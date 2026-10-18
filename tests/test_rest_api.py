"""Integration tests for the standalone FastAPI REST service."""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from mdgraph.cli import main
from mdgraph.config import MdGraphConfig
from mdgraph.server.rest_api import create_rest_api


@pytest.fixture
def api_client(temp_dir, git_repo, sqlite_cache):
    """Fixture providing a FastAPI TestClient with initialized repo and cache."""
    cfg = MdGraphConfig(
        repo_path=str(git_repo.repo_path),
        cache_path=str(sqlite_cache.db_path),
        auto_commit=True,
    )
    app = create_rest_api(config=cfg, repo=git_repo, cache=sqlite_cache)
    with TestClient(app) as client:
        yield client


def test_health_endpoints(api_client):
    """Test health and root endpoints."""
    res_root = api_client.get("/")
    assert res_root.status_code == 200
    data = res_root.json()
    assert data["status"] == "ok"
    assert data["service"] == "mdgraph-rest-api"
    assert "version" in data
    assert "repo_path" in data

    res_v1 = api_client.get("/api/v1/health")
    assert res_v1.status_code == 200
    assert res_v1.json()["status"] == "ok"


def test_ingest_url(api_client):
    """Test URL ingestion endpoint with mocked HTTP response."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = (
        "<html><head><title>Remote Architecture</title></head>"
        "<body><h1>Microservices Guide</h1><p>Event-driven design.</p></body></html>"
    )

    with patch("httpx.Client.get", return_value=mock_resp):
        res = api_client.post("/api/v1/ingest/url", json={
            "url": "https://example.com/arch",
        })
        assert res.status_code == 200
        data = res.json()
        assert data["count"] == 1
        doc = data["documents"][0]
        assert doc["title"] == "Remote Architecture"
        assert "# Microservices Guide" in doc["markdown_content"]
        assert doc["format"] == "web_page"


def test_ingest_file_upload(api_client):
    """Test file upload multipart ingestion."""
    file_content = b"# Security Best Practices\n\nAlways rotate API tokens."
    files = {"file": ("security_policy.md", file_content, "text/markdown")}

    res = api_client.post("/api/v1/ingest/file", files=files)
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 1
    doc = data["documents"][0]
    assert doc["title"] == "Security Best Practices"
    assert "Always rotate API tokens." in doc["markdown_content"]


def test_ingest_raw_text(api_client, temp_dir):
    """Test direct raw text and HTML ingestion."""
    dest_dir = temp_dir / "normalized_test"

    res = api_client.post("/api/v1/ingest/text", json={
        "text": "<h1>Database Tuning</h1><p>Use indexes properly.</p>",
        "title": "Database Tuning Guide",
        "format": "html",
        "dest": str(dest_dir),
    })
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 1
    doc = data["documents"][0]
    assert "Database Tuning" in doc["title"]
    assert "# Database Tuning" in doc["markdown_content"]

    # Verify file was written to dest
    assert dest_dir.exists()
    saved_files = list(dest_dir.glob("*.md"))
    assert len(saved_files) == 1


def test_compile_text_offline(api_client):
    """Test compiling markdown content into OKF concepts offline."""
    content = (
        "# Remote Work Allowance\n\n"
        "Guidelines for equipment stipends handled by [IT Support](./it_support.md).\n\n"
        "## IT Support\n\n"
        "Help desk for ordering monitors.\n"
    )

    res = api_client.post("/api/v1/compile", json={
        "content": content,
        "source_name": "allowance.md",
        "offline": True,
        "save_to_repo": True,
        "sync_index": True,
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["saved_to_repo"] is True
    assert data["count"] >= 1
    assert data["commit_hash"] is not None

    # Test reading back compiled concepts via REST API
    res_list = api_client.get("/api/v1/concepts")
    assert res_list.status_code == 200
    concepts = res_list.json()
    assert len(concepts) >= 1


def test_compile_file(api_client, temp_dir):
    """Test compiling an on-disk markdown file into OKF concepts."""
    f = temp_dir / "onboarding.md"
    f.write_text("# Engineering Onboarding\n\nWelcome to engineering.", encoding="utf-8")

    res = api_client.post("/api/v1/compile/file", json={
        "file_path": str(f),
        "offline": True,
        "save_to_repo": True,
    })
    assert res.status_code == 200
    data = res.json()
    assert data["count"] >= 1
    assert data["saved_to_repo"] is True


def test_pipeline_one_shot(api_client):
    """Test end-to-end one-shot pipeline (ingest -> compile -> save -> sync)."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = (
        "<html><head><title>Cloud Infrastructure</title></head>"
        "<body><h1>Cloud Arch</h1><p>Managed via Kubernetes.</p></body></html>"
    )

    with patch("httpx.Client.get", return_value=mock_resp):
        res = api_client.post("/api/v1/pipeline", json={
            "source": "https://example.com/cloud",
            "offline": True,
            "save_to_repo": True,
            "sync_index": True,
        })
        assert res.status_code == 200
        data = res.json()
        assert data["ingested_count"] == 1
        assert data["concept_count"] >= 1
        assert data["saved_to_repo"] is True
        assert data["commit_hash"] is not None


def test_cli_api_help():
    """Verify `mdgraph api --help` displays correct flags."""
    runner = CliRunner()
    res = runner.invoke(main, ["api", "--help"])
    assert res.exit_code == 0
    assert "--host" in res.output
    assert "--port" in res.output
    assert "--repo" in res.output
    assert "--model" in res.output
