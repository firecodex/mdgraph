"""OKF File Manager: Handles reading, writing, and validation of OKF Markdown files."""

from __future__ import annotations

from pathlib import Path

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

    def load_by_id(self, node_id: str, tenant_id: str | None = None) -> OKFConcept:
        """Load an OKF concept by its node ID and optional tenant."""
        content = self.repo.read_file(node_id, tenant_id=tenant_id)

        # Find the relative file path
        rel_path = None
        if tenant_id and tenant_id != "default":
            candidate = f"tenants/{tenant_id}/concepts/{node_id}.md"
            if (self.repo.repo_path / candidate).exists():
                rel_path = candidate
            else:
                alt = f"tenants/{tenant_id}/{node_id}.md"
                if (self.repo.repo_path / alt).exists():
                    rel_path = alt
        elif tenant_id == "default":
            candidate = f"concepts/{node_id}.md"
            if (self.repo.repo_path / candidate).exists():
                rel_path = candidate
            else:
                alt = f"{node_id}.md"
                if (self.repo.repo_path / alt).exists():
                    rel_path = alt

        if not rel_path:
            for p in self.repo.list_markdown_files(tenant_id=tenant_id):
                if p.stem == node_id:
                    rel_path = str(p.relative_to(self.repo.repo_path))
                    break

        if not rel_path:
            rel_path = f"concepts/{node_id}.md"

        commit_hash = self.repo.get_file_commit_hash(rel_path)
        concept = OKFConcept.from_markdown(
            content=content,
            file_path=rel_path,
            default_id=node_id,
            commit_hash=commit_hash,
        )
        if tenant_id and tenant_id != "default" and concept.tenant_id == "default":
            concept.tenant_id = tenant_id

        return concept

    def save_concept(
        self,
        concept: OKFConcept,
        commit_message: str | None = None,
        subfolder: str = "concepts",
    ) -> Path:
        """Serialize and save concept to filesystem, committing to Git if auto_commit is enabled."""
        tenant_id = concept.tenant_id or "default"
        if not concept.file_path:
            if tenant_id != "default":
                rel_path = f"tenants/{tenant_id}/{subfolder}/{concept.id}.md"
            else:
                rel_path = f"{subfolder}/{concept.id}.md"
            concept.file_path = rel_path
        else:
            rel_path = concept.file_path

        markdown_content = concept.to_markdown()
        target_path = self.repo.write_file(rel_path, markdown_content)

        tenant_suffix = f" [tenant:{tenant_id}]" if tenant_id != "default" else ""
        msg = commit_message or f"Update concept: {concept.id} ({concept.title}){tenant_suffix}"
        commit_hash = self.repo.commit(msg, paths=[rel_path])
        concept.commit_hash = commit_hash

        return target_path

    def delete_concept(self, node_id: str, tenant_id: str | None = None, commit_message: str | None = None) -> bool:
        """Delete concept file and commit to Git."""
        try:
            concept = self.load_by_id(node_id, tenant_id=tenant_id)
            if concept.file_path:
                deleted = self.repo.delete_file(concept.file_path)
                if deleted:
                    actual_tenant = concept.tenant_id or "default"
                    msg = commit_message or f"Delete concept: {node_id} (tenant:{actual_tenant})"
                    self.repo.commit(msg, paths=[concept.file_path])
                    return True
        except FileNotFoundError:
            pass
        return False

    def list_all_concepts(self, tenant_id: str | None = None) -> list[OKFConcept]:
        """Load all valid OKF concepts from the repository, optionally scoped to a tenant."""
        concepts: list[OKFConcept] = []
        for file_path in self.repo.list_markdown_files(tenant_id=tenant_id):
            try:
                concept = self.load_concept(file_path)
                if tenant_id is None or concept.tenant_id == tenant_id:
                    concepts.append(concept)
            except Exception:
                # Skip non-OKF or invalid markdown files gracefully
                pass
        return concepts

    def validate_concept(self, concept: OKFConcept) -> list[str]:
        """Validate OKF conformance and check for broken cross-links."""
        errors: list[str] = []
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
