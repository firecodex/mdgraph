"""Pytest test configuration and fixtures for MdGraph."""

import shutil
import tempfile
from pathlib import Path

import pytest

from mdgraph.indexer.sqlite_cache import SQLiteQueryCache
from mdgraph.models import OKFConcept
from mdgraph.storage.git_repo import GitRepo


@pytest.fixture
def temp_dir():
    """Create a temporary directory cleaned up after test run."""
    d = tempfile.mkdtemp(prefix="mdgraph_test_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def git_repo(temp_dir):
    """Create an initialized GitRepo in a temporary directory."""
    repo_path = temp_dir / "knowledge"
    repo = GitRepo(repo_path, auto_init=True)
    return repo


@pytest.fixture
def sqlite_cache(temp_dir):
    """Create an in-memory or file-based SQLiteQueryCache."""
    cache_path = temp_dir / "cache.db"
    cache = SQLiteQueryCache(cache_path)
    yield cache
    cache.close()


@pytest.fixture
def sample_okf_concept():
    """Create a sample OKF concept object."""
    body = (
        "# Remote Work Hardware Allowance\n\n"
        "Employees receive a yearly stipend managed by the [IT Department](./it_department.md).\n\n"
        "## Approved Equipment\n"
        "All purchases must adhere to the [Security Guidelines](./security_guidelines.md).\n"
    )
    concept = OKFConcept(
        id="remote_work_policy",
        type="Policy",
        title="Remote Work Hardware Allowance",
        description="Home office equipment stipend rules and procurement.",
        tags=["hr", "hardware", "remote", "allowance"],
        status="stable",
        body=body,
        file_path="concepts/remote_work_policy.md",
    )
    concept.edges = OKFConcept.extract_links(concept.id, concept.body)
    return concept
