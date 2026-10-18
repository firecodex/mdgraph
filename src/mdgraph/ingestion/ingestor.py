"""Universal Ingestor: Central coordinator for parsing heterogeneous formats into Markdown."""

from __future__ import annotations

import os
from pathlib import Path

from mdgraph.ingestion.base import BaseParser, IngestionResult
from mdgraph.ingestion.html import HTMLParser
from mdgraph.ingestion.markdown import MarkdownParser
from mdgraph.ingestion.pdf import PDFParser
from mdgraph.ingestion.web import WebURLParser
from mdgraph.ingestion.youtube import YouTubeParser, is_youtube_url


class UniversalIngestor:
    """Dispatches files, directories, web URLs, and YouTube videos to appropriate parsers to produce standardized Markdown."""

    def __init__(
        self,
        extra_parsers: list[BaseParser] | None = None,
        web_parser: WebURLParser | None = None,
        youtube_parser: YouTubeParser | None = None,
    ):
        self.parsers: list[BaseParser] = [
            MarkdownParser(),
            HTMLParser(),
            PDFParser(),
        ]
        if extra_parsers:
            self.parsers = extra_parsers + self.parsers

        self.web_parser = web_parser or WebURLParser()
        self.youtube_parser = youtube_parser or YouTubeParser()

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
            raise ValueError(f"No suitable parser found for {p} ({e})") from e

    def ingest_directory(self, dir_path: str | Path) -> list[IngestionResult]:
        """Recursively scan directory and parse all supported files."""
        d = Path(dir_path).resolve()
        if not d.is_dir():
            raise NotADirectoryError(f"Directory not found: {d}")

        results: list[IngestionResult] = []
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

    def ingest_url(self, url: str) -> IngestionResult:
        """Fetch and parse a website URL or YouTube video URL into clean Markdown."""
        clean_url = url.strip()
        if is_youtube_url(clean_url):
            return self.youtube_parser.parse_url(clean_url)
        return self.web_parser.parse_url(clean_url)

    def ingest(self, source: str | Path) -> list[IngestionResult]:
        """Polymorphic ingest: accepts directory, file, website URL, or YouTube URL."""
        source_str = str(source).strip()
        if source_str.startswith(("http://", "https://", "www.")) or is_youtube_url(source_str):
            return [self.ingest_url(source_str)]

        p = Path(source).resolve()
        if p.is_dir():
            return self.ingest_directory(p)
        if p.is_file():
            return [self.ingest_file(p)]
        raise FileNotFoundError(f"Source not found (not a file, directory, or valid URL): {source}")
