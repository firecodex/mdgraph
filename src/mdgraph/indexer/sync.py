"""Indexing Sync Worker: Synchronizes Git Markdown repository to relational query cache."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Set

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

    def sync(self, force: bool = False) -> SyncSummary:
        """Incrementally sync repository Markdown files into query cache."""
        start_time = time.perf_counter()
        summary = SyncSummary()

        active_concept_ids: Set[str] = set()
        md_files = self.repo.list_markdown_files()

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
                active_concept_ids.add(concept.id)

                existing = self.cache.get_concept(concept.id)
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

        # Check for deleted concepts in cache
        existing_concepts = self.cache.list_concepts(limit=100000)
        for ec in existing_concepts:
            cid = ec["id"]
            if cid not in active_concept_ids:
                self.cache.delete_concept(cid)
                summary.deleted += 1

        summary.duration_ms = (time.perf_counter() - start_time) * 1000.0
        return summary

    def rebuild(self) -> SyncSummary:
        """Drop all tables in the query cache and rebuild fresh from Git truth."""
        self.cache.clear()
        return self.sync(force=True)
