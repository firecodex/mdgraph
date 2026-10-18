"""Native Model Context Protocol (MCP) server for MdGraph using FastMCP."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from mdgraph.config import MdGraphConfig
from mdgraph.indexer.base import BaseQueryCache
from mdgraph.indexer.sqlite_cache import SQLiteQueryCache
from mdgraph.indexer.sync import IndexSyncWorker
from mdgraph.storage.git_repo import GitRepo


def create_mcp_server(
    config: MdGraphConfig | None = None,
    repo: GitRepo | None = None,
    cache: BaseQueryCache | None = None,
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
    def get_concept(node_id: str, tenant_id: str | None = None) -> dict[str, Any]:
        """Agent tool: Get metadata, tags, and direct cross-links for a specific concept node.

        Args:
            node_id: The unique concept identifier (slug, e.g. 'remote_work_policy').
            tenant_id: Optional workspace tenant identifier (searches all if None).
        """
        data = query_cache.get_concept(node_id, tenant_id=tenant_id)
        if not data:
            scope_msg = f" in tenant '{tenant_id}'" if tenant_id else ""
            return {"error": f"Concept '{node_id}' not found{scope_msg}."}
        return data

    @mcp.tool()
    def read_concept_body(node_id: str, tenant_id: str | None = None) -> str:
        """Agent tool: Reads the exact, unmodified OKF markdown body from the Git repository.

        Args:
            node_id: The unique concept identifier.
            tenant_id: Optional workspace tenant identifier (searches all if None).
        """
        try:
            return git_repo.read_file(node_id, tenant_id=tenant_id)
        except FileNotFoundError:
            scope_msg = f" in tenant '{tenant_id}'" if tenant_id else ""
            return f"Error: Concept '{node_id}' not found{scope_msg}."

    @mcp.tool()
    def search_knowledge(
        query: str,
        tags: list[str] | None = None,
        concept_type: str | None = None,
        tenant_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Agent tool: BM25 full-text keyword search across knowledge graph concepts.

        Args:
            query: Search query string (BM25 full-text match).
            tags: Optional list of tags to filter by.
            concept_type: Optional concept type filter (e.g. 'Policy', 'Architecture').
            tenant_id: Optional workspace tenant identifier (searches across all if None).
            limit: Maximum number of results to return (default 10).
        """
        results = query_cache.search(
            query=query,
            tags=tags,
            concept_type=concept_type,
            tenant_id=tenant_id,
            limit=limit,
        )
        return [r.model_dump() for r in results]

    @mcp.tool()
    def traverse_graph(
        node_id: str,
        max_depth: int = 2,
        direction: str = "out",
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """Agent tool: Returns exact topological neighbors and multi-hop pathways of a concept via Recursive CTE.

        Args:
            node_id: The starting root concept identifier.
            max_depth: Max number of hops to traverse (default 2).
            direction: Traversal direction: 'out' (outgoing links), 'in' (backlinks), or 'both'.
            tenant_id: Optional workspace tenant identifier (auto-detected if None).
        """
        res = query_cache.traverse(
            node_id=node_id,
            max_depth=max_depth,
            direction=direction,
            tenant_id=tenant_id,
        )
        return res.model_dump()

    @mcp.tool()
    def find_path(
        source_id: str,
        target_id: str,
        max_depth: int = 5,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """Agent tool: Finds the shortest topological path between two concepts within a tenant workspace.

        Args:
            source_id: Starting concept slug.
            target_id: Destination concept slug.
            max_depth: Maximum hops to search.
            tenant_id: Optional workspace tenant identifier (auto-detected if None).
        """
        path = query_cache.find_path(source_id, target_id, max_depth, tenant_id=tenant_id)
        if path:
            return {
                "found": True,
                "source": source_id,
                "target": target_id,
                "tenant_id": tenant_id or "auto",
                "path": path,
                "length": len(path) - 1,
            }
        return {
            "found": False,
            "source": source_id,
            "target": target_id,
            "tenant_id": tenant_id or "auto",
            "path": [],
            "message": f"No path exists within max_depth {max_depth}.",
        }

    @mcp.tool()
    def list_concepts(
        concept_type: str | None = None,
        tag: str | None = None,
        tenant_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Agent tool: Lists concepts filtered by type, tag, or tenant.

        Args:
            concept_type: Optional type filter (e.g., 'Concept', 'Policy').
            tag: Optional tag filter.
            tenant_id: Optional workspace tenant identifier (lists all if None).
            limit: Maximum results to return.
        """
        return query_cache.list_concepts(
            concept_type=concept_type,
            tag=tag,
            tenant_id=tenant_id,
            limit=limit,
        )

    @mcp.tool()
    def list_tenants() -> list[str]:
        """Agent tool: Lists all distinct active tenant workspaces available in the repository."""
        return query_cache.list_tenants()

    @mcp.tool()
    def get_graph_stats(tenant_id: str | None = None) -> dict[str, Any]:
        """Agent tool: Returns statistics of the knowledge graph (concept counts, types, tags), optionally scoped to tenant.

        Args:
            tenant_id: Optional tenant identifier to scope statistics.
        """
        stats = query_cache.get_stats(tenant_id=tenant_id)
        dump = stats.model_dump()
        dump["git_head"] = git_repo.get_head_commit()
        return dump

    @mcp.tool()
    def reindex(tenant_id: str | None = None, rebuild: bool = False) -> dict[str, Any]:
        """Agent tool: Re-synchronize the Git truth repository into the relational query cache.

        Args:
            tenant_id: Optional tenant workspace to synchronize (or all if None).
            rebuild: If true, drops cache and rebuilds from scratch.
        """
        if rebuild:
            summary = sync_worker.rebuild(tenant_id=tenant_id)
        else:
            summary = sync_worker.sync(tenant_id=tenant_id)

        return {
            "status": "success",
            "tenant_id": tenant_id or "all",
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

    @mcp.resource("okf://tenants/{tenant_id}/concepts/{node_id}")
    def get_tenant_concept_resource(tenant_id: str, node_id: str) -> str:
        """Resource: Read raw Markdown content of a concept belonging to a specific tenant."""
        return git_repo.read_file(node_id, tenant_id=tenant_id)

    @mcp.resource("okf://tenants")
    def get_tenants_resource() -> str:
        """Resource: List all active workspace tenants."""
        import json
        return json.dumps(query_cache.list_tenants(), indent=2)

    @mcp.resource("okf://graph/stats")
    def get_stats_resource() -> str:
        """Resource: Summary statistics of the graph in JSON."""
        stats = query_cache.get_stats()
        return stats.model_dump_json(indent=2)

    return mcp
