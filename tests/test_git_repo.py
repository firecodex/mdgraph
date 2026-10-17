"""Unit tests for Git-backed truth layer and OKFFileManager."""

from mdgraph.models import OKFConcept
from mdgraph.storage.git_repo import GitRepo
from mdgraph.storage.okf_file import OKFFileManager


def test_git_repo_init_and_head(temp_dir):
    repo_path = temp_dir / "my_knowledge"
    repo = GitRepo(repo_path)

    assert repo.is_git_repo()
    assert (repo_path / "index.md").exists()
    head = repo.get_head_commit()
    assert head is not None
    assert len(head) == 40  # 40-char SHA


def test_git_repo_write_and_commit(git_repo):
    file_p = git_repo.write_file("concepts/test_doc.md", "# Test Document\n\nContent here.")
    assert file_p.exists()

    commit_sha = git_repo.commit("Add test_doc")
    assert commit_sha is not None

    file_commit = git_repo.get_file_commit_hash("concepts/test_doc.md")
    assert file_commit == commit_sha

    history = git_repo.get_history(limit=5)
    assert len(history) >= 2
    assert "Add test_doc" in history[0]["message"]


def test_okf_file_manager_save_and_load(git_repo):
    fm = OKFFileManager(git_repo)
    concept = OKFConcept(
        id="backend_service",
        type="System",
        title="Backend Microservice",
        description="Core API gateway service",
        tags=["backend", "api"],
        body="# Backend Microservice\n\nConnects to [PostgreSQL Cache](./postgres_cache.md).",
    )
    concept.edges = OKFConcept.extract_links(concept.id, concept.body)

    saved_path = fm.save_concept(concept)
    assert saved_path.exists()

    loaded = fm.load_by_id("backend_service")
    assert loaded.id == "backend_service"
    assert loaded.title == "Backend Microservice"
    assert len(loaded.edges) == 1
    assert loaded.edges[0].target_id == "postgres_cache"


def test_okf_file_manager_delete(git_repo):
    fm = OKFFileManager(git_repo)
    concept = OKFConcept(
        id="temp_concept",
        type="Concept",
        title="Temporary Concept",
        body="Will be deleted.",
    )
    fm.save_concept(concept)
    assert (git_repo.repo_path / "concepts/temp_concept.md").exists()

    success = fm.delete_concept("temp_concept")
    assert success
    assert not (git_repo.repo_path / "concepts/temp_concept.md").exists()
