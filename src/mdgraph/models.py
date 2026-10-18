"""Open Knowledge Format (OKF) data models and graph structures."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

# Regex pattern to match standard Markdown links: [Anchor Text](target.md or ./target.md or target)
MD_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
# Regex pattern to match Obsidian/wiki-style links: [[target]] or [[target|Anchor Text]]
WIKI_LINK_PATTERN = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def normalize_node_id(raw_target: str) -> str:
    """Normalize a target reference (e.g., './it_department.md' or 'IT Department') to a clean slug ID."""
    clean = raw_target.strip()
    # Strip URL fragments or query params if any
    clean = clean.split("#")[0].split("?")[0]
    # Strip relative path prefix
    if clean.startswith("./"):
        clean = clean[2:]
    elif clean.startswith("../"):
        clean = clean.replace("../", "")
    # Strip .md extension
    if clean.lower().endswith(".md"):
        clean = clean[:-3]
    # Remove directory paths if referencing concepts/xyz
    clean = clean.split("/")[-1]
    # Convert to lowercase slug
    clean = re.sub(r"[^\w\-]+", "_", clean.lower()).strip("_")
    return clean


class Edge(BaseModel):
    """Represents a directional edge between two concepts in the knowledge graph."""
    model_config = ConfigDict(extra="allow")

    source_id: str
    target_id: str
    tenant_id: str = "default"
    label: str | None = "references"
    link_text: str | None = None
    raw_target: str | None = None

    def __hash__(self) -> int:
        return hash((self.tenant_id, self.source_id, self.target_id, self.label))


class OKFConcept(BaseModel):
    """Google Open Knowledge Format (OKF v0.2 / v2) Concept document with Future-Proofing.

    A Concept represents an explicit node in the graph, containing strict YAML
    frontmatter and a clean Markdown body with explicit cross-links.

    Fully compliant with:
    - OKF v0.1: type, title, description, tags, status, aliases
    - OKF v0.2 / v2: provenance (generated), trust attestations (verified), sources,
      canonical resource URI, and freshness lifecycle (stale_after)
    - Future OKF versions (v3+): extra="allow" and transparent open-world metadata absorption.
    """
    model_config = ConfigDict(extra="allow")

    okf_version: str = Field(default="0.2", description="OKF specification version, e.g. '0.2'")
    id: str
    tenant_id: str = Field(default="default", description="Workspace/tenant identifier for multi-tenant isolation")
    type: str = Field(..., description="OKF concept type (e.g., Concept, Policy, Entity, System, Metric, Article, Tool)")
    title: str
    description: str = ""
    resource: str | None = Field(default=None, description="Canonical source URL or resource identifier")
    tags: list[str] = Field(default_factory=list)
    status: str = Field(default="stable", description="Lifecycle status (stable, draft, deprecated, expired, archived)")
    stale_after: str | None = Field(default=None, description="ISO date or timestamp after which concept is considered stale")
    generated: dict[str, Any] | None = Field(default=None, description="Provenance: generator metadata ({by: ..., at: ...})")
    verified: list[dict[str, Any]] = Field(default_factory=list, description="Verification records ({by: ..., at: ..., notes: ...})")
    sources: list[str] = Field(default_factory=list, description="Upstream document sources or context file paths")
    aliases: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary custom or future-version frontmatter fields")
    body: str = ""
    file_path: str | None = None
    commit_hash: str | None = None
    edges: list[Edge] = Field(default_factory=list)

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("OKF document must declare a non-empty 'type' field.")
        return v.strip()

    @property
    def outgoing_links(self) -> list[str]:
        """Return list of target IDs for all explicit outgoing edges."""
        return [e.target_id for e in self.edges]

    @property
    def is_verified(self) -> bool:
        """Return True if this concept has at least one verification attestation."""
        return bool(self.verified and len(self.verified) > 0)

    @property
    def is_stale(self) -> bool:
        """Return True if stale_after is defined and today's date is past that threshold."""
        if not self.stale_after:
            return False
        try:
            clean_date = str(self.stale_after).split("T")[0].strip()
            stale_dt = datetime.strptime(clean_date, "%Y-%m-%d").date()
            return date.today() > stale_dt
        except Exception:
            return False

    @property
    def provenance_author(self) -> str:
        """Return generator identity (e.g. 'agent:gpt-4o-mini' or 'human:suganthan')."""
        if isinstance(self.generated, dict):
            return str(self.generated.get("by", "unknown"))
        return "unspecified"

    def to_metadata_dict(self) -> dict[str, Any]:
        """Produce a comprehensive metadata dictionary preserving all OKF v2 and future attributes."""
        meta = dict(self.metadata)
        meta["okf_version"] = self.okf_version
        meta["tenant_id"] = self.tenant_id
        if self.resource:
            meta["resource"] = self.resource
        if self.stale_after:
            meta["stale_after"] = self.stale_after
        if self.generated:
            meta["generated"] = self.generated
        if self.verified:
            meta["verified"] = self.verified
        if self.sources:
            meta["sources"] = self.sources
        meta["is_verified"] = self.is_verified
        meta["is_stale"] = self.is_stale
        return meta

    def to_markdown(self) -> str:
        """Serialize OKF concept back into standard Markdown with YAML frontmatter."""
        frontmatter_dict: dict[str, Any] = {
            "okf_version": str(self.okf_version),
            "type": self.type,
            "title": self.title,
        }
        if self.tenant_id and self.tenant_id != "default":
            frontmatter_dict["tenant_id"] = self.tenant_id
        if self.description:
            frontmatter_dict["description"] = self.description
        if self.resource:
            frontmatter_dict["resource"] = self.resource
        if self.tags:
            frontmatter_dict["tags"] = self.tags
        if self.status:
            frontmatter_dict["status"] = self.status
        if self.stale_after:
            frontmatter_dict["stale_after"] = self.stale_after
        if self.generated:
            frontmatter_dict["generated"] = self.generated
        if self.verified:
            frontmatter_dict["verified"] = self.verified
        if self.sources:
            frontmatter_dict["sources"] = self.sources
        if self.aliases:
            frontmatter_dict["aliases"] = self.aliases

        # Preserve any arbitrary custom or future OKF metadata keys
        if self.metadata:
            for k, v in self.metadata.items():
                if k not in frontmatter_dict:
                    frontmatter_dict[k] = v

        # Absorb any dynamic pydantic extra attributes
        extra_attrs = getattr(self, "__pydantic_extra__", None)
        if extra_attrs and isinstance(extra_attrs, dict):
            for k, v in extra_attrs.items():
                if k not in frontmatter_dict:
                    frontmatter_dict[k] = v

        yaml_str = yaml.safe_dump(frontmatter_dict, sort_keys=False, allow_unicode=True).strip()
        body_clean = self.body.strip()
        return f"---\n{yaml_str}\n---\n\n{body_clean}\n"

    @classmethod
    def from_markdown(
        cls,
        content: str,
        file_path: str | None = None,
        default_id: str | None = None,
        default_tenant_id: str | None = None,
        commit_hash: str | None = None,
    ) -> OKFConcept:
        """Parse OKF Markdown file content, extracting frontmatter, body, and explicit links."""
        frontmatter_dict: dict[str, Any] = {}
        body = content

        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                yaml_content = parts[1]
                body = parts[2].strip()
                try:
                    loaded = yaml.safe_load(yaml_content)
                    if isinstance(loaded, dict):
                        frontmatter_dict = loaded
                except Exception as e:
                    raise ValueError(f"Failed to parse YAML frontmatter: {e}") from e

        # Derive node id
        node_id = default_id
        if not node_id and file_path:
            node_id = Path(file_path).stem
        if not node_id:
            title = frontmatter_dict.get("title", "")
            node_id = normalize_node_id(title) if title else "unnamed_concept"

        # Determine version (support okf_version, version, format_version; default to "0.2")
        okf_version = (
            frontmatter_dict.get("okf_version")
            or frontmatter_dict.get("version")
            or frontmatter_dict.get("format_version")
            or "0.2"
        )

        # Derive tenant_id from frontmatter or directory path (tenants/<tenant_id>/...)
        inferred_tenant = default_tenant_id or "default"
        if file_path:
            norm_path = file_path.replace("\\", "/")
            if "tenants/" in norm_path:
                parts = norm_path.split("/")
                if "tenants" in parts:
                    idx = parts.index("tenants")
                    if idx + 1 < len(parts):
                        inferred_tenant = parts[idx + 1]

        tenant_id = str(frontmatter_dict.get("tenant_id", inferred_tenant)).strip() or "default"

        # Core fields
        concept_type = frontmatter_dict.get("type", "Concept")
        title = frontmatter_dict.get("title", node_id.replace("_", " ").title())
        description = frontmatter_dict.get("description", "")
        resource = frontmatter_dict.get("resource")
        status = frontmatter_dict.get("status", "stable")
        stale_after = frontmatter_dict.get("stale_after")
        if stale_after is not None:
            stale_after = str(stale_after)

        # Provenance (generated)
        generated = frontmatter_dict.get("generated")
        if isinstance(generated, str):
            generated = {"by": generated, "at": datetime.now(timezone.utc).isoformat()}

        # Trust & Verification (verified)
        verified_raw = frontmatter_dict.get("verified", [])
        verified: list[dict[str, Any]] = []
        if isinstance(verified_raw, list):
            for v in verified_raw:
                if isinstance(v, dict):
                    verified.append(v)
                elif isinstance(v, str):
                    verified.append({"by": v})
        elif isinstance(verified_raw, dict):
            verified.append(verified_raw)
        elif isinstance(verified_raw, str):
            verified.append({"by": verified_raw})

        # Sources / lineage
        sources_raw = frontmatter_dict.get("sources", [])
        sources: list[str] = []
        if isinstance(sources_raw, list):
            sources = [str(s).strip() for s in sources_raw if s]
        elif isinstance(sources_raw, str):
            sources = [s.strip() for s in sources_raw.split(",") if s.strip()]

        # Tags & Aliases
        tags = frontmatter_dict.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        aliases = frontmatter_dict.get("aliases", [])
        if isinstance(aliases, str):
            aliases = [a.strip() for a in aliases.split(",") if a.strip()]

        # Filter out known core keys to preserve any future metadata keys
        core_keys = {
            "okf_version", "version", "format_version",
            "type", "title", "description", "resource",
            "tags", "status", "stale_after",
            "generated", "verified", "sources", "aliases",
            "tenant_id",
        }
        extra_metadata = {k: v for k, v in frontmatter_dict.items() if k not in core_keys}

        # Extract explicit outgoing links from Markdown body scoped to tenant
        edges = cls.extract_links(source_id=node_id, markdown_body=body, tenant_id=tenant_id)

        return cls(
            okf_version=str(okf_version),
            id=node_id,
            tenant_id=tenant_id,
            type=str(concept_type),
            title=str(title),
            description=str(description),
            resource=str(resource) if resource else None,
            tags=list(tags),
            status=str(status),
            stale_after=stale_after,
            generated=generated,
            verified=verified,
            sources=sources,
            aliases=list(aliases),
            metadata=extra_metadata,
            body=body,
            file_path=file_path,
            commit_hash=commit_hash,
            edges=edges,
        )

    @staticmethod
    def extract_links(source_id: str, markdown_body: str, tenant_id: str = "default") -> list[Edge]:
        """Extract explicit cross-links from markdown body.

        Supports:
        - [Anchor Text](./concept_name.md)
        - [Anchor Text](concept_name.md)
        - [[target]]
        - [[target|Anchor Text]]
        """
        edges: list[Edge] = []
        seen = set()

        # 1. Match Markdown links [Text](target)
        for match in MD_LINK_PATTERN.finditer(markdown_body):
            anchor_text = match.group(1).strip()
            raw_target = match.group(2).strip()

            # Ignore external HTTP/HTTPS/mailto URLs
            if raw_target.startswith(("http://", "https://", "mailto:", "ftp://", "#")):
                continue

            target_id = normalize_node_id(raw_target)
            if target_id and target_id != source_id:
                edge_key = (tenant_id, source_id, target_id)
                if edge_key not in seen:
                    seen.add(edge_key)
                    edges.append(
                        Edge(
                            source_id=source_id,
                            target_id=target_id,
                            tenant_id=tenant_id,
                            label="references",
                            link_text=anchor_text,
                            raw_target=raw_target,
                        )
                    )

        # 2. Match Wikilinks [[target]] or [[target|label]]
        for match in WIKI_LINK_PATTERN.finditer(markdown_body):
            raw_target = match.group(1).strip()
            anchor_text = match.group(2).strip() if match.group(2) else raw_target

            target_id = normalize_node_id(raw_target)
            if target_id and target_id != source_id:
                edge_key = (tenant_id, source_id, target_id)
                if edge_key not in seen:
                    seen.add(edge_key)
                    edges.append(
                        Edge(
                            source_id=source_id,
                            target_id=target_id,
                            tenant_id=tenant_id,
                            label="references",
                            link_text=anchor_text,
                            raw_target=raw_target,
                        )
                    )

        return edges


class ConceptDraft(BaseModel):
    """Pydantic schema used by the LLM Compiler for structured output extraction."""
    model_config = ConfigDict(extra="allow")

    id: str = Field(..., description="Unique slug for this concept, e.g. remote_work_policy")
    tenant_id: str = Field(default="default", description="Workspace/tenant identifier")
    type: str = Field(..., description="OKF concept type, e.g. Policy, Architecture, Entity, System, Metric, Tool, Article")
    title: str = Field(..., description="Clear human-readable concept title")
    description: str = Field(..., description="Concise 1-2 sentence executive summary")
    resource: str | None = Field(default=None, description="Optional canonical reference URL")
    tags: list[str] = Field(default_factory=list, description="Categorization tags")
    status: str = Field(default="stable", description="Lifecycle status: stable, draft, deprecated, expired")
    stale_after: str | None = Field(default=None, description="Optional freshness deadline, e.g. 2027-01-01")
    sources: list[str] = Field(default_factory=list, description="Upstream document or source context")
    body: str = Field(..., description="Detailed Markdown content including explicit cross-links to other concepts [Concept](./concept_id.md)")
    related_concept_ids: list[str] = Field(default_factory=list, description="List of concept IDs referenced or related")


class ExtractedGraph(BaseModel):
    """Collection of extracted concepts from compiler pass."""
    concepts: list[ConceptDraft] = Field(default_factory=list)
    source_document: str | None = None


class SearchResult(BaseModel):
    """Search match returned by FTS5 full-text search."""
    id: str
    tenant_id: str = "default"
    type: str
    title: str
    description: str
    tags: list[str]
    rank: float
    snippet: str | None = None
    file_path: str


class TraverseResult(BaseModel):
    """Graph traversal result computed via Recursive Common Table Expression (CTE)."""
    root_id: str
    tenant_id: str = "default"
    max_depth: int
    direction: str = "out"
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    paths: list[list[str]] = Field(default_factory=list)


class GraphStats(BaseModel):
    """Global statistics of the indexed knowledge graph."""
    total_concepts: int
    total_edges: int
    concept_types: dict[str, int]
    top_tags: dict[str, int]
    git_head: str | None = None
    last_indexed_at: str | None = None
    tenant_id: str | None = None
    tenants: list[str] = Field(default_factory=list)


class GraphResult(BaseModel):
    """Complete graph snapshot with all nodes and edges."""
    concepts: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    stats: GraphStats
