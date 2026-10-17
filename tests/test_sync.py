"""Unit tests for IndexSyncWorker."""

from mdgraph.indexer.sync import IndexSyncWorker
from mdgraph.models import OKFConcept
from mdgraph.storage.okf_file import OKFFileManager


def test_index_sync_incremental_and_rebuild(git_repo, sqlite_cache):
    fm = OKFFileManager(git_repo)
    c1 = OKFConcept(id="concept_one", type="Concept", title="Concept 1", body="Content 1")
    c2 = OKFConcept(id="concept_two", type="Concept", title="Concept 2", body="Content 2")
    fm.save_concept(c1)
    fm.save_concept(c2)

    sync_worker = IndexSyncWorker(git_repo, sqlite_cache)

    # 1. First sync: should index 3 concepts (index.md + concept_one + concept_two)
    s1 = sync_worker.sync()
    assert s1.indexed >= 2
    assert s1.updated == 0

    # 2. Second sync with no changes: should skip them
    s2 = sync_worker.sync()
    assert s2.indexed == 0
    assert s2.skipped >= 2

    # 3. Update concept 1
    c1.body = "Updated Content 1 with link [Concept 2](./concept_two.md)"
    c1.edges = OKFConcept.extract_links(c1.id, c1.body)
    fm.save_concept(c1, commit_message="Update concept 1")

    s3 = sync_worker.sync()
    assert s3.updated == 1

    # Check updated edges in cache
    cached = sqlite_cache.get_concept("concept_one")
    assert len(cached["outgoing_edges"]) == 1

    # 4. Delete concept 2 and test cache deletion synchronization
    fm.delete_concept("concept_two")
    s4 = sync_worker.sync()
    assert s4.deleted == 1
    assert sqlite_cache.get_concept("concept_two") is None

    # 5. Full rebuild
    s5 = sync_worker.rebuild()
    assert s5.indexed >= 1
