"""Indexing Sync Worker: Synchronizes Git Markdown repository to relational query cache."""

from __future__ import annotations

import time
from dataclasses import dataclass

from mdgraph.indexer.base import BaseQueryCache
from mdgraph.models import OKFConcept
from mdgraph.storage.git_repo import GitRepo
from mdgraph.storage.okf_file import OKFFileManager


@dataclass
class SyncSummary:
    """Summary metrics of an index synchronization run."""
    indexed: int = 0
    updated: int = 0
    deleted: int = 0
    skipped: int = 0
    errors: int = 0
    duration_ms: float = 0.0


class IndexSyncWorker:
    """Worker that translates file-based Git Markdown truth into the relational cache."""

    def __init__(self, repo: GitRepo, cache: BaseQueryCache):
        self.repo = repo
        self.cache = cache
        self.file_manager = OKFFileManager(repo)

    def sync(self, tenant_id: str | None = None, force: bool = False) -> SyncSummary:
        """Incrementally sync repository Markdown files into query cache, optionally scoped to tenant."""
        start_time = time.perf_counter()
        summary = SyncSummary()

        active_concepts: set[tuple[str, str]] = set()
        md_files = self.repo.list_markdown_files(tenant_id=tenant_id)

        for file_path in md_files:
            try:
                rel_path = str(file_path.relative_to(self.repo.repo_path))
                commit_hash = self.repo.get_file_commit_hash(rel_path)

                # Read raw content
                content = file_path.read_text(encoding="utf-8")
                # Attempt to parse as OKFConcept
                concept = OKFConcept.from_markdown(
                    content=content,
                    file_path=rel_path,
                    commit_hash=commit_hash,
                )
                c_tenant = concept.tenant_id or "default"
                active_concepts.add((c_tenant, concept.id))

                existing = self.cache.get_concept(concept.id, tenant_id=c_tenant)
                if not force and existing:
                    # Check if commit hash or content is identical
                    if existing.get("commit_hash") == commit_hash and commit_hash is not None:
                        summary.skipped += 1
                        continue

                self.cache.insert_or_update_concept(concept)
                if existing:
                    summary.updated += 1
                else:
                    summary.indexed += 1

            except Exception:
                summary.errors += 1

        # Check for deleted concepts in cache scoped to tenant
        existing_concepts = self.cache.list_concepts(tenant_id=tenant_id, limit=100000)
        for ec in existing_concepts:
            ec_tenant = ec.get("tenant_id", "default")
            cid = ec["id"]
            if (ec_tenant, cid) not in active_concepts:
                self.cache.delete_concept(cid, tenant_id=ec_tenant)
                summary.deleted += 1

        summary.duration_ms = (time.perf_counter() - start_time) * 1000.0
        return summary

    def rebuild(self, tenant_id: str | None = None) -> SyncSummary:
        """Rebuild cache fresh from Git truth (optionally scoped to a tenant)."""
        if tenant_id is None:
            self.cache.clear()
            return self.sync(tenant_id=None, force=True)

        # Scoped rebuild: remove concepts for this tenant
        existing_concepts = self.cache.list_concepts(tenant_id=tenant_id, limit=100000)
        for ec in existing_concepts:
            self.cache.delete_concept(ec["id"], tenant_id=tenant_id)

        return self.sync(tenant_id=tenant_id, force=True)
