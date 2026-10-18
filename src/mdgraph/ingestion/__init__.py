"""Ingestion package for converting heterogeneous documents into structured Markdown."""

from mdgraph.ingestion.base import BaseParser, IngestionResult
from mdgraph.ingestion.html import HTMLParser
from mdgraph.ingestion.ingestor import UniversalIngestor
from mdgraph.ingestion.markdown import MarkdownParser
from mdgraph.ingestion.pdf import PDFParser
from mdgraph.ingestion.web import WebURLParser
from mdgraph.ingestion.youtube import YouTubeParser, is_youtube_url

__all__ = [
    "BaseParser",
    "IngestionResult",
    "MarkdownParser",
    "HTMLParser",
    "PDFParser",
    "WebURLParser",
    "YouTubeParser",
    "is_youtube_url",
    "UniversalIngestor",
]
