"""YouTube video ingestor: Extracts video metadata and synchronized captions/transcript into Markdown."""

from __future__ import annotations

import re
from typing import Any

import httpx

from mdgraph.ingestion.base import IngestionResult

# Regex matching youtube.com/watch?v=, youtu.be/, youtube.com/shorts/, youtube.com/embed/
YOUTUBE_URL_PATTERN = re.compile(
    r"(?:https?:\/\/)?(?:www\.|m\.)?(?:youtube\.com\/(?:watch\?.*?v=|shorts\/|embed\/|v\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})"
)


def is_youtube_url(url: str) -> bool:
    """Return True if URL is a recognized YouTube video or shorts link."""
    return bool(YOUTUBE_URL_PATTERN.search(url.strip()))


def extract_youtube_video_id(url: str) -> str | None:
    """Extract the 11-character YouTube video ID from any standard URL."""
    match = YOUTUBE_URL_PATTERN.search(url.strip())
    return match.group(1) if match else None


def format_seconds(seconds: float) -> str:
    """Convert float seconds into [HH:MM:SS] or [MM:SS] timestamp."""
    total_seconds = int(seconds)
    m, s = divmod(total_seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


class YouTubeParser:
    """Fetches YouTube video metadata and captions/transcript to produce structured Markdown."""

    OEMBED_API = "https://www.youtube.com/oembed"

    def parse_url(self, url: str, timeout: float = 20.0) -> IngestionResult:
        """Parse YouTube URL into a Markdown transcript document."""
        clean_url = url.strip()
        if not clean_url.startswith(("http://", "https://")):
            clean_url = "https://" + clean_url
        video_id = extract_youtube_video_id(clean_url)
        if not video_id:
            raise ValueError(f"Could not extract a valid YouTube video ID from: {clean_url}")

        # 1. Fetch metadata via official public oEmbed endpoint
        title = f"YouTube Video {video_id}"
        author_name = "Unknown Channel"
        author_url = ""
        try:
            with httpx.Client(follow_redirects=True, timeout=timeout) as client:
                res = client.get(self.OEMBED_API, params={"url": clean_url, "format": "json"})
                if res.status_code == 200:
                    meta = res.json()
                    title = meta.get("title", title)
                    author_name = meta.get("author_name", author_name)
                    author_url = meta.get("author_url", "")
        except Exception:
            pass

        # 2. Extract transcript using youtube-transcript-api
        transcript_lines: list[str] = []
        has_transcript = False
        try:
            from youtube_transcript_api import YouTubeTranscriptApi

            try:
                # youtube-transcript-api >= 1.0 (instance method)
                raw_snippets = YouTubeTranscriptApi().fetch(video_id)
            except (AttributeError, TypeError):
                # Legacy classmethod fallback
                raw_snippets = YouTubeTranscriptApi.get_transcript(video_id)

            for snippet in raw_snippets:
                # Handle both object attributes and dictionary keys
                if hasattr(snippet, "text") and hasattr(snippet, "start"):
                    text = str(snippet.text).strip()
                    start = float(snippet.start)
                elif isinstance(snippet, dict):
                    text = str(snippet.get("text", "")).strip()
                    start = float(snippet.get("start", 0.0))
                else:
                    continue

                if text:
                    timestamp_str = format_seconds(start)
                    transcript_lines.append(f"**[{timestamp_str}]** {text}")

            has_transcript = len(transcript_lines) > 0
        except Exception as e:
            transcript_lines.append(f"*(No closed captions or transcript available for this video: {e})*")

        # 3. Assemble structured Markdown
        md_parts = [
            f"# {title}\n",
            "- **Platform:** YouTube",
            f"- **Channel:** [{author_name}]({author_url})" if author_url else f"- **Channel:** {author_name}",
            f"- **Video URL:** {clean_url}",
            f"- **Video ID:** `{video_id}`\n",
            "## Video Transcript\n",
        ]

        if has_transcript:
            md_parts.append("\n\n".join(transcript_lines))
        else:
            md_parts.append(transcript_lines[0])

        markdown_body = "\n".join(md_parts) + "\n"

        metadata: dict[str, Any] = {
            "format": "youtube_video",
            "video_id": video_id,
            "channel": author_name,
            "url": clean_url,
            "has_transcript": has_transcript,
        }

        return IngestionResult(
            source_path=clean_url,
            title=title,
            markdown_content=markdown_body,
            metadata=metadata,
        )
