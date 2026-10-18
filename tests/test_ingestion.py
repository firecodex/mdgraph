"""Unit tests for universal ingestion pipeline."""

from mdgraph.ingestion.html import HTMLParser
from mdgraph.ingestion.ingestor import UniversalIngestor
from mdgraph.ingestion.markdown import MarkdownParser


def test_markdown_parser(temp_dir):
    p = temp_dir / "sample.md"
    p.write_text("# API Architecture Guide\n\nThis describes REST endpoints.", encoding="utf-8")

    parser = MarkdownParser()
    assert parser.can_parse(p)

    res = parser.parse(p)
    assert res.title == "API Architecture Guide"
    assert "REST endpoints" in res.markdown_content
    assert res.metadata["format"] == "markdown"


def test_html_parser_tables_and_headers(temp_dir):
    html = """
    <!DOCTYPE html>
    <html>
    <head><title>Engineering Guidelines</title></head>
    <body>
        <h1>Code Review Policy</h1>
        <p>All PRs require approval from <strong>Senior Engineers</strong>.</p>
        <table>
            <tr><th>Role</th><th>Approval Level</th></tr>
            <tr><td>Junior</td><td>Read-only</td></tr>
            <tr><td>Senior</td><td>Write/Merge</td></tr>
        </table>
        <ul>
            <li>Follow linting</li>
            <li>Add unit tests</li>
        </ul>
    </body>
    </html>
    """
    p = temp_dir / "review.html"
    p.write_text(html, encoding="utf-8")

    parser = HTMLParser()
    assert parser.can_parse(p)

    res = parser.parse(p)
    assert res.title == "Engineering Guidelines"
    assert "# Code Review Policy" in res.markdown_content
    assert "**Senior Engineers**" in res.markdown_content
    # Verify table converted to Markdown table
    assert "| Role | Approval Level |" in res.markdown_content
    assert "| --- | --- |" in res.markdown_content
    assert "| Junior | Read-only |" in res.markdown_content
    # Verify lists
    assert "- Follow linting" in res.markdown_content


def test_universal_ingestor(temp_dir):
    (temp_dir / "file1.md").write_text("# Doc 1\n\nContent 1", encoding="utf-8")
    (temp_dir / "file2.html").write_text("<h1>Doc 2</h1><p>Content 2</p>", encoding="utf-8")
    (temp_dir / "file3.txt").write_text("Plain text content", encoding="utf-8")

    ingestor = UniversalIngestor()
    results = ingestor.ingest_directory(temp_dir)
    assert len(results) == 3
    titles = {r.title for r in results}
    assert "Doc 1" in titles
    assert "Doc 2" in titles


def test_is_youtube_url():
    from mdgraph.ingestion.youtube import is_youtube_url

    assert is_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert is_youtube_url("https://youtu.be/dQw4w9WgXcQ")
    assert is_youtube_url("https://youtube.com/shorts/dQw4w9WgXcQ")
    assert is_youtube_url("https://www.youtube.com/embed/dQw4w9WgXcQ")
    assert not is_youtube_url("https://example.com/article")
    assert not is_youtube_url("https://github.com/firecodex/mdgraph")


def test_web_url_parser():
    from unittest.mock import MagicMock, patch

    from mdgraph.ingestion.web import WebURLParser

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = (
        "<html><head><title>Test Article</title></head><body><h1>Welcome</h1><p>Body content</p></body></html>"
    )

    with patch("httpx.Client.get", return_value=mock_response):
        parser = WebURLParser()
        result = parser.parse_url("https://example.com/docs")
        assert result.title == "Test Article"
        assert "# Welcome" in result.markdown_content
        assert "Body content" in result.markdown_content
        assert result.metadata["format"] == "web_page"
        assert result.metadata["url"] == "https://example.com/docs"


def test_youtube_parser():
    from unittest.mock import MagicMock, patch

    from mdgraph.ingestion.youtube import YouTubeParser

    oembed_resp = MagicMock()
    oembed_resp.status_code = 200
    oembed_resp.json.return_value = {
        "title": "Introduction to OKF",
        "author_name": "Knowledge Engineering",
        "author_url": "https://www.youtube.com/@ke",
    }

    mock_transcript = [
        {"text": "Welcome to open knowledge graphs.", "start": 0.0, "duration": 3.0},
        {"text": "We store concepts in Git.", "start": 12.5, "duration": 4.0},
    ]

    with patch("httpx.Client.get", return_value=oembed_resp), \
         patch("youtube_transcript_api.YouTubeTranscriptApi.fetch", return_value=mock_transcript):
        parser = YouTubeParser()
        result = parser.parse_url("https://www.youtube.com/watch?v=12345678901")
        assert result.title == "Introduction to OKF"
        assert result.metadata["format"] == "youtube_video"
        assert result.metadata["video_id"] == "12345678901"
        assert result.metadata["channel"] == "Knowledge Engineering"
        assert "**[00:00]** Welcome to open knowledge graphs." in result.markdown_content
        assert "**[00:12]** We store concepts in Git." in result.markdown_content


def test_universal_ingestor_polymorphic(temp_dir):
    from unittest.mock import MagicMock, patch

    ingestor = UniversalIngestor()

    # 1. Local file
    f = temp_dir / "single.md"
    f.write_text("# Single File\n\nContent", encoding="utf-8")
    res_file = ingestor.ingest(f)
    assert len(res_file) == 1
    assert res_file[0].title == "Single File"

    # 2. Local dir
    res_dir = ingestor.ingest(temp_dir)
    assert len(res_dir) >= 1

    # 3. Web URL
    mock_web = MagicMock()
    mock_web.status_code = 200
    mock_web.text = "<html><head><title>Web Page</title></head><body><h1>Web</h1></body></html>"
    with patch("httpx.Client.get", return_value=mock_web):
        res_url = ingestor.ingest("https://example.com/web")
        assert len(res_url) == 1
        assert res_url[0].title == "Web Page"
        assert res_url[0].metadata["format"] == "web_page"

