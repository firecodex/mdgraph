"""Abstract Query Cache base interface for MdGraph."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from mdgraph.models import GraphStats, OKFConcept, SearchResult, TraverseResult


class BaseQueryCache(ABC):
    """Abstract interface for relational query caches."""

    @abstractmethod
    def insert_or_update_concept(self, concept: OKFConcept) -> None:
        """Upsert concept into cache tables and FTS index."""
        pass

    @abstractmethod
    def delete_concept(self, node_id: str, tenant_id: str | None = None) -> None:
        """Remove concept, its edges, and FTS entries (scoped to tenant if specified)."""
        pass

    @abstractmethod
    def get_concept(self, node_id: str, tenant_id: str | None = None) -> dict[str, Any] | None:
        """Retrieve concept row and associated edges by ID (within tenant if specified, else across tenants)."""
        pass

    @abstractmethod
    def search(
        self,
        query: str,
        tags: list[str] | None = None,
        concept_type: str | None = None,
        tenant_id: str | None = None,
        limit: int = 10,
    ) -> list[SearchResult]:
        """Perform BM25 full-text keyword search (scoped to tenant if specified, else across all tenants)."""
        pass

    @abstractmethod
    def traverse(
        self,
        node_id: str,
        max_depth: int = 2,
        direction: str = "out",
        tenant_id: str | None = None,
    ) -> TraverseResult:
        """Execute recursive CTE multi-hop topological traversal (auto-resolving tenant if None)."""
        pass

    @abstractmethod
    def find_path(
        self,
        source_id: str,
        target_id: str,
        max_depth: int = 5,
        tenant_id: str | None = None,
    ) -> list[str] | None:
        """Find the shortest topological path between two concepts (auto-resolving tenant if None)."""
        pass

    @abstractmethod
    def list_concepts(
        self,
        concept_type: str | None = None,
        tag: str | None = None,
        tenant_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List concepts filtered by scalar attributes (within tenant if specified, else across all)."""
        pass

    @abstractmethod
    def get_stats(self, tenant_id: str | None = None) -> GraphStats:
        """Get summary statistics of the indexed graph (optionally scoped to tenant)."""
        pass

    @abstractmethod
    def list_tenants(self) -> list[str]:
        """Return list of distinct active tenant workspace identifiers."""
        pass

    @abstractmethod
    def clear(self) -> None:
        """Drop or truncate all cache tables."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Close database connections."""
        pass
