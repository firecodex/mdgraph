"""SQLite FTS5 and Recursive CTE Vectorless Query Cache for MdGraph."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from mdgraph.indexer.base import BaseQueryCache
from mdgraph.models import GraphStats, OKFConcept, SearchResult, TraverseResult


class SQLiteQueryCache(BaseQueryCache):
    """Sub-millisecond relational query cache using SQLite FTS5 and Recursive CTEs."""

    def __init__(self, db_path: str | Path = ":memory:"):
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn: Optional[sqlite3.Connection] = None
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
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                status TEXT DEFAULT 'stable',
                metadata TEXT DEFAULT '{}',
                body TEXT DEFAULT '',
                file_path TEXT NOT NULL,
                commit_hash TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 2. Graph Edges Table (Explicit cross-links)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                label TEXT DEFAULT 'references',
                link_text TEXT,
                raw_target TEXT,
                FOREIGN KEY (source_id) REFERENCES concepts(id) ON DELETE CASCADE
            );
        """)

        # Indexes for fast edge joins and recursive CTE lookups
        cur.execute("CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_edges_pair ON edges(source_id, target_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_concepts_type ON concepts(type);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_concepts_commit ON concepts(commit_hash);")

        # 3. Full-Text Search Table (FTS5)
        cur.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS concepts_fts USING fts5(
                id UNINDEXED,
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

        # Check existing commit hash
        cur.execute("SELECT commit_hash FROM concepts WHERE id = ?", (concept.id,))
        row = cur.fetchone()
        if row and row["commit_hash"] == concept.commit_hash and concept.commit_hash is not None:
            # Hash unchanged, skip redundant re-indexing
            return

        tags_json = json.dumps(concept.tags, ensure_ascii=False)
        metadata_json = json.dumps(concept.metadata, ensure_ascii=False)

        # Upsert concept row
        cur.execute("""
            INSERT INTO concepts (id, type, title, description, tags, status, metadata, body, file_path, commit_hash, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
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
            concept.id,
            concept.type,
            concept.title,
            concept.description,
            tags_json,
            concept.status,
            metadata_json,
            concept.body,
            concept.file_path or f"concepts/{concept.id}.md",
            concept.commit_hash,
        ))

        # Refresh FTS5 index
        cur.execute("DELETE FROM concepts_fts WHERE id = ?", (concept.id,))
        tags_text = " ".join(concept.tags)
        cur.execute("""
            INSERT INTO concepts_fts (id, title, description, body, tags)
            VALUES (?, ?, ?, ?, ?);
        """, (
            concept.id,
            concept.title,
            concept.description,
            concept.body,
            tags_text,
        ))

        # Rebuild edges from this source
        cur.execute("DELETE FROM edges WHERE source_id = ?", (concept.id,))
        for edge in concept.edges:
            cur.execute("""
                INSERT INTO edges (source_id, target_id, label, link_text, raw_target)
                VALUES (?, ?, ?, ?, ?);
            """, (
                edge.source_id,
                edge.target_id,
                edge.label or "references",
                edge.link_text or "",
                edge.raw_target or "",
            ))

        self.conn.commit()

    def delete_concept(self, node_id: str) -> None:
        """Delete concept, its edges, and FTS entries."""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM concepts WHERE id = ?", (node_id,))
        cur.execute("DELETE FROM concepts_fts WHERE id = ?", (node_id,))
        cur.execute("DELETE FROM edges WHERE source_id = ? OR target_id = ?", (node_id, node_id))
        self.conn.commit()

    def get_concept(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve concept metadata and associated edges by ID."""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM concepts WHERE id = ?", (node_id,))
        row = cur.fetchone()
        if not row:
            return None

        data = dict(row)
        data["tags"] = json.loads(data["tags"])
        data["metadata"] = json.loads(data["metadata"])

        # Fetch outgoing edges
        cur.execute("SELECT target_id, label, link_text FROM edges WHERE source_id = ?", (node_id,))
        data["outgoing_edges"] = [dict(r) for r in cur.fetchall()]

        # Fetch incoming edges (backlinks)
        cur.execute("SELECT source_id, label, link_text FROM edges WHERE target_id = ?", (node_id,))
        data["incoming_edges"] = [dict(r) for r in cur.fetchall()]

        return data

    def search(
        self,
        query: str,
        tags: Optional[List[str]] = None,
        concept_type: Optional[str] = None,
        limit: int = 10,
    ) -> List[SearchResult]:
        """BM25 full-text keyword search across title, description, body, and tags."""
        cur = self.conn.cursor()

        # Sanitize query for FTS5 syntax
        # Escape quotes and characters that break FTS5
        clean_query = query.replace('"', '""').strip()
        if not clean_query:
            return []

        # If user searched multi-word string, format as tokens or phrase
        fts_terms = [t for t in clean_query.split() if t]
        if not fts_terms:
            return []

        # Construct FTS MATCH expression (prefix match on terms)
        fts_query = " ".join(f'"{t}"*' for t in fts_terms)

        sql = """
            SELECT
                c.id,
                c.type,
                c.title,
                c.description,
                c.tags,
                c.file_path,
                bm25(concepts_fts) as rank,
                snippet(concepts_fts, 3, '<b>', '</b>', '...', 20) as snippet
            FROM concepts_fts
            JOIN concepts c ON c.id = concepts_fts.id
            WHERE concepts_fts MATCH ?
        """
        params: List[Any] = [fts_query]

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
                SELECT id, type, title, description, tags, file_path, 0.0 as rank, substr(body, 1, 120) as snippet
                FROM concepts
                WHERE (title LIKE ? OR description LIKE ? OR body LIKE ?)
            """
            like_param = f"%{query}%"
            f_params: List[Any] = [like_param, like_param, like_param]
            if concept_type:
                fallback_sql += " AND type = ?"
                f_params.append(concept_type)
            fallback_sql += " LIMIT ?"
            f_params.append(limit)
            cur.execute(fallback_sql, f_params)
            rows = cur.fetchall()

        results: List[SearchResult] = []
        for r in rows:
            parsed_tags = json.loads(r["tags"]) if isinstance(r["tags"], str) else (r["tags"] or [])
            results.append(
                SearchResult(
                    id=r["id"],
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
    ) -> TraverseResult:
        """Execute exact Recursive CTE multi-hop topological traversal."""
        cur = self.conn.cursor()

        if direction == "in":
            # Reverse traversal: follow incoming links to node_id
            cte_sql = """
                WITH RECURSIVE graph_path AS (
                    SELECT source_id, target_id, label, link_text, 1 as depth,
                           target_id || '<-' || source_id as path
                    FROM edges WHERE target_id = ?
                    UNION ALL
                    SELECT e.source_id, e.target_id, e.label, e.link_text, gp.depth + 1,
                           gp.path || '<-' || e.source_id
                    FROM edges e
                    JOIN graph_path gp ON e.target_id = gp.source_id
                    WHERE gp.depth < ?
                      AND instr(gp.path, e.source_id) = 0
                )
                SELECT source_id, target_id, label, link_text, depth, path FROM graph_path;
            """
            cur.execute(cte_sql, (node_id, max_depth))
        elif direction == "both":
            # Undirected traversal: both outgoing and incoming edges
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
                    WHERE source_id = ? OR target_id = ?

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
                    WHERE gp.depth < ?
                      AND instr(gp.path, CASE WHEN e.source_id = gp.to_node THEN e.target_id ELSE e.source_id END) = 0
                )
                SELECT from_node as source_id, to_node as target_id, label, link_text, depth, path FROM graph_path;
            """
            cur.execute(cte_sql, (node_id, node_id, node_id, node_id, node_id, node_id, max_depth))
        else:
            # Standard outgoing traversal via Recursive CTE as described in the architecture
            cte_sql = """
                WITH RECURSIVE graph_path AS (
                    SELECT source_id, target_id, label, link_text, 1 as depth,
                           source_id || '->' || target_id as path
                    FROM edges WHERE source_id = ?
                    UNION ALL
                    SELECT e.source_id, e.target_id, e.label, e.link_text, gp.depth + 1,
                           gp.path || '->' || e.target_id
                    FROM edges e
                    JOIN graph_path gp ON e.source_id = gp.target_id
                    WHERE gp.depth < ?
                      AND instr(gp.path, e.target_id) = 0
                )
                SELECT source_id, target_id, label, link_text, depth, path FROM graph_path;
            """
            cur.execute(cte_sql, (node_id, max_depth))

        edge_rows = cur.fetchall()

        collected_node_ids: Set[str] = {node_id}
        edges_list: List[Dict[str, Any]] = []
        paths_list: List[List[str]] = []

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

        # Hydrate all collected nodes with their metadata
        nodes_list: List[Dict[str, Any]] = []
        if collected_node_ids:
            placeholders = ",".join("?" for _ in collected_node_ids)
            cur.execute(f"""
                SELECT id, type, title, description, tags, status, file_path
                FROM concepts WHERE id IN ({placeholders})
            """, list(collected_node_ids))

            for nr in cur.fetchall():
                nodes_list.append({
                    "id": nr["id"],
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
    ) -> Optional[List[str]]:
        """Find the shortest topological path between two concepts using Recursive CTE."""
        if source_id == target_id:
            return [source_id]

        cur = self.conn.cursor()
        sql = """
            WITH RECURSIVE path_finder AS (
                SELECT source_id, target_id, 1 as depth,
                       source_id || '->' || target_id as path
                FROM edges
                WHERE source_id = ?

                UNION ALL

                SELECT e.source_id, e.target_id, pf.depth + 1,
                       pf.path || '->' || e.target_id
                FROM edges e
                JOIN path_finder pf ON e.source_id = pf.target_id
                WHERE pf.depth < ?
                  AND instr(pf.path, e.target_id) = 0
            )
            SELECT path FROM path_finder
            WHERE target_id = ?
            ORDER BY depth ASC
            LIMIT 1;
        """
        cur.execute(sql, (source_id, max_depth, target_id))
        row = cur.fetchone()
        if row and row["path"]:
            return [p for p in row["path"].split("->") if p]
        return None

    def list_concepts(
        self,
        concept_type: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List concepts filtered by scalar type or tag."""
        cur = self.conn.cursor()
        sql = "SELECT id, type, title, description, tags, status, file_path, commit_hash FROM concepts WHERE 1=1"
        params: List[Any] = []

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

    def get_stats(self) -> GraphStats:
        """Compute summary statistics across concepts and edges."""
        cur = self.conn.cursor()

        cur.execute("SELECT COUNT(*) as cnt FROM concepts;")
        total_concepts = cur.fetchone()["cnt"]

        cur.execute("SELECT COUNT(*) as cnt FROM edges;")
        total_edges = cur.fetchone()["cnt"]

        cur.execute("SELECT type, COUNT(*) as cnt FROM concepts GROUP BY type ORDER BY cnt DESC;")
        concept_types = {r["type"]: r["cnt"] for r in cur.fetchall()}

        # Top tags aggregation
        cur.execute("SELECT tags FROM concepts WHERE tags IS NOT NULL;")
        tag_counts: Dict[str, int] = {}
        for r in cur.fetchall():
            try:
                tags = json.loads(r["tags"])
                for t in tags:
                    tag_counts[t] = tag_counts.get(t, 0) + 1
            except Exception:
                pass

        sorted_tags = dict(sorted(tag_counts.items(), key=lambda item: item[1], reverse=True)[:10])

        return GraphStats(
            total_concepts=total_concepts,
            total_edges=total_edges,
            concept_types=concept_types,
            top_tags=sorted_tags,
        )

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
