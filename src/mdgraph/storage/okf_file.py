"""OKF File Manager: Handles reading, writing, and validation of OKF Markdown files."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from mdgraph.models import OKFConcept
from mdgraph.storage.git_repo import GitRepo


class OKFFileManager:
    """High-level manager for OKF concept Markdown files."""

    def __init__(self, repo: GitRepo):
        self.repo = repo

    def load_concept(self, file_path: Path | str) -> OKFConcept:
        """Load and parse an OKF concept from a file."""
        path_obj = Path(file_path)
        if not path_obj.is_absolute():
            path_obj = self.repo.repo_path / path_obj

        if not path_obj.exists():
            raise FileNotFoundError(f"File not found: {path_obj}")

        content = path_obj.read_text(encoding="utf-8")
        rel_path = str(path_obj.relative_to(self.repo.repo_path))
        commit_hash = self.repo.get_file_commit_hash(rel_path)

        return OKFConcept.from_markdown(
            content=content,
            file_path=rel_path,
            commit_hash=commit_hash,
        )

    def load_by_id(self, node_id: str) -> OKFConcept:
        """Load an OKF concept by its node ID."""
        content = self.repo.read_file(node_id)
        # Find the file path
        rel_path = f"concepts/{node_id}.md"
        if (self.repo.repo_path / rel_path).exists():
            pass
        elif (self.repo.repo_path / f"{node_id}.md").exists():
            rel_path = f"{node_id}.md"
        else:
            for p in self.repo.list_markdown_files():
                if p.stem == node_id:
                    rel_path = str(p.relative_to(self.repo.repo_path))
                    break

        commit_hash = self.repo.get_file_commit_hash(rel_path)
        return OKFConcept.from_markdown(
            content=content,
            file_path=rel_path,
            default_id=node_id,
            commit_hash=commit_hash,
        )

    def save_concept(
        self,
        concept: OKFConcept,
        commit_message: Optional[str] = None,
        subfolder: str = "concepts",
    ) -> Path:
        """Serialize and save concept to filesystem, committing to Git if auto_commit is enabled."""
        if not concept.file_path:
            rel_path = f"{subfolder}/{concept.id}.md"
            concept.file_path = rel_path
        else:
            rel_path = concept.file_path

        markdown_content = concept.to_markdown()
        target_path = self.repo.write_file(rel_path, markdown_content)

        msg = commit_message or f"Update concept: {concept.id} ({concept.title})"
        commit_hash = self.repo.commit(msg, paths=[rel_path])
        concept.commit_hash = commit_hash

        return target_path

    def delete_concept(self, node_id: str, commit_message: Optional[str] = None) -> bool:
        """Delete concept file and commit to Git."""
        try:
            concept = self.load_by_id(node_id)
            if concept.file_path:
                deleted = self.repo.delete_file(concept.file_path)
                if deleted:
                    msg = commit_message or f"Delete concept: {node_id}"
                    self.repo.commit(msg, paths=[concept.file_path])
                    return True
        except FileNotFoundError:
            pass
        return False

    def list_all_concepts(self) -> List[OKFConcept]:
        """Load all valid OKF concepts from the repository."""
        concepts: List[OKFConcept] = []
        for file_path in self.repo.list_markdown_files():
            try:
                concept = self.load_concept(file_path)
                concepts.append(concept)
            except Exception:
                # Skip non-OKF or invalid markdown files gracefully
                pass
        return concepts

    def validate_concept(self, concept: OKFConcept) -> List[str]:
        """Validate OKF conformance and check for broken cross-links."""
        errors: List[str] = []
        if not concept.id:
            errors.append("Concept missing unique 'id'.")
        if not concept.type:
            errors.append("Concept missing required 'type' field.")
        if not concept.title:
            errors.append("Concept missing 'title'.")

        # Check for link validity
        all_ids = {p.stem for p in self.repo.list_markdown_files()}
        all_ids.add(concept.id)
        for edge in concept.edges:
            if edge.target_id not in all_ids:
                errors.append(f"Broken cross-link: '{edge.target_id}' referenced by '{concept.id}' does not exist.")

        return errors
