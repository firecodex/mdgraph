"""SQLite FTS5 and Recursive CTE Vectorless Query Cache for MdGraph."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from mdgraph.indexer.base import BaseQueryCache
from mdgraph.models import GraphStats, OKFConcept, SearchResult, TraverseResult


class SQLiteQueryCache(BaseQueryCache):
    """Sub-millisecond relational query cache using SQLite FTS5 and Recursive CTEs."""

    def __init__(self, db_path: str | Path = ":memory:"):
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn: sqlite3.Connection | None = None
        self._init_db()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON;")
            self._conn.execute("PRAGMA journal_mode = WAL;")
        return self._conn

    def _init_db(self) -> None:
        """Create tables, indexes, and FTS5 virtual tables."""
        cur = self.conn.cursor()

        # 1. Core Concepts Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS concepts (
                tenant_id TEXT NOT NULL DEFAULT 'default',
                id TEXT NOT NULL,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                status TEXT DEFAULT 'stable',
                metadata TEXT DEFAULT '{}',
                body TEXT DEFAULT '',
                file_path TEXT NOT NULL,
                commit_hash TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tenant_id, id)
            );
        """)

        # Migration check: ensure tenant_id column exists if table was created previously
        cur.execute("PRAGMA table_info(concepts);")
        c_cols = [row[1] for row in cur.fetchall()]
        if c_cols and "tenant_id" not in c_cols:
            cur.execute("ALTER TABLE concepts ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default';")
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_concepts_tenant_id ON concepts(tenant_id, id);")

        # 2. Graph Edges Table (Explicit cross-links)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                label TEXT DEFAULT 'references',
                link_text TEXT,
                raw_target TEXT
            );
        """)

        # Migration check: ensure tenant_id column exists on edges
        cur.execute("PRAGMA table_info(edges);")
        e_cols = [row[1] for row in cur.fetchall()]
        if e_cols and "tenant_id" not in e_cols:
            cur.execute("ALTER TABLE edges ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default';")

        # Indexes for fast edge joins and recursive CTE lookups
        cur.execute("CREATE INDEX IF NOT EXISTS idx_concepts_tenant ON concepts(tenant_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_edges_tenant ON edges(tenant_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_edges_tenant_source ON edges(tenant_id, source_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_edges_tenant_target ON edges(tenant_id, target_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_edges_tenant_pair ON edges(tenant_id, source_id, target_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_concepts_type ON concepts(tenant_id, type);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_concepts_commit ON concepts(commit_hash);")

        # 3. Full-Text Search Table (FTS5)
        # Check if concepts_fts already exists with tenant_id
        cur.execute("PRAGMA table_info(concepts_fts);")
        fts_cols = [row[1] for row in cur.fetchall()]
        if fts_cols and "tenant_id" not in fts_cols:
            cur.execute("DROP TABLE concepts_fts;")
            fts_cols = []

        if not fts_cols:
            cur.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS concepts_fts USING fts5(
                    id UNINDEXED,
                    tenant_id UNINDEXED,
                    title,
                    description,
                    body,
                    tags,
                    tokenize = 'porter unicode61'
                );
            """)

        self.conn.commit()

    def insert_or_update_concept(self, concept: OKFConcept) -> None:
        """Insert or replace concept in SQLite, update FTS5, and rebuild its edges."""
        cur = self.conn.cursor()
        tenant_id = concept.tenant_id or "default"

        # Check existing commit hash
        cur.execute("SELECT commit_hash FROM concepts WHERE tenant_id = ? AND id = ?", (tenant_id, concept.id))
        row = cur.fetchone()
        if row and row["commit_hash"] == concept.commit_hash and concept.commit_hash is not None:
            # Hash unchanged, skip redundant re-indexing
            return

        tags_json = json.dumps(concept.tags, ensure_ascii=False)
        metadata_dict = concept.to_metadata_dict()
        metadata_json = json.dumps(metadata_dict, ensure_ascii=False)

        # Upsert concept row
        cur.execute("""
            INSERT INTO concepts (tenant_id, id, type, title, description, tags, status, metadata, body, file_path, commit_hash, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(tenant_id, id) DO UPDATE SET
                type=excluded.type,
                title=excluded.title,
                description=excluded.description,
                tags=excluded.tags,
                status=excluded.status,
                metadata=excluded.metadata,
                body=excluded.body,
                file_path=excluded.file_path,
                commit_hash=excluded.commit_hash,
                updated_at=CURRENT_TIMESTAMP;
        """, (
            tenant_id,
            concept.id,
            concept.type,
            concept.title,
            concept.description,
            tags_json,
            concept.status,
            metadata_json,
            concept.body,
            concept.file_path or (f"tenants/{tenant_id}/concepts/{concept.id}.md" if tenant_id != "default" else f"concepts/{concept.id}.md"),
            concept.commit_hash,
        ))

        # Refresh FTS5 index
        cur.execute("DELETE FROM concepts_fts WHERE tenant_id = ? AND id = ?", (tenant_id, concept.id))
        tags_text = " ".join(concept.tags)
        cur.execute("""
            INSERT INTO concepts_fts (id, tenant_id, title, description, body, tags)
            VALUES (?, ?, ?, ?, ?, ?);
        """, (
            concept.id,
            tenant_id,
            concept.title,
            concept.description,
            concept.body,
            tags_text,
        ))

        # Rebuild edges from this source
        cur.execute("DELETE FROM edges WHERE tenant_id = ? AND source_id = ?", (tenant_id, concept.id))
        for edge in concept.edges:
            edge_tenant = edge.tenant_id or tenant_id
            cur.execute("""
                INSERT INTO edges (tenant_id, source_id, target_id, label, link_text, raw_target)
                VALUES (?, ?, ?, ?, ?, ?);
            """, (
                edge_tenant,
                edge.source_id,
                edge.target_id,
                edge.label or "references",
                edge.link_text or "",
                edge.raw_target or "",
            ))

        self.conn.commit()

    def delete_concept(self, node_id: str, tenant_id: str | None = None) -> None:
        """Delete concept, its edges, and FTS entries scoped to tenant (or across tenants if None)."""
        cur = self.conn.cursor()
        if tenant_id is not None:
            cur.execute("DELETE FROM concepts WHERE tenant_id = ? AND id = ?", (tenant_id, node_id))
            cur.execute("DELETE FROM concepts_fts WHERE tenant_id = ? AND id = ?", (tenant_id, node_id))
            cur.execute(
                "DELETE FROM edges WHERE tenant_id = ? AND (source_id = ? OR target_id = ?)",
                (tenant_id, node_id, node_id),
            )
        else:
            cur.execute("DELETE FROM concepts WHERE id = ?", (node_id,))
            cur.execute("DELETE FROM concepts_fts WHERE id = ?", (node_id,))
            cur.execute("DELETE FROM edges WHERE source_id = ? OR target_id = ?", (node_id, node_id))
        self.conn.commit()

    def get_concept(self, node_id: str, tenant_id: str | None = None) -> dict[str, Any] | None:
        """Retrieve concept metadata and associated edges by ID within tenant (or across tenants if None)."""
        cur = self.conn.cursor()
        if tenant_id is not None:
            cur.execute("SELECT * FROM concepts WHERE tenant_id = ? AND id = ?", (tenant_id, node_id))
        else:
            cur.execute(
                "SELECT * FROM concepts WHERE id = ? ORDER BY CASE WHEN tenant_id = 'default' THEN 0 ELSE 1 END LIMIT 1",
                (node_id,),
            )
        row = cur.fetchone()
        if not row:
            return None

        data = dict(row)
        actual_tenant = data["tenant_id"]
        data["tags"] = json.loads(data["tags"])
        data["metadata"] = json.loads(data["metadata"])
        meta = data["metadata"]
        for key in ["okf_version", "resource", "stale_after", "generated", "verified", "sources", "is_verified", "is_stale"]:
            if key in meta:
                data[key] = meta[key]

        # Fetch outgoing edges scoped to tenant
        cur.execute("SELECT target_id, label, link_text FROM edges WHERE tenant_id = ? AND source_id = ?", (actual_tenant, node_id))
        data["outgoing_edges"] = [dict(r) for r in cur.fetchall()]

        # Fetch incoming edges (backlinks) scoped to tenant
        cur.execute("SELECT source_id, label, link_text FROM edges WHERE tenant_id = ? AND target_id = ?", (actual_tenant, node_id))
        data["incoming_edges"] = [dict(r) for r in cur.fetchall()]

        return data

    def search(
        self,
        query: str,
        tags: list[str] | None = None,
        concept_type: str | None = None,
        tenant_id: str | None = None,
        limit: int = 10,
    ) -> list[SearchResult]:
        """BM25 full-text keyword search across title, description, body, and tags (scoped to tenant if specified)."""
        cur = self.conn.cursor()

        # Sanitize query for FTS5 syntax
        clean_query = query.replace('"', '""').strip()
        if not clean_query:
            return []

        fts_terms = [t for t in clean_query.split() if t]
        if not fts_terms:
            return []

        # Construct FTS MATCH expression (prefix match on terms)
        fts_query = " ".join(f'"{t}"*' for t in fts_terms)

        sql = """
            SELECT
                c.id,
                c.tenant_id,
                c.type,
                c.title,
                c.description,
                c.tags,
                c.file_path,
                bm25(concepts_fts) as rank,
                snippet(concepts_fts, 4, '<b>', '</b>', '...', 20) as snippet
            FROM concepts_fts
            JOIN concepts c ON c.id = concepts_fts.id AND c.tenant_id = concepts_fts.tenant_id
            WHERE concepts_fts MATCH ?
        """
        params: list[Any] = [fts_query]

        if tenant_id and tenant_id.lower() != "all":
            sql += " AND c.tenant_id = ?"
            params.append(tenant_id)

        if concept_type:
            sql += " AND c.type = ?"
            params.append(concept_type)

        if tags:
            for t in tags:
                sql += " AND c.tags LIKE ?"
                params.append(f'%"{t}"%')

        sql += " ORDER BY rank ASC LIMIT ?"
        params.append(limit)

        try:
            cur.execute(sql, params)
            rows = cur.fetchall()
        except sqlite3.OperationalError:
            # Fallback to standard exact substring query if FTS expression is unusual
            fallback_sql = """
                SELECT id, tenant_id, type, title, description, tags, file_path, 0.0 as rank, substr(body, 1, 120) as snippet
                FROM concepts
                WHERE (title LIKE ? OR description LIKE ? OR body LIKE ?)
            """
            like_param = f"%{query}%"
            f_params: list[Any] = [like_param, like_param, like_param]
            if tenant_id and tenant_id.lower() != "all":
                fallback_sql += " AND tenant_id = ?"
                f_params.append(tenant_id)
            if concept_type:
                fallback_sql += " AND type = ?"
                f_params.append(concept_type)
            fallback_sql += " LIMIT ?"
            f_params.append(limit)
            cur.execute(fallback_sql, f_params)
            rows = cur.fetchall()

        results: list[SearchResult] = []
        for r in rows:
            parsed_tags = json.loads(r["tags"]) if isinstance(r["tags"], str) else (r["tags"] or [])
            results.append(
                SearchResult(
                    id=r["id"],
                    tenant_id=r["tenant_id"] if "tenant_id" in r.keys() else "default",
                    type=r["type"],
                    title=r["title"],
                    description=r["description"] or "",
                    tags=parsed_tags,
                    rank=float(r["rank"]),
                    snippet=r["snippet"],
                    file_path=r["file_path"],
                )
            )
        return results

    def traverse(
        self,
        node_id: str,
        max_depth: int = 2,
        direction: str = "out",
        tenant_id: str | None = None,
    ) -> TraverseResult:
        """Execute exact Recursive CTE multi-hop topological traversal (auto-resolving tenant if None)."""
        cur = self.conn.cursor()

        if tenant_id is None:
            cur.execute(
                "SELECT tenant_id FROM concepts WHERE id = ? ORDER BY CASE WHEN tenant_id = 'default' THEN 0 ELSE 1 END LIMIT 1",
                (node_id,),
            )
            t_row = cur.fetchone()
            resolved_tenant = t_row["tenant_id"] if t_row else "default"
        else:
            resolved_tenant = tenant_id

        if direction == "in":
            # Reverse traversal: follow incoming links to node_id within tenant
            cte_sql = """
                WITH RECURSIVE graph_path AS (
                    SELECT source_id, target_id, label, link_text, 1 as depth,
                           target_id || '<-' || source_id as path
                    FROM edges WHERE tenant_id = ? AND target_id = ?
                    UNION ALL
                    SELECT e.source_id, e.target_id, e.label, e.link_text, gp.depth + 1,
                           gp.path || '<-' || e.source_id
                    FROM edges e
                    JOIN graph_path gp ON e.target_id = gp.source_id
                    WHERE e.tenant_id = ? AND gp.depth < ?
                      AND instr(gp.path, e.source_id) = 0
                )
                SELECT source_id, target_id, label, link_text, depth, path FROM graph_path;
            """
            cur.execute(cte_sql, (resolved_tenant, node_id, resolved_tenant, max_depth))
        elif direction == "both":
            # Undirected traversal within tenant
            cte_sql = """
                WITH RECURSIVE graph_path AS (
                    SELECT
                        CASE WHEN source_id = ? THEN source_id ELSE target_id END as from_node,
                        CASE WHEN source_id = ? THEN target_id ELSE source_id END as to_node,
                        label,
                        link_text,
                        1 as depth,
                        ? || '->' || CASE WHEN source_id = ? THEN target_id ELSE source_id END as path
                    FROM edges
                    WHERE tenant_id = ? AND (source_id = ? OR target_id = ?)

                    UNION ALL

                    SELECT
                        CASE WHEN e.source_id = gp.to_node THEN e.source_id ELSE e.target_id END,
                        CASE WHEN e.source_id = gp.to_node THEN e.target_id ELSE e.source_id END,
                        e.label,
                        e.link_text,
                        gp.depth + 1,
                        gp.path || '->' || CASE WHEN e.source_id = gp.to_node THEN e.target_id ELSE e.source_id END
                    FROM edges e
                    JOIN graph_path gp ON (e.source_id = gp.to_node OR e.target_id = gp.to_node)
                    WHERE e.tenant_id = ? AND gp.depth < ?
                      AND instr(gp.path, CASE WHEN e.source_id = gp.to_node THEN e.target_id ELSE e.source_id END) = 0
                )
                SELECT from_node as source_id, to_node as target_id, label, link_text, depth, path FROM graph_path;
            """
            cur.execute(cte_sql, (node_id, node_id, node_id, node_id, resolved_tenant, node_id, node_id, resolved_tenant, max_depth))
        else:
            # Standard outgoing traversal via Recursive CTE within tenant
            cte_sql = """
                WITH RECURSIVE graph_path AS (
                    SELECT source_id, target_id, label, link_text, 1 as depth,
                           source_id || '->' || target_id as path
                    FROM edges WHERE tenant_id = ? AND source_id = ?
                    UNION ALL
                    SELECT e.source_id, e.target_id, e.label, e.link_text, gp.depth + 1,
                           gp.path || '->' || e.target_id
                    FROM edges e
                    JOIN graph_path gp ON e.source_id = gp.target_id
                    WHERE e.tenant_id = ? AND gp.depth < ?
                      AND instr(gp.path, e.target_id) = 0
                )
                SELECT source_id, target_id, label, link_text, depth, path FROM graph_path;
            """
            cur.execute(cte_sql, (resolved_tenant, node_id, resolved_tenant, max_depth))

        edge_rows = cur.fetchall()

        collected_node_ids: set[str] = {node_id}
        edges_list: list[dict[str, Any]] = []
        paths_list: list[list[str]] = []

        for row in edge_rows:
            src = row["source_id"]
            tgt = row["target_id"]
            collected_node_ids.add(src)
            collected_node_ids.add(tgt)
            edges_list.append({
                "source": src,
                "target": tgt,
                "label": row["label"],
                "link_text": row["link_text"],
                "depth": row["depth"],
            })
            if "path" in row.keys() and row["path"]:
                split_path = [n for n in row["path"].replace("<-", "->").split("->") if n]
                if split_path not in paths_list:
                    paths_list.append(split_path)

        # Hydrate all collected nodes with their metadata scoped to tenant
        nodes_list: list[dict[str, Any]] = []
        if collected_node_ids:
            placeholders = ",".join("?" for _ in collected_node_ids)
            cur.execute(f"""
                SELECT id, tenant_id, type, title, description, tags, status, file_path
                FROM concepts WHERE tenant_id = ? AND id IN ({placeholders})
            """, [resolved_tenant] + list(collected_node_ids))

            for nr in cur.fetchall():
                nodes_list.append({
                    "id": nr["id"],
                    "tenant_id": nr["tenant_id"],
                    "type": nr["type"],
                    "title": nr["title"],
                    "description": nr["description"],
                    "tags": json.loads(nr["tags"]) if nr["tags"] else [],
                    "status": nr["status"],
                    "file_path": nr["file_path"],
                    "is_root": (nr["id"] == node_id),
                })

        return TraverseResult(
            root_id=node_id,
            tenant_id=resolved_tenant,
            max_depth=max_depth,
            direction=direction,
            nodes=nodes_list,
            edges=edges_list,
            paths=paths_list,
        )

    def find_path(
        self,
        source_id: str,
        target_id: str,
        max_depth: int = 5,
        tenant_id: str | None = None,
    ) -> list[str] | None:
        """Find the shortest topological path between two concepts within tenant using Recursive CTE."""
        if source_id == target_id:
            return [source_id]

        cur = self.conn.cursor()

        if tenant_id is None:
            cur.execute(
                "SELECT tenant_id FROM concepts WHERE id = ? ORDER BY CASE WHEN tenant_id = 'default' THEN 0 ELSE 1 END LIMIT 1",
                (source_id,),
            )
            t_row = cur.fetchone()
            resolved_tenant = t_row["tenant_id"] if t_row else "default"
        else:
            resolved_tenant = tenant_id

        sql = """
            WITH RECURSIVE path_finder AS (
                SELECT source_id, target_id, 1 as depth,
                       source_id || '->' || target_id as path
                FROM edges
                WHERE tenant_id = ? AND source_id = ?

                UNION ALL

                SELECT e.source_id, e.target_id, pf.depth + 1,
                       pf.path || '->' || e.target_id
                FROM edges e
                JOIN path_finder pf ON e.source_id = pf.target_id
                WHERE e.tenant_id = ? AND pf.depth < ?
                  AND instr(pf.path, e.target_id) = 0
            )
            SELECT path FROM path_finder
            WHERE target_id = ?
            ORDER BY depth ASC
            LIMIT 1;
        """
        cur.execute(sql, (resolved_tenant, source_id, resolved_tenant, max_depth, target_id))
        row = cur.fetchone()
        if row and row["path"]:
            return [p for p in row["path"].split("->") if p]
        return None

    def list_concepts(
        self,
        concept_type: str | None = None,
        tag: str | None = None,
        tenant_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List concepts filtered by scalar type, tag, or tenant (all tenants if None)."""
        cur = self.conn.cursor()
        sql = "SELECT id, tenant_id, type, title, description, tags, status, file_path, commit_hash FROM concepts WHERE 1=1"
        params: list[Any] = []

        if tenant_id and tenant_id.lower() != "all":
            sql += " AND tenant_id = ?"
            params.append(tenant_id)

        if concept_type:
            sql += " AND type = ?"
            params.append(concept_type)

        if tag:
            sql += " AND tags LIKE ?"
            params.append(f'%"{tag}"%')

        sql += " ORDER BY title ASC LIMIT ?"
        params.append(limit)

        cur.execute(sql, params)
        out = []
        for r in cur.fetchall():
            d = dict(r)
            d["tags"] = json.loads(d["tags"]) if d["tags"] else []
            out.append(d)
        return out

    def get_stats(self, tenant_id: str | None = None) -> GraphStats:
        """Compute summary statistics across concepts and edges (optionally scoped to tenant)."""
        cur = self.conn.cursor()

        concept_filter = " WHERE tenant_id = ?" if tenant_id else ""
        edge_filter = " WHERE tenant_id = ?" if tenant_id else ""
        params = [tenant_id] if tenant_id else []

        cur.execute(f"SELECT COUNT(*) as cnt FROM concepts{concept_filter};", params)
        total_concepts = cur.fetchone()["cnt"]

        cur.execute(f"SELECT COUNT(*) as cnt FROM edges{edge_filter};", params)
        total_edges = cur.fetchone()["cnt"]

        cur.execute(
            f"SELECT type, COUNT(*) as cnt FROM concepts{concept_filter} GROUP BY type ORDER BY cnt DESC;",
            params,
        )
        concept_types = {r["type"]: r["cnt"] for r in cur.fetchall()}

        # Top tags aggregation
        cur.execute(f"SELECT tags FROM concepts{concept_filter} AND tags IS NOT NULL;" if tenant_id else "SELECT tags FROM concepts WHERE tags IS NOT NULL;", params)
        tag_counts: dict[str, int] = {}
        for r in cur.fetchall():
            try:
                tags = json.loads(r["tags"])
                for t in tags:
                    tag_counts[t] = tag_counts.get(t, 0) + 1
            except Exception:
                pass

        sorted_tags = dict(sorted(tag_counts.items(), key=lambda item: item[1], reverse=True)[:10])

        all_tenants = self.list_tenants()

        return GraphStats(
            total_concepts=total_concepts,
            total_edges=total_edges,
            concept_types=concept_types,
            top_tags=sorted_tags,
            tenant_id=tenant_id,
            tenants=all_tenants,
        )

    def list_tenants(self) -> list[str]:
        """Return list of distinct active tenant workspace identifiers."""
        cur = self.conn.cursor()
        cur.execute("SELECT DISTINCT tenant_id FROM concepts ORDER BY tenant_id ASC;")
        tenants = [r[0] for r in cur.fetchall() if r[0]]
        return tenants if tenants else ["default"]

    def clear(self) -> None:
        """Drop all tables."""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM edges;")
        cur.execute("DELETE FROM concepts;")
        cur.execute("DELETE FROM concepts_fts;")
        self.conn.commit()

    def close(self) -> None:
        """Close connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
