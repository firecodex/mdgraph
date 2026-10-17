"""Abstract base interface for knowledge graph compilers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from mdgraph.models import OKFConcept


class BaseCompiler(ABC):
    """Abstract interface for compiling text into OKF concepts."""

    @abstractmethod
    def compile(self, text: str, source_name: Optional[str] = None) -> List[OKFConcept]:
        """Compile source document into an interconnected list of OKF concepts."""
        pass
