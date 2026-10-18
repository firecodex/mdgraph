"""Git-backed truth storage layer for MdGraph.

Ensures that Markdown files in the filesystem serve as the absolute, auditable source of truth.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any


class GitRepo:
    """Manages a Git repository for OKF Markdown documents."""

    def __init__(
        self,
        repo_path: str | Path,
        author_name: str = "MdGraph Compiler",
        author_email: str = "compiler@mdgraph.dev",
        auto_init: bool = True,
    ):
        self.repo_path = Path(repo_path).resolve()
        self.author_name = author_name
        self.author_email = author_email

        if auto_init and not self.is_git_repo():
            self.init_repo()

    def _run_git(self, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
        """Run a git command in the repository directory."""
        env = os.environ.copy()
        env["GIT_AUTHOR_NAME"] = self.author_name
        env["GIT_AUTHOR_EMAIL"] = self.author_email
        env["GIT_COMMITTER_NAME"] = self.author_name
        env["GIT_COMMITTER_EMAIL"] = self.author_email

        return subprocess.run(
            ["git"] + args,
            cwd=str(self.repo_path),
            capture_output=True,
            text=True,
            check=check,
            env=env,
        )

    def is_git_repo(self) -> bool:
        """Check if repo_path contains a valid Git repository."""
        git_dir = self.repo_path / ".git"
        if not git_dir.exists():
            return False
        try:
            res = self._run_git(["rev-parse", "--is-inside-work-tree"], check=False)
            return res.returncode == 0 and res.stdout.strip() == "true"
        except Exception:
            return False

    def init_repo(self) -> None:
        """Initialize a new Git repository if not present."""
        self.repo_path.mkdir(parents=True, exist_ok=True)
        self._run_git(["init", "-b", "main"])
        # Configure local git user if not set
        self._run_git(["config", "user.name", self.author_name], check=False)
        self._run_git(["config", "user.email", self.author_email], check=False)

        # Create standard OKF root index.md if absent
        index_file = self.repo_path / "index.md"
        if not index_file.exists():
            index_content = (
                "---\n"
                "type: KnowledgeBase\n"
                "title: Root Knowledge Index\n"
                "description: MdGraph Open Knowledge Format (OKF) Root Index\n"
                "okf_version: \"0.2\"\n"
                "---\n\n"
                "# Knowledge Graph Index\n\n"
                "Welcome to the MdGraph OKF knowledge repository.\n"
            )
            index_file.write_text(index_content, encoding="utf-8")
            self.commit("Initialize MdGraph OKF repository with root index.md")

    def commit(self, message: str, paths: list[str] | None = None) -> str | None:
        """Stage files and create a commit. Returns commit hash or None if nothing changed."""
        try:
            if paths:
                for p in paths:
                    self._run_git(["add", str(p)])
            else:
                self._run_git(["add", "-A"])

            status = self._run_git(["status", "--porcelain"])
            if not status.stdout.strip():
                # Nothing to commit
                return self.get_head_commit()

            self._run_git(["commit", "-m", message])
            return self.get_head_commit()
        except Exception:
            # If commit fails (e.g. empty commit), return current head
            return self.get_head_commit()

    def get_head_commit(self) -> str | None:
        """Get the full SHA of HEAD commit."""
        try:
            res = self._run_git(["rev-parse", "HEAD"], check=False)
            if res.returncode == 0:
                return res.stdout.strip()
            return None
        except Exception:
            return None

    def get_file_commit_hash(self, rel_path: str | Path) -> str | None:
        """Get the commit hash that last modified the specified file."""
        try:
            res = self._run_git(
                ["log", "-n", "1", "--pretty=format:%H", "--", str(rel_path)],
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
            return self.get_head_commit()
        except Exception:
            return self.get_head_commit()

    def list_markdown_files(self, tenant_id: str | None = None) -> list[Path]:
        """List all .md files in the repository, optionally scoped to a tenant."""
        md_files = []

        for root, dirs, files in os.walk(self.repo_path):
            # Exclude hidden directories and cache dirs
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
            for f in files:
                if f.endswith(".md"):
                    full_p = Path(root) / f
                    rel_p = full_p.relative_to(self.repo_path)

                    if tenant_id is not None:
                        if tenant_id == "default":
                            # Default tenant includes files outside tenants/ OR files under tenants/default/
                            parts = rel_p.parts
                            if parts and parts[0] == "tenants" and (len(parts) < 2 or parts[1] != "default"):
                                continue
                        else:
                            # Specific tenant: must be under tenants/{tenant_id}/
                            parts = rel_p.parts
                            if not (len(parts) >= 2 and parts[0] == "tenants" and parts[1] == tenant_id):
                                continue

                    md_files.append(full_p)
        return sorted(md_files)

    def read_file(self, node_id_or_path: str, tenant_id: str | None = None) -> str:
        """Read Markdown file by node_id or relative path, optionally scoped to tenant."""
        # 1. If tenant_id specified and not default, check tenant directory first
        if tenant_id and tenant_id != "default":
            tenant_concept = self.repo_path / "tenants" / tenant_id / "concepts" / f"{node_id_or_path}.md"
            if tenant_concept.is_file():
                return tenant_concept.read_text(encoding="utf-8")

            tenant_file = self.repo_path / "tenants" / tenant_id / f"{node_id_or_path}.md"
            if tenant_file.is_file():
                return tenant_file.read_text(encoding="utf-8")

            tenant_direct = self.repo_path / "tenants" / tenant_id / node_id_or_path
            if tenant_direct.is_file():
                return tenant_direct.read_text(encoding="utf-8")

            for p in self.list_markdown_files(tenant_id=tenant_id):
                if p.stem == node_id_or_path or p.name == node_id_or_path:
                    return p.read_text(encoding="utf-8")

        # 2. Try direct path relative to repo root
        target = self.repo_path / node_id_or_path
        if target.is_file():
            return target.read_text(encoding="utf-8")

        # 3. Try with .md extension
        if not node_id_or_path.endswith(".md"):
            target_md = self.repo_path / f"{node_id_or_path}.md"
            if target_md.is_file():
                return target_md.read_text(encoding="utf-8")

            # Try under concepts/
            target_concepts = self.repo_path / "concepts" / f"{node_id_or_path}.md"
            if target_concepts.is_file():
                return target_concepts.read_text(encoding="utf-8")

        # 4. Search recursively across candidate files
        candidate_files = self.list_markdown_files(tenant_id=tenant_id)
        for p in candidate_files:
            if p.stem == node_id_or_path or p.name == node_id_or_path:
                return p.read_text(encoding="utf-8")

        raise FileNotFoundError(f"Concept or file '{node_id_or_path}' not found in {self.repo_path}")

    def list_tenants(self) -> list[str]:
        """Discover all tenant identifiers present in the repository filesystem."""
        tenants = set()
        tenants_dir = self.repo_path / "tenants"
        if tenants_dir.is_dir():
            for child in tenants_dir.iterdir():
                if child.is_dir() and not child.name.startswith("."):
                    tenants.add(child.name)

        # If root concepts or index.md exist, include 'default'
        if (self.repo_path / "concepts").is_dir() or (self.repo_path / "index.md").is_file() or not tenants:
            tenants.add("default")

        return sorted(tenants)

    def write_file(self, rel_path: str | Path, content: str) -> Path:
        """Write content to a file in repository and return absolute path."""
        target = self.repo_path / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def delete_file(self, rel_path: str | Path) -> bool:
        """Delete file from repository."""
        target = self.repo_path / rel_path
        if target.is_file():
            target.unlink()
            return True
        return False

    def get_history(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get list of recent commits."""
        try:
            res = self._run_git(
                ["log", f"-n{limit}", "--pretty=format:%H%x09%an%x09%ad%x09%s", "--date=iso"],
                check=False,
            )
            if res.returncode != 0 or not res.stdout.strip():
                return []

            commits = []
            for line in res.stdout.strip().splitlines():
                parts = line.split("\t")
                if len(parts) >= 4:
                    commits.append({
                        "commit_hash": parts[0],
                        "author": parts[1],
                        "date": parts[2],
                        "message": parts[3],
                    })
            return commits
        except Exception:
            return []

    def get_diff(self, commit_hash: str | None = None) -> str:
        """Get git diff from HEAD or specified commit."""
        try:
            args = ["diff"]
            if commit_hash:
                args.append(commit_hash)
            res = self._run_git(args, check=False)
            return res.stdout
        except Exception:
            return ""
