"""Abstract base parser and ingestion data structures."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class IngestionResult(BaseModel):
    """Normalized document output from the ingestion pipeline."""
    source_path: str
    title: str
    markdown_content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class BaseParser(ABC):
    """Abstract interface for file format parsers."""

    @abstractmethod
    def can_parse(self, file_path: Path) -> bool:
        """Check if parser handles this file type."""
        pass

    @abstractmethod
    def parse(self, file_path: Path) -> IngestionResult:
        """Parse file into normalized Markdown and metadata."""
        pass
