"""Universal Ingestor: Central coordinator for parsing heterogeneous formats into Markdown."""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from mdgraph.ingestion.base import BaseParser, IngestionResult
from mdgraph.ingestion.html import HTMLParser
from mdgraph.ingestion.markdown import MarkdownParser
from mdgraph.ingestion.pdf import PDFParser


class UniversalIngestor:
    """Dispatches files to appropriate parsers to produce standardized Markdown."""

    def __init__(self, extra_parsers: Optional[List[BaseParser]] = None):
        self.parsers: List[BaseParser] = [
            MarkdownParser(),
            HTMLParser(),
            PDFParser(),
        ]
        if extra_parsers:
            self.parsers = extra_parsers + self.parsers

    def register_parser(self, parser: BaseParser) -> None:
        """Register a custom parser at the front of the list."""
        self.parsers.insert(0, parser)

    def ingest_file(self, file_path: str | Path) -> IngestionResult:
        """Parse a single file using the matching parser."""
        p = Path(file_path).resolve()
        if not p.is_file():
            raise FileNotFoundError(f"Input file not found: {p}")

        for parser in self.parsers:
            if parser.can_parse(p):
                return parser.parse(p)

        # Fallback to plain text reading
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            return IngestionResult(
                source_path=str(p),
                title=p.stem.replace("_", " ").title(),
                markdown_content=content,
                metadata={"format": "unknown_raw_text"},
            )
        except Exception as e:
            raise ValueError(f"No suitable parser found for {p} ({e})")

    def ingest_directory(self, dir_path: str | Path) -> List[IngestionResult]:
        """Recursively scan directory and parse all supported files."""
        d = Path(dir_path).resolve()
        if not d.is_dir():
            raise NotADirectoryError(f"Directory not found: {d}")

        results: List[IngestionResult] = []
        for root, _, files in os.walk(d):
            for f in files:
                if f.startswith("."):
                    continue
                fp = Path(root) / f
                try:
                    res = self.ingest_file(fp)
                    results.append(res)
                except Exception:
                    pass
        return results
