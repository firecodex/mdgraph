"""Abstract Query Cache base interface for MdGraph."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from mdgraph.models import GraphStats, OKFConcept, SearchResult, TraverseResult


class BaseQueryCache(ABC):
    """Abstract interface for relational query caches."""

    @abstractmethod
    def insert_or_update_concept(self, concept: OKFConcept) -> None:
        """Upsert concept into cache tables and FTS index."""
        pass

    @abstractmethod
    def delete_concept(self, node_id: str) -> None:
        """Remove concept, its edges, and FTS entries."""
        pass

    @abstractmethod
    def get_concept(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve concept row and associated edges by ID."""
        pass

    @abstractmethod
    def search(
        self,
        query: str,
        tags: Optional[List[str]] = None,
        concept_type: Optional[str] = None,
        limit: int = 10,
    ) -> List[SearchResult]:
        """Perform BM25 full-text keyword search with optional scalar filters."""
        pass

    @abstractmethod
    def traverse(
        self,
        node_id: str,
        max_depth: int = 2,
        direction: str = "out",
    ) -> TraverseResult:
        """Execute recursive CTE multi-hop topological traversal."""
        pass

    @abstractmethod
    def find_path(
        self,
        source_id: str,
        target_id: str,
        max_depth: int = 5,
    ) -> Optional[List[str]]:
        """Find the shortest topological path between two concepts."""
        pass

    @abstractmethod
    def list_concepts(
        self,
        concept_type: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List concepts filtered by scalar attributes."""
        pass

    @abstractmethod
    def get_stats(self) -> GraphStats:
        """Get summary statistics of the indexed graph."""
        pass

    @abstractmethod
    def clear(self) -> None:
        """Drop or truncate all cache tables."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Close database connections."""
        pass
