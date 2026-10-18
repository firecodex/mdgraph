"""PostgreSQL JSONB and Recursive CTE Vectorless Query Cache for MdGraph."""

from __future__ import annotations

import json
from typing import Any

from mdgraph.indexer.base import BaseQueryCache
from mdgraph.models import GraphStats, OKFConcept, SearchResult, TraverseResult


class PostgresQueryCache(BaseQueryCache):
    """PostgreSQL backend for enterprise-grade MdGraph deployment."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        try:
            import psycopg
            from psycopg.rows import dict_row
            self._psycopg = psycopg
            self._dict_row = dict_row
        except ImportError as err:
            raise ImportError(
                "PostgreSQL support requires 'psycopg'. Install with: pip install mdgraph-ai[postgres]"
            ) from err

        self._conn = None
        self._init_db()

    @property
    def conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = self._psycopg.connect(self.dsn, row_factory=self._dict_row, autocommit=True)
        return self._conn

    def _init_db(self) -> None:
        with self.conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS concepts (
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    tags JSONB DEFAULT '[]'::jsonb,
                    status TEXT DEFAULT 'stable',
                    metadata JSONB DEFAULT '{}'::jsonb,
                    body TEXT DEFAULT '',
                    file_path TEXT NOT NULL,
                    commit_hash TEXT,
                    tsv_body tsvector GENERATED ALWAYS AS (to_tsvector('english', title || ' ' || description || ' ' || body)) STORED,
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (tenant_id, id)
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS edges (
                    id BIGSERIAL PRIMARY KEY,
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    label TEXT DEFAULT 'references',
                    link_text TEXT,
                    raw_target TEXT
                );
            """)

            cur.execute("CREATE INDEX IF NOT EXISTS idx_pg_concepts_tenant ON concepts(tenant_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_pg_edges_tenant ON edges(tenant_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_pg_edges_source ON edges(tenant_id, source_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_pg_edges_target ON edges(tenant_id, target_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_pg_concepts_tags ON concepts USING GIN (tags);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_pg_concepts_tsv ON concepts USING GIN (tsv_body);")

    def insert_or_update_concept(self, concept: OKFConcept) -> None:
        tenant_id = concept.tenant_id or "default"
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO concepts (tenant_id, id, type, title, description, tags, status, metadata, body, file_path, commit_hash, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s, %s, %s, NOW())
                ON CONFLICT (tenant_id, id) DO UPDATE SET
                    type = EXCLUDED.type,
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    tags = EXCLUDED.tags,
                    status = EXCLUDED.status,
                    metadata = EXCLUDED.metadata,
                    body = EXCLUDED.body,
                    file_path = EXCLUDED.file_path,
                    commit_hash = EXCLUDED.commit_hash,
                    updated_at = NOW();
            """, (
                tenant_id,
                concept.id,
                concept.type,
                concept.title,
                concept.description,
                json.dumps(concept.tags),
                concept.status,
                json.dumps(concept.to_metadata_dict()),
                concept.body,
                concept.file_path or (f"tenants/{tenant_id}/concepts/{concept.id}.md" if tenant_id != "default" else f"concepts/{concept.id}.md"),
                concept.commit_hash,
            ))

            cur.execute("DELETE FROM edges WHERE tenant_id = %s AND source_id = %s;", (tenant_id, concept.id))
            for edge in concept.edges:
                edge_tenant = edge.tenant_id or tenant_id
                cur.execute("""
                    INSERT INTO edges (tenant_id, source_id, target_id, label, link_text, raw_target)
                    VALUES (%s, %s, %s, %s, %s, %s);
                """, (
                    edge_tenant,
                    edge.source_id,
                    edge.target_id,
                    edge.label or "references",
                    edge.link_text or "",
                    edge.raw_target or "",
                ))

    def delete_concept(self, node_id: str, tenant_id: str | None = None) -> None:
        with self.conn.cursor() as cur:
            if tenant_id is not None:
                cur.execute("DELETE FROM concepts WHERE tenant_id = %s AND id = %s;", (tenant_id, node_id))
                cur.execute(
                    "DELETE FROM edges WHERE tenant_id = %s AND (source_id = %s OR target_id = %s);",
                    (tenant_id, node_id, node_id),
                )
            else:
                cur.execute("DELETE FROM concepts WHERE id = %s;", (node_id,))
                cur.execute("DELETE FROM edges WHERE source_id = %s OR target_id = %s;", (node_id, node_id))

    def get_concept(self, node_id: str, tenant_id: str | None = None) -> dict[str, Any] | None:
        with self.conn.cursor() as cur:
            if tenant_id is not None:
                cur.execute("SELECT * FROM concepts WHERE tenant_id = %s AND id = %s;", (tenant_id, node_id))
            else:
                cur.execute(
                    "SELECT * FROM concepts WHERE id = %s ORDER BY CASE WHEN tenant_id = 'default' THEN 0 ELSE 1 END LIMIT 1;",
                    (node_id,),
                )
            row = cur.fetchone()
            if not row:
                return None
            data = dict(row)
            actual_tenant = data.get("tenant_id", "default")
            meta = data.get("metadata", {})
            if isinstance(meta, dict):
                for key in ["okf_version", "resource", "stale_after", "generated", "verified", "sources", "is_verified", "is_stale"]:
                    if key in meta:
                        data[key] = meta[key]
            cur.execute("SELECT target_id, label, link_text FROM edges WHERE tenant_id = %s AND source_id = %s;", (actual_tenant, node_id))
            data["outgoing_edges"] = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT source_id, label, link_text FROM edges WHERE tenant_id = %s AND target_id = %s;", (actual_tenant, node_id))
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
        with self.conn.cursor() as cur:
            sql = """
                SELECT id, tenant_id, type, title, description, tags, file_path,
                       ts_rank(tsv_body, plainto_tsquery('english', %s)) as rank,
                       ts_headline('english', body, plainto_tsquery('english', %s), 'StartSel=[MATCH], StopSel=[/MATCH], MaxWords=20') as snippet
                FROM concepts
                WHERE tsv_body @@ plainto_tsquery('english', %s)
            """
            params: list[Any] = [query, query, query]
            if tenant_id and tenant_id.lower() != "all":
                sql += " AND tenant_id = %s"
                params.append(tenant_id)
            if concept_type:
                sql += " AND type = %s"
                params.append(concept_type)
            if tags:
                sql += " AND tags ?& %s"
                params.append(tags)

            sql += " ORDER BY rank DESC LIMIT %s;"
            params.append(limit)

            cur.execute(sql, params)
            rows = cur.fetchall()
            return [
                SearchResult(
                    id=r["id"],
                    tenant_id=r.get("tenant_id", "default"),
                    type=r["type"],
                    title=r["title"],
                    description=r["description"] or "",
                    tags=r["tags"] or [],
                    rank=float(r["rank"]),
                    snippet=r["snippet"],
                    file_path=r["file_path"],
                )
                for r in rows
            ]

    def traverse(
        self,
        node_id: str,
        max_depth: int = 2,
        direction: str = "out",
        tenant_id: str | None = None,
    ) -> TraverseResult:
        with self.conn.cursor() as cur:
            if tenant_id is None:
                cur.execute(
                    "SELECT tenant_id FROM concepts WHERE id = %s ORDER BY CASE WHEN tenant_id = 'default' THEN 0 ELSE 1 END LIMIT 1;",
                    (node_id,),
                )
                t_row = cur.fetchone()
                resolved_tenant = t_row["tenant_id"] if t_row else "default"
            else:
                resolved_tenant = tenant_id

            if direction == "in":
                cte_sql = """
                    WITH RECURSIVE graph_path AS (
                        SELECT source_id, target_id, label, link_text, 1 as depth,
                               ARRAY[target_id, source_id] as path
                        FROM edges WHERE tenant_id = %s AND target_id = %s
                        UNION ALL
                        SELECT e.source_id, e.target_id, e.label, e.link_text, gp.depth + 1,
                               gp.path || e.source_id
                        FROM edges e
                        JOIN graph_path gp ON e.target_id = gp.source_id
                        WHERE e.tenant_id = %s AND gp.depth < %s
                          AND NOT (e.source_id = ANY(gp.path))
                    )
                    SELECT source_id, target_id, label, link_text, depth, path FROM graph_path;
                """
                cur.execute(cte_sql, (resolved_tenant, node_id, resolved_tenant, max_depth))
            elif direction == "both":
                cte_sql = """
                    WITH RECURSIVE graph_path AS (
                        SELECT
                            CASE WHEN source_id = %s THEN source_id ELSE target_id END as from_node,
                            CASE WHEN source_id = %s THEN target_id ELSE source_id END as to_node,
                            label,
                            link_text,
                            1 as depth,
                            ARRAY[%s, CASE WHEN source_id = %s THEN target_id ELSE source_id END] as path
                        FROM edges
                        WHERE tenant_id = %s AND (source_id = %s OR target_id = %s)

                        UNION ALL

                        SELECT
                            CASE WHEN e.source_id = gp.to_node THEN e.source_id ELSE e.target_id END,
                            CASE WHEN e.source_id = gp.to_node THEN e.target_id ELSE e.source_id END,
                            e.label,
                            e.link_text,
                            gp.depth + 1,
                            gp.path || CASE WHEN e.source_id = gp.to_node THEN e.target_id ELSE e.source_id END
                        FROM edges e
                        JOIN graph_path gp ON (e.source_id = gp.to_node OR e.target_id = gp.to_node)
                        WHERE e.tenant_id = %s AND gp.depth < %s
                          AND NOT (CASE WHEN e.source_id = gp.to_node THEN e.target_id ELSE e.source_id END = ANY(gp.path))
                    )
                    SELECT from_node as source_id, to_node as target_id, label, link_text, depth, path FROM graph_path;
                """
                cur.execute(cte_sql, (node_id, node_id, node_id, node_id, resolved_tenant, node_id, node_id, resolved_tenant, max_depth))
            else:
                cte_sql = """
                    WITH RECURSIVE graph_path AS (
                        SELECT source_id, target_id, label, link_text, 1 as depth,
                               ARRAY[source_id, target_id] as path
                        FROM edges WHERE tenant_id = %s AND source_id = %s
                        UNION ALL
                        SELECT e.source_id, e.target_id, e.label, e.link_text, gp.depth + 1,
                               gp.path || e.target_id
                        FROM edges e
                        JOIN graph_path gp ON e.source_id = gp.target_id
                        WHERE e.tenant_id = %s AND gp.depth < %s
                          AND NOT (e.target_id = ANY(gp.path))
                    )
                    SELECT source_id, target_id, label, link_text, depth, path FROM graph_path;
                """
                cur.execute(cte_sql, (resolved_tenant, node_id, resolved_tenant, max_depth))

            rows = cur.fetchall()

            collected_node_ids = {node_id}
            edges_list = []
            paths_list = []
            for r in rows:
                collected_node_ids.add(r["source_id"])
                collected_node_ids.add(r["target_id"])
                edges_list.append({
                    "source": r["source_id"],
                    "target": r["target_id"],
                    "label": r["label"],
                    "link_text": r["link_text"],
                    "depth": r["depth"],
                })
                paths_list.append(list(r["path"]))

            nodes_list = []
            if collected_node_ids:
                cur.execute(
                    "SELECT id, tenant_id, type, title, description, tags, status, file_path FROM concepts WHERE tenant_id = %s AND id = ANY(%s);",
                    (resolved_tenant, list(collected_node_ids)),
                )
                for nr in cur.fetchall():
                    nodes_list.append({
                        "id": nr["id"],
                        "tenant_id": nr["tenant_id"],
                        "type": nr["type"],
                        "title": nr["title"],
                        "description": nr["description"],
                        "tags": nr["tags"] or [],
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
        if source_id == target_id:
            return [source_id]

        with self.conn.cursor() as cur:
            if tenant_id is None:
                cur.execute(
                    "SELECT tenant_id FROM concepts WHERE id = %s ORDER BY CASE WHEN tenant_id = 'default' THEN 0 ELSE 1 END LIMIT 1;",
                    (source_id,),
                )
                t_row = cur.fetchone()
                resolved_tenant = t_row["tenant_id"] if t_row else "default"
            else:
                resolved_tenant = tenant_id

            sql = """
                WITH RECURSIVE path_finder AS (
                    SELECT source_id, target_id, 1 as depth, ARRAY[source_id, target_id] as path
                    FROM edges WHERE tenant_id = %s AND source_id = %s
                    UNION ALL
                    SELECT e.source_id, e.target_id, pf.depth + 1, pf.path || e.target_id
                    FROM edges e JOIN path_finder pf ON e.source_id = pf.target_id
                    WHERE e.tenant_id = %s AND pf.depth < %s AND NOT (e.target_id = ANY(pf.path))
                )
                SELECT path FROM path_finder WHERE target_id = %s ORDER BY depth ASC LIMIT 1;
            """
            cur.execute(sql, (resolved_tenant, source_id, resolved_tenant, max_depth, target_id))
            row = cur.fetchone()
            if row:
                return list(row["path"])
            return None

    def list_concepts(
        self,
        concept_type: str | None = None,
        tag: str | None = None,
        tenant_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self.conn.cursor() as cur:
            sql = "SELECT id, tenant_id, type, title, description, tags, status, file_path, commit_hash FROM concepts WHERE 1=1"
            params: list[Any] = []
            if tenant_id and tenant_id.lower() != "all":
                sql += " AND tenant_id = %s"
                params.append(tenant_id)
            if concept_type:
                sql += " AND type = %s"
                params.append(concept_type)
            if tag:
                sql += " AND tags ? %s"
                params.append(tag)
            sql += " ORDER BY title ASC LIMIT %s;"
            params.append(limit)
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def get_stats(self, tenant_id: str | None = None) -> GraphStats:
        with self.conn.cursor() as cur:
            concept_filter = " WHERE tenant_id = %s" if tenant_id else ""
            edge_filter = " WHERE tenant_id = %s" if tenant_id else ""
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
            cur.execute(f"""
                SELECT jsonb_array_elements_text(tags) as tag, COUNT(*) as cnt
                FROM concepts{concept_filter}
                GROUP BY tag
                ORDER BY cnt DESC
                LIMIT 10;
            """, params)
            top_tags = {r["tag"]: r["cnt"] for r in cur.fetchall()}

            all_tenants = self.list_tenants()

            return GraphStats(
                total_concepts=total_concepts,
                total_edges=total_edges,
                concept_types=concept_types,
                top_tags=top_tags,
                tenant_id=tenant_id,
                tenants=all_tenants,
            )

    def list_tenants(self) -> list[str]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT DISTINCT tenant_id FROM concepts ORDER BY tenant_id ASC;")
            tenants = [r["tenant_id"] for r in cur.fetchall() if r.get("tenant_id")]
            return tenants if tenants else ["default"]

    def clear(self) -> None:
        with self.conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE edges, concepts CASCADE;")

    def close(self) -> None:
        if self._conn and not self._conn.closed:
            self._conn.close()
