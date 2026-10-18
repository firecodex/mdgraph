"""Integration tests for the mdgraph CLI."""

from click.testing import CliRunner

from mdgraph.cli import main


def test_cli_version():
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "MdGraph" in result.output


def test_cli_init_and_stats(temp_dir):
    runner = CliRunner()
    repo_path = str(temp_dir / "test_repo")

    # mdgraph init
    init_res = runner.invoke(main, ["init", repo_path])
    assert init_res.exit_code == 0
    assert "initialized at" in init_res.output

    # mdgraph stats
    stats_res = runner.invoke(main, ["stats", "--config", "none"])
    assert stats_res.exit_code == 0


def test_cli_ingest_compile_index_query_traverse(temp_dir):
    runner = CliRunner()

    # 1. Create a raw markdown document
    raw_doc = temp_dir / "raw_handbook.md"
    raw_doc.write_text(
        "# Remote Work Policy\n\n"
        "Guidelines for remote staff. Equipment is ordered via the Vendor Portal.\n\n"
        "## Vendor Portal\n\n"
        "Portal for ordering approved hardware and monitors.\n",
        encoding="utf-8"
    )

    repo_dir = temp_dir / "knowledge_repo"
    cache_db = temp_dir / "cache.db"

    # mdgraph init
    init_res = runner.invoke(main, ["init", str(repo_dir)])
    assert init_res.exit_code == 0

    # Ingest
    ingest_dir = temp_dir / "normalized"
    ingest_res = runner.invoke(main, ["ingest", str(raw_doc), "--dest", str(ingest_dir)])
    assert ingest_res.exit_code == 0

    normalized_files = list(ingest_dir.glob("*.md"))
    assert len(normalized_files) > 0
    normalized_file = normalized_files[0]

    # Compile with offline mode
    compile_res = runner.invoke(main, [
        "compile",
        str(normalized_file),
        "--offline"
    ], env={"MDGRAPH_REPO_PATH": str(repo_dir), "MDGRAPH_CACHE_PATH": str(cache_db)})
    assert compile_res.exit_code == 0

    # Index
    index_res = runner.invoke(main, [
        "index",
        "--rebuild"
    ], env={"MDGRAPH_REPO_PATH": str(repo_dir), "MDGRAPH_CACHE_PATH": str(cache_db)})
    assert index_res.exit_code == 0

    # Query
    query_res = runner.invoke(main, [
        "query",
        "equipment",
        "--traverse"
    ], env={"MDGRAPH_REPO_PATH": str(repo_dir), "MDGRAPH_CACHE_PATH": str(cache_db)})
    assert query_res.exit_code == 0
    assert "Search Results" in query_res.output

    # Traverse
    traverse_res = runner.invoke(main, [
        "traverse",
        "remote_work_policy",
        "--depth",
        "2"
    ], env={"MDGRAPH_REPO_PATH": str(repo_dir), "MDGRAPH_CACHE_PATH": str(cache_db)})
    assert traverse_res.exit_code == 0
    assert "Topological traversal" in traverse_res.output

    # Show
    show_res = runner.invoke(main, [
        "show",
        "remote_work_policy"
    ], env={"MDGRAPH_REPO_PATH": str(repo_dir), "MDGRAPH_CACHE_PATH": str(cache_db)})
    assert show_res.exit_code == 0
    assert "Remote Work Policy" in show_res.output


def test_cli_ingest_url(temp_dir):
    from unittest.mock import MagicMock, patch

    runner = CliRunner()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><head><title>Remote Architecture</title></head><body><h1>API Design</h1></body></html>"

    dest_dir = temp_dir / "url_output"
    with patch("httpx.Client.get", return_value=mock_resp):
        res = runner.invoke(main, ["ingest", "https://example.com/arch", "--dest", str(dest_dir)])
        assert res.exit_code == 0
        assert "Ingested Documents" in res.output
        assert "Remote Architecture" in res.output
        written_files = list(dest_dir.glob("*.md"))
        assert len(written_files) == 1
        assert "remote_architecture.md" in written_files[0].name


def test_cli_ingest_nonexistent_path():
    runner = CliRunner()
    res = runner.invoke(main, ["ingest", "/non/existent/path/that/cannot/exist/xyz_12345"])
    assert res.exit_code != 0
    assert "does not exist" in res.output

