"""PDF Document parser with structure and table awareness."""

from __future__ import annotations

from pathlib import Path

from mdgraph.ingestion.base import BaseParser, IngestionResult


class PDFParser(BaseParser):
    """Parses PDF documents into structured Markdown."""

    EXTENSIONS = {".pdf"}

    def can_parse(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.EXTENSIONS

    def parse(self, file_path: Path) -> IngestionResult:
        # Check if docling is installed and available
        try:
            from docling.document_converter import DocumentConverter
            converter = DocumentConverter()
            result = converter.convert(str(file_path))
            md_content = result.document.export_to_markdown()
            title = file_path.stem.replace("_", " ").title()
            return IngestionResult(
                source_path=str(file_path),
                title=title,
                markdown_content=md_content,
                metadata={"format": "pdf", "engine": "docling"},
            )
        except (ImportError, Exception):
            pass

        # Native fallback using pypdf
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(file_path))
            pages_text = []

            title = file_path.stem.replace("_", " ").title()
            if reader.metadata and reader.metadata.title:
                title = reader.metadata.title

            for i, page in enumerate(reader.pages):
                page_text = page.extract_text() or ""
                if page_text.strip():
                    pages_text.append(f"## Page {i + 1}\n\n{page_text.strip()}")

            full_md = f"# {title}\n\n" + "\n\n".join(pages_text)

            return IngestionResult(
                source_path=str(file_path),
                title=title,
                markdown_content=full_md,
                metadata={"format": "pdf", "engine": "pypdf", "num_pages": len(reader.pages)},
            )
        except Exception as e:
            raise RuntimeError(f"Failed to parse PDF {file_path}: {e}") from e
