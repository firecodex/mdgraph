"""PostgreSQL JSONB and Recursive CTE Vectorless Query Cache for MdGraph."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

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
        except ImportError:
            raise ImportError(
                "PostgreSQL support requires 'psycopg'. Install with: pip install mdgraph[postgres]"
            )

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
                    id TEXT PRIMARY KEY,
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
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS edges (
                    id BIGSERIAL PRIMARY KEY,
                    source_id TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
                    target_id TEXT NOT NULL,
                    label TEXT DEFAULT 'references',
                    link_text TEXT,
                    raw_target TEXT
                );
            """)

            cur.execute("CREATE INDEX IF NOT EXISTS idx_pg_edges_source ON edges(source_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_pg_edges_target ON edges(target_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_pg_concepts_tags ON concepts USING GIN (tags);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_pg_concepts_tsv ON concepts USING GIN (tsv_body);")

    def insert_or_update_concept(self, concept: OKFConcept) -> None:
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO concepts (id, type, title, description, tags, status, metadata, body, file_path, commit_hash, updated_at)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s, %s, %s, NOW())
                ON CONFLICT (id) DO UPDATE SET
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
                concept.id,
                concept.type,
                concept.title,
                concept.description,
                json.dumps(concept.tags),
                concept.status,
                json.dumps(concept.metadata),
                concept.body,
                concept.file_path or f"concepts/{concept.id}.md",
                concept.commit_hash,
            ))

            cur.execute("DELETE FROM edges WHERE source_id = %s;", (concept.id,))
            for edge in concept.edges:
                cur.execute("""
                    INSERT INTO edges (source_id, target_id, label, link_text, raw_target)
                    VALUES (%s, %s, %s, %s, %s);
                """, (
                    edge.source_id,
                    edge.target_id,
                    edge.label or "references",
                    edge.link_text or "",
                    edge.raw_target or "",
                ))

    def delete_concept(self, node_id: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM concepts WHERE id = %s;", (node_id,))
            cur.execute("DELETE FROM edges WHERE target_id = %s;", (node_id,))

    def get_concept(self, node_id: str) -> Optional[Dict[str, Any]]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM concepts WHERE id = %s;", (node_id,))
            row = cur.fetchone()
            if not row:
                return None
            data = dict(row)
            cur.execute("SELECT target_id, label, link_text FROM edges WHERE source_id = %s;", (node_id,))
            data["outgoing_edges"] = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT source_id, label, link_text FROM edges WHERE target_id = %s;", (node_id,))
            data["incoming_edges"] = [dict(r) for r in cur.fetchall()]
            return data

    def search(
        self,
        query: str,
        tags: Optional[List[str]] = None,
        concept_type: Optional[str] = None,
        limit: int = 10,
    ) -> List[SearchResult]:
        with self.conn.cursor() as cur:
            sql = """
                SELECT id, type, title, description, tags, file_path,
                       ts_rank(tsv_body, plainto_tsquery('english', %s)) as rank,
                       ts_headline('english', body, plainto_tsquery('english', %s), 'StartSel=[MATCH], StopSel=[/MATCH], MaxWords=20') as snippet
                FROM concepts
                WHERE tsv_body @@ plainto_tsquery('english', %s)
            """
            params: List[Any] = [query, query, query]
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
    ) -> TraverseResult:
        with self.conn.cursor() as cur:
            cte_sql = """
                WITH RECURSIVE graph_path AS (
                    SELECT source_id, target_id, label, link_text, 1 as depth,
                           ARRAY[source_id, target_id] as path
                    FROM edges WHERE source_id = %s
                    UNION ALL
                    SELECT e.source_id, e.target_id, e.label, e.link_text, gp.depth + 1,
                           gp.path || e.target_id
                    FROM edges e
                    JOIN graph_path gp ON e.source_id = gp.target_id
                    WHERE gp.depth < %s
                      AND NOT (e.target_id = ANY(gp.path))
                )
                SELECT source_id, target_id, label, link_text, depth, path FROM graph_path;
            """
            cur.execute(cte_sql, (node_id, max_depth))
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
                cur.execute("SELECT id, type, title, description, tags, status, file_path FROM concepts WHERE id = ANY(%s);", (list(collected_node_ids),))
                for nr in cur.fetchall():
                    nodes_list.append({
                        "id": nr["id"],
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
        with self.conn.cursor() as cur:
            sql = """
                WITH RECURSIVE path_finder AS (
                    SELECT source_id, target_id, 1 as depth, ARRAY[source_id, target_id] as path
                    FROM edges WHERE source_id = %s
                    UNION ALL
                    SELECT e.source_id, e.target_id, pf.depth + 1, pf.path || e.target_id
                    FROM edges e JOIN path_finder pf ON e.source_id = pf.target_id
                    WHERE pf.depth < %s AND NOT (e.target_id = ANY(pf.path))
                )
                SELECT path FROM path_finder WHERE target_id = %s ORDER BY depth ASC LIMIT 1;
            """
            cur.execute(sql, (source_id, max_depth, target_id))
            row = cur.fetchone()
            if row:
                return list(row["path"])
            return None

    def list_concepts(
        self,
        concept_type: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        with self.conn.cursor() as cur:
            sql = "SELECT id, type, title, description, tags, status, file_path, commit_hash FROM concepts WHERE 1=1"
            params: List[Any] = []
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

    def get_stats(self) -> GraphStats:
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM concepts;")
            total_concepts = cur.fetchone()["cnt"]
            cur.execute("SELECT COUNT(*) as cnt FROM edges;")
            total_edges = cur.fetchone()["cnt"]
            cur.execute("SELECT type, COUNT(*) as cnt FROM concepts GROUP BY type ORDER BY cnt DESC;")
            concept_types = {r["type"]: r["cnt"] for r in cur.fetchall()}
            cur.execute("""
                SELECT jsonb_array_elements_text(tags) as tag, COUNT(*) as cnt
                FROM concepts
                GROUP BY tag
                ORDER BY cnt DESC
                LIMIT 10;
            """)
            top_tags = {r["tag"]: r["cnt"] for r in cur.fetchall()}

            return GraphStats(
                total_concepts=total_concepts,
                total_edges=total_edges,
                concept_types=concept_types,
                top_tags=top_tags,
            )

    def clear(self) -> None:
        with self.conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE edges, concepts CASCADE;")

    def close(self) -> None:
        if self._conn and not self._conn.closed:
            self._conn.close()
