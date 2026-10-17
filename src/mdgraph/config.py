"""Configuration loader and schema for MdGraph."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel, Field


class MdGraphConfig(BaseModel):
    """Runtime configuration for MdGraph engine."""
    repo_path: str = Field(default="./knowledge", description="Directory containing Git-backed OKF Markdown repository")
    cache_path: str = Field(default="./.mdgraph/cache.db", description="Path to SQLite query cache database")
    db_type: str = Field(default="sqlite", description="Database backend: 'sqlite' or 'postgres'")
    postgres_uri: Optional[str] = Field(default=None, description="PostgreSQL connection URI (if db_type is postgres)")
    mcp_host: str = Field(default="0.0.0.0", description="MCP server bind host for SSE/HTTP")
    mcp_port: int = Field(default=8000, description="MCP server port")
    llm_model: str = Field(default="openai/gpt-4o-mini", description="LiteLLM model string for compiler")
    llm_temperature: float = Field(default=0.1, description="LLM temperature for deterministic extraction")
    git_author_name: str = Field(default="MdGraph Compiler", description="Git author name for automated commits")
    git_author_email: str = Field(default="compiler@mdgraph.dev", description="Git author email")
    auto_commit: bool = Field(default=True, description="Automatically commit changes to Git repo")

    def resolve_paths(self, base_dir: Optional[Path] = None) -> MdGraphConfig:
        """Resolve relative paths relative to base_dir or cwd."""
        base = base_dir or Path.cwd()
        resolved_repo = Path(self.repo_path)
        if not resolved_repo.is_absolute():
            resolved_repo = (base / resolved_repo).resolve()

        resolved_cache = Path(self.cache_path)
        if not resolved_cache.is_absolute():
            resolved_cache = (base / resolved_cache).resolve()

        return MdGraphConfig(
            repo_path=str(resolved_repo),
            cache_path=str(resolved_cache),
            db_type=self.db_type,
            postgres_uri=self.postgres_uri,
            mcp_host=self.mcp_host,
            mcp_port=self.mcp_port,
            llm_model=self.llm_model,
            llm_temperature=self.llm_temperature,
            git_author_name=self.git_author_name,
            git_author_email=self.git_author_email,
            auto_commit=self.auto_commit,
        )


def load_config(config_path: Optional[str] = None) -> MdGraphConfig:
    """Load configuration from a YAML file, environment variables, or defaults."""
    config_dict = {}

    # Check potential config locations if not explicitly passed
    search_paths = []
    if config_path:
        search_paths.append(Path(config_path))
    else:
        search_paths.extend([
            Path("mdgraph.yaml"),
            Path("mdgraph.yml"),
            Path("config.yaml"),
            Path("config.yml"),
            Path(".mdgraph/config.yaml"),
        ])

    for p in search_paths:
        if p.is_file():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    loaded = yaml.safe_load(f)
                    if isinstance(loaded, dict):
                        config_dict = loaded
                        break
            except Exception:
                pass

    # Override with environment variables
    env_mappings = {
        "MDGRAPH_REPO_PATH": "repo_path",
        "MDGRAPH_CACHE_PATH": "cache_path",
        "MDGRAPH_DB_TYPE": "db_type",
        "MDGRAPH_POSTGRES_URI": "postgres_uri",
        "MDGRAPH_MCP_HOST": "mcp_host",
        "MDGRAPH_MCP_PORT": "mcp_port",
        "MDGRAPH_LLM_MODEL": "llm_model",
        "MDGRAPH_AUTO_COMMIT": "auto_commit",
    }
    for env_var, field_name in env_mappings.items():
        if env_var in os.environ:
            val = os.environ[env_var]
            if field_name == "mcp_port":
                config_dict[field_name] = int(val)
            elif field_name == "auto_commit":
                config_dict[field_name] = val.lower() in ("true", "1", "yes")
            else:
                config_dict[field_name] = val

    cfg = MdGraphConfig(**config_dict)
    return cfg.resolve_paths()
