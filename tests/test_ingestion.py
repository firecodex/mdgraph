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
