"""Web URL parser for ingesting public web pages and articles into Markdown."""

from __future__ import annotations

import httpx

from mdgraph.ingestion.base import IngestionResult
from mdgraph.ingestion.html import HTMLParser


class WebURLParser:
    """Fetches public web pages over HTTP/HTTPS and converts content into clean Markdown."""

    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(self, html_parser: HTMLParser | None = None):
        self.html_parser = html_parser or HTMLParser()

    def parse_url(self, url: str, timeout: float = 20.0) -> IngestionResult:
        """Fetch remote URL and convert HTML body into clean Markdown."""
        clean_url = url.strip()
        if not clean_url.startswith(("http://", "https://")):
            clean_url = "https://" + clean_url
        headers = {
            "User-Agent": self.DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        try:
            with httpx.Client(follow_redirects=True, timeout=timeout) as client:
                response = client.get(clean_url, headers=headers)
                response.raise_for_status()
                html_text = response.text
        except Exception as e:
            raise RuntimeError(f"Failed to fetch website URL '{clean_url}': {e}") from e

        # Use HTMLParser to convert HTML document to Markdown
        parsed = self.html_parser.parse_string(html_text, source_path=clean_url)
        parsed.metadata["format"] = "web_page"
        parsed.metadata["url"] = clean_url
        parsed.metadata["status_code"] = response.status_code
        return parsed
