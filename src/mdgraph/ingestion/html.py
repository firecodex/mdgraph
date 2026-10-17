"""HTML and web page parser with structural table and header extraction."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict

from bs4 import BeautifulSoup, NavigableString, Tag

from mdgraph.ingestion.base import BaseParser, IngestionResult


class HTMLParser(BaseParser):
    """Parses HTML into normalized, clean Markdown preserving tables and hierarchy."""

    EXTENSIONS = {".html", ".htm", ".xhtml"}

    def can_parse(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.EXTENSIONS

    def parse(self, file_path: Path) -> IngestionResult:
        html_content = file_path.read_text(encoding="utf-8", errors="replace")
        return self.parse_string(html_content, source_path=str(file_path))

    def parse_string(self, html_content: str, source_path: str = "inline.html") -> IngestionResult:
        soup = BeautifulSoup(html_content, "html.parser")

        # Extract title
        title = "Untitled Document"
        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            title = title_tag.string.strip()
        else:
            h1 = soup.find("h1")
            if h1:
                title = h1.get_text(strip=True)

        # Extract meta description
        meta_desc = ""
        meta_tag = soup.find("meta", attrs={"name": "description"})
        if meta_tag and meta_tag.get("content"):
            meta_desc = str(meta_tag.get("content")).strip()

        # Remove non-content elements
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "svg"]):
            tag.decompose()

        # Body or whole document
        main_body = soup.find("main") or soup.find("article") or soup.body or soup

        markdown_lines = []
        for element in main_body.children:
            if isinstance(element, Tag):
                converted = self._convert_tag_to_markdown(element)
                if converted:
                    markdown_lines.append(converted)
            elif isinstance(element, NavigableString):
                text = str(element).strip()
                if text:
                    markdown_lines.append(text)

        md_text = "\n\n".join(line for line in markdown_lines if line.strip())

        return IngestionResult(
            source_path=source_path,
            title=title,
            markdown_content=md_text,
            metadata={"format": "html", "description": meta_desc},
        )

    def _convert_tag_to_markdown(self, tag: Tag) -> str:
        name = tag.name.lower()

        if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            level = int(name[1])
            return f"{'#' * level} {tag.get_text(strip=True)}"

        elif name == "p":
            return self._inline_markdown(tag)

        elif name in {"ul", "ol"}:
            items = []
            for idx, li in enumerate(tag.find_all("li", recursive=False), 1):
                li_text = self._inline_markdown(li)
                prefix = f"{idx}." if name == "ol" else "-"
                items.append(f"{prefix} {li_text}")
            return "\n".join(items)

        elif name == "table":
            return self._convert_table(tag)

        elif name == "pre":
            code = tag.find("code")
            code_text = code.get_text() if code else tag.get_text()
            return f"```\n{code_text.strip()}\n```"

        elif name == "blockquote":
            return f"> {tag.get_text(strip=True)}"

        else:
            # Container tags: div, section, etc.
            sub_results = []
            for child in tag.children:
                if isinstance(child, Tag):
                    sub = self._convert_tag_to_markdown(child)
                    if sub:
                        sub_results.append(sub)
                elif isinstance(child, NavigableString):
                    t = str(child).strip()
                    if t:
                        sub_results.append(t)
            return "\n\n".join(sub_results)

    def _convert_table(self, table: Tag) -> str:
        """Convert HTML table to Markdown table format."""
        rows = table.find_all("tr")
        if not rows:
            return ""

        table_data = []
        for r in rows:
            cols = [td.get_text(strip=True).replace("\n", " ") for td in r.find_all(["td", "th"])]
            if cols:
                table_data.append(cols)

        if not table_data:
            return ""

        num_cols = max(len(r) for r in table_data)
        # Pad shorter rows
        for r in table_data:
            while len(r) < num_cols:
                r.append("")

        lines = []
        # Header row
        header = table_data[0]
        lines.append("| " + " | ".join(header) + " |")
        lines.append("| " + " | ".join(["---"] * num_cols) + " |")

        # Body rows
        for row in table_data[1:]:
            lines.append("| " + " | ".join(row) + " |")

        return "\n".join(lines)

    def _inline_markdown(self, tag: Tag) -> str:
        """Process inline tags like <a>, <strong>, <em>, <code>."""
        text_parts = []
        for child in tag.children:
            if isinstance(child, NavigableString):
                text_parts.append(str(child))
            elif isinstance(child, Tag):
                cname = child.name.lower()
                child_text = child.get_text()
                if cname == "a":
                    href = child.get("href", "")
                    text_parts.append(f"[{child_text}]({href})")
                elif cname in {"strong", "b"}:
                    text_parts.append(f"**{child_text}**")
                elif cname in {"em", "i"}:
                    text_parts.append(f"*{child_text}*")
                elif cname == "code":
                    text_parts.append(f"`{child_text}`")
                else:
                    text_parts.append(child_text)
        return "".join(text_parts).strip()
