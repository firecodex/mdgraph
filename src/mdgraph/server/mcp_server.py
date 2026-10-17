"""Native Model Context Protocol (MCP) server for MdGraph using FastMCP."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastmcp import FastMCP

from mdgraph.config import MdGraphConfig
from mdgraph.indexer.base import BaseQueryCache
from mdgraph.indexer.sqlite_cache import SQLiteQueryCache
from mdgraph.indexer.sync import IndexSyncWorker
from mdgraph.storage.git_repo import GitRepo


def create_mcp_server(
    config: Optional[MdGraphConfig] = None,
    repo: Optional[GitRepo] = None,
    cache: Optional[BaseQueryCache] = None,
) -> FastMCP:
    """Factory function that creates and registers tools on a FastMCP server."""
    cfg = config or MdGraphConfig()
    git_repo = repo or GitRepo(cfg.repo_path, author_name=cfg.git_author_name, author_email=cfg.git_author_email)
    query_cache = cache or SQLiteQueryCache(cfg.cache_path)
    sync_worker = IndexSyncWorker(git_repo, query_cache)

    # Perform initial sync to ensure query cache is up to date
    sync_worker.sync()

    mcp = FastMCP(
        name="MdGraph Knowledge Engine",
        instructions=(
            "MdGraph is a vectorless Open Knowledge Format (OKF) storage engine. "
            "You can traverse explicit knowledge graphs deterministically via traverse_graph(), "
            "search concepts with BM25 full-text keyword search via search_knowledge(), "
            "and read pristine Markdown files via read_concept_body()."
        ),
    )

    @mcp.tool()
    def get_concept(node_id: str) -> Dict[str, Any]:
        """Agent tool: Get metadata, tags, and direct cross-links for a specific concept node.
        
        Args:
            node_id: The unique concept identifier (slug, e.g. 'remote_work_policy').
        """
        data = query_cache.get_concept(node_id)
        if not data:
            return {"error": f"Concept '{node_id}' not found in knowledge graph."}
        return data

    @mcp.tool()
    def read_concept_body(node_id: str) -> str:
        """Agent tool: Reads the exact, unmodified OKF markdown body from the Git repository.
        
        Args:
            node_id: The unique concept identifier.
        """
        try:
            return git_repo.read_file(node_id)
        except FileNotFoundError:
            return f"Error: Concept '{node_id}' not found."

    @mcp.tool()
    def search_knowledge(
        query: str,
        tags: Optional[List[str]] = None,
        concept_type: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Agent tool: BM25 full-text keyword search across knowledge graph concepts.
        
        Args:
            query: Search query string (BM25 full-text match).
            tags: Optional list of tags to filter by.
            concept_type: Optional concept type filter (e.g. 'Policy', 'Architecture').
            limit: Maximum number of results to return (default 10).
        """
        results = query_cache.search(query=query, tags=tags, concept_type=concept_type, limit=limit)
        return [r.model_dump() for r in results]

    @mcp.tool()
    def traverse_graph(
        node_id: str,
        max_depth: int = 2,
        direction: str = "out",
    ) -> Dict[str, Any]:
        """Agent tool: Returns exact topological neighbors and multi-hop pathways of a concept via Recursive CTE.
        
        Args:
            node_id: The starting root concept identifier.
            max_depth: Max number of hops to traverse (default 2).
            direction: Traversal direction: 'out' (outgoing links), 'in' (backlinks), or 'both'.
        """
        res = query_cache.traverse(node_id=node_id, max_depth=max_depth, direction=direction)
        return res.model_dump()

    @mcp.tool()
    def find_path(
        source_id: str,
        target_id: str,
        max_depth: int = 5,
    ) -> Dict[str, Any]:
        """Agent tool: Finds the shortest topological path between two concepts.
        
        Args:
            source_id: Starting concept slug.
            target_id: Destination concept slug.
            max_depth: Maximum hops to search.
        """
        path = query_cache.find_path(source_id, target_id, max_depth)
        if path:
            return {"found": True, "source": source_id, "target": target_id, "path": path, "length": len(path) - 1}
        return {"found": False, "source": source_id, "target": target_id, "path": [], "message": "No path exists within max_depth."}

    @mcp.tool()
    def list_concepts(
        concept_type: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Agent tool: Lists concepts filtered by type or tag.
        
        Args:
            concept_type: Optional type filter (e.g., 'Concept', 'Policy').
            tag: Optional tag filter.
            limit: Maximum results to return.
        """
        return query_cache.list_concepts(concept_type=concept_type, tag=tag, limit=limit)

    @mcp.tool()
    def get_graph_stats() -> Dict[str, Any]:
        """Agent tool: Returns global statistics of the knowledge graph (concept counts, types, tags)."""
        stats = query_cache.get_stats()
        dump = stats.model_dump()
        dump["git_head"] = git_repo.get_head_commit()
        return dump

    @mcp.tool()
    def reindex(rebuild: bool = False) -> Dict[str, Any]:
        """Agent tool: Re-synchronize the Git truth repository into the relational query cache.
        
        Args:
            rebuild: If true, drops cache and rebuilds from scratch.
        """
        if rebuild:
            summary = sync_worker.rebuild()
        else:
            summary = sync_worker.sync()

        return {
            "status": "success",
            "indexed": summary.indexed,
            "updated": summary.updated,
            "deleted": summary.deleted,
            "skipped": summary.skipped,
            "errors": summary.errors,
            "duration_ms": summary.duration_ms,
        }

    # FastMCP Resources
    @mcp.resource("okf://concepts/{node_id}")
    def get_concept_resource(node_id: str) -> str:
        """Resource: Read raw Markdown content of a concept."""
        return git_repo.read_file(node_id)

    @mcp.resource("okf://graph/stats")
    def get_stats_resource() -> str:
        """Resource: Summary statistics of the graph in JSON."""
        stats = query_cache.get_stats()
        return stats.model_dump_json(indent=2)

    return mcp
