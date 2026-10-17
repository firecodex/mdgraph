"""Open Knowledge Format (OKF) data models and graph structures."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
from pydantic import BaseModel, Field, field_validator


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
    source_id: str
    target_id: str
    label: Optional[str] = "references"
    link_text: Optional[str] = None
    raw_target: Optional[str] = None

    def __hash__(self) -> int:
        return hash((self.source_id, self.target_id, self.label))


class OKFConcept(BaseModel):
    """Google Open Knowledge Format (OKF) Concept document.
    
    A Concept represents an explicit node in the graph, containing strict YAML
    frontmatter and a clean Markdown body with explicit cross-links.
    """
    id: str
    type: str = Field(..., description="OKF concept type (e.g., Concept, Policy, Entity, System, Metric)")
    title: str
    description: str = ""
    tags: List[str] = Field(default_factory=list)
    status: str = "stable"
    aliases: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    body: str = ""
    file_path: Optional[str] = None
    commit_hash: Optional[str] = None
    edges: List[Edge] = Field(default_factory=list)

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("OKF document must declare a non-empty 'type' field.")
        return v.strip()

    def to_markdown(self) -> str:
        """Serialize OKF concept back into standard Markdown with YAML frontmatter."""
        frontmatter_dict: Dict[str, Any] = {
            "type": self.type,
            "title": self.title,
        }
        if self.description:
            frontmatter_dict["description"] = self.description
        if self.tags:
            frontmatter_dict["tags"] = self.tags
        if self.status:
            frontmatter_dict["status"] = self.status
        if self.aliases:
            frontmatter_dict["aliases"] = self.aliases
        if self.metadata:
            for k, v in self.metadata.items():
                if k not in frontmatter_dict:
                    frontmatter_dict[k] = v

        yaml_str = yaml.safe_dump(frontmatter_dict, sort_keys=False, allow_unicode=True).strip()
        body_clean = self.body.strip()
        return f"---\n{yaml_str}\n---\n\n{body_clean}\n"

    @classmethod
    def from_markdown(
        cls,
        content: str,
        file_path: Optional[str] = None,
        default_id: Optional[str] = None,
        commit_hash: Optional[str] = None,
    ) -> OKFConcept:
        """Parse OKF Markdown file content, extracting frontmatter, body, and explicit links."""
        frontmatter_dict: Dict[str, Any] = {}
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
                    raise ValueError(f"Failed to parse YAML frontmatter: {e}")

        # Derive node id
        node_id = default_id
        if not node_id and file_path:
            node_id = Path(file_path).stem
        if not node_id:
            title = frontmatter_dict.get("title", "")
            node_id = normalize_node_id(title) if title else "unnamed_concept"

        # Determine type
        concept_type = frontmatter_dict.get("type", "Concept")
        title = frontmatter_dict.get("title", node_id.replace("_", " ").title())
        description = frontmatter_dict.get("description", "")
        tags = frontmatter_dict.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        status = frontmatter_dict.get("status", "stable")
        aliases = frontmatter_dict.get("aliases", [])
        if isinstance(aliases, str):
            aliases = [a.strip() for a in aliases.split(",") if a.strip()]

        # Filter out core keys from extra metadata
        core_keys = {"type", "title", "description", "tags", "status", "aliases"}
        extra_metadata = {k: v for k, v in frontmatter_dict.items() if k not in core_keys}

        # Extract explicit outgoing links from Markdown body
        edges = cls.extract_links(source_id=node_id, markdown_body=body)

        return cls(
            id=node_id,
            type=str(concept_type),
            title=str(title),
            description=str(description),
            tags=list(tags),
            status=str(status),
            aliases=list(aliases),
            metadata=extra_metadata,
            body=body,
            file_path=file_path,
            commit_hash=commit_hash,
            edges=edges,
        )

    @staticmethod
    def extract_links(source_id: str, markdown_body: str) -> List[Edge]:
        """Extract explicit cross-links from markdown body.
        
        Supports:
        - [Anchor Text](./concept_name.md)
        - [Anchor Text](concept_name.md)
        - [[target]]
        - [[target|Anchor Text]]
        """
        edges: List[Edge] = []
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
                edge_key = (source_id, target_id)
                if edge_key not in seen:
                    seen.add(edge_key)
                    edges.append(
                        Edge(
                            source_id=source_id,
                            target_id=target_id,
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
                edge_key = (source_id, target_id)
                if edge_key not in seen:
                    seen.add(edge_key)
                    edges.append(
                        Edge(
                            source_id=source_id,
                            target_id=target_id,
                            label="references",
                            link_text=anchor_text,
                            raw_target=raw_target,
                        )
                    )

        return edges


class ConceptDraft(BaseModel):
    """Pydantic schema used by the LLM Compiler for structured output extraction."""
    id: str = Field(..., description="Unique slug for this concept, e.g. remote_work_policy")
    type: str = Field(..., description="OKF concept type, e.g. Policy, Architecture, Entity, Tool, Metric")
    title: str = Field(..., description="Clear human-readable concept title")
    description: str = Field(..., description="Concise 1-2 sentence executive summary")
    tags: List[str] = Field(default_factory=list, description="Categorization tags")
    status: str = Field(default="stable", description="Lifecycle status: stable, draft, or deprecated")
    body: str = Field(..., description="Detailed Markdown content including explicit cross-links to other concepts [Concept](./concept_id.md)")
    related_concept_ids: List[str] = Field(default_factory=list, description="List of concept IDs referenced or related")


class ExtractedGraph(BaseModel):
    """Collection of extracted concepts from compiler pass."""
    concepts: List[ConceptDraft] = Field(default_factory=list)
    source_document: Optional[str] = None


class SearchResult(BaseModel):
    """Search match returned by FTS5 full-text search."""
    id: str
    type: str
    title: str
    description: str
    tags: List[str]
    rank: float
    snippet: Optional[str] = None
    file_path: str


class TraverseResult(BaseModel):
    """Graph traversal result computed via Recursive Common Table Expression (CTE)."""
    root_id: str
    max_depth: int
    direction: str = "out"
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
    edges: List[Dict[str, Any]] = Field(default_factory=list)
    paths: List[List[str]] = Field(default_factory=list)


class GraphStats(BaseModel):
    """Global statistics of the indexed knowledge graph."""
    total_concepts: int
    total_edges: int
    concept_types: Dict[str, int]
    top_tags: Dict[str, int]
    git_head: Optional[str] = None
    last_indexed_at: Optional[str] = None


class GraphResult(BaseModel):
    """Complete graph snapshot with all nodes and edges."""
    concepts: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    stats: GraphStats
