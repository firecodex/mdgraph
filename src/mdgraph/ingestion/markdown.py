"""Markdown and plain text parser for universal ingestion."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from mdgraph.ingestion.base import BaseParser, IngestionResult


class MarkdownParser(BaseParser):
    """Parses and normalizes Markdown and plain text documents."""

    EXTENSIONS = {".md", ".markdown", ".mdown", ".txt", ".rst"}

    def can_parse(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.EXTENSIONS

    def parse(self, file_path: Path) -> IngestionResult:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        title = file_path.stem.replace("_", " ").replace("-", " ").title()

        # Look for first H1 header in markdown
        h1_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        if h1_match:
            title = h1_match.group(1).strip()

        metadata: dict[str, Any] = {
            "format": "markdown" if file_path.suffix.lower() != ".txt" else "text",
            "file_size": file_path.stat().st_size,
        }

        return IngestionResult(
            source_path=str(file_path),
            title=title,
            markdown_content=content,
            metadata=metadata,
        )
