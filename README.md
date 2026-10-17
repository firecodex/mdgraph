# MdGraph

[![PyPI version](https://img.shields.io/badge/pypi-0.1.0-blue.svg)](https://pypi.org/project/mdgraph/)
[![Python Versions](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)](https://pypi.org/project/mdgraph/)
[![License](https://img.shields.io/badge/license-Apache%202.0-yellow.svg)](LICENSE)
[![MCP Protocol](https://img.shields.io/badge/MCP-FastMCP-orange.svg)](https://modelcontextprotocol.io/)

> **Kill the Vector Chunks. Store Explicit Knowledge Graphs.**
> A vectorless Open Knowledge Format (OKF) context engine for agentic AI.

MdGraph is an open-source storage engine designed to replace traditional vector databases for AI agents. Rather than chunking text into opaque vector embeddings and relying on approximate cosine similarity, MdGraph implements Google's **Open Knowledge Format (OKF)** to store explicit, human-readable knowledge graphs using Markdown and Git.

It provides deterministic, traversable, and version-controlled context for autonomous agents built on frameworks like **Google ADK**, **LangGraph**, **CrewAI**, and editors like **Cursor** or **Claude Desktop** via the **Model Context Protocol (MCP)**.

---

## Key Pillars

- **Universal Ingestion**: Ingest PDFs, HTML tables, presentation decks, or audio transcripts into structured Markdown without losing hierarchical structure or table integrity.
- **Pluggable LLM Compiler**: Compile knowledge using any LLM—from local Llama models via Ollama to Claude 3.5, Gemini 1.5, or GPT-4o—powered by LiteLLM and strict Pydantic validation.
- **Git-Backed Truth**: Markdown files with YAML frontmatter serve as the absolute source of truth. Every concept modification is auditable, versioned, and committed via Git.
- **Vectorless Indexing**: Ditches float arrays and cosine similarity. Uses SQLite FTS5 (for edge) or PostgreSQL (for enterprise) to index cross-links into graph edge tables and text into BM25 full-text search.
- **Sub-Millisecond Recursive CTE Traversal**: Multi-hop reasoning queries execute via SQL Recursive Common Table Expressions (`WITH RECURSIVE`), bypassing chunk ambiguity.
- **Native MCP Server**: Exposes your entire knowledge graph over FastMCP so agents can seamlessly call `get_concept()`, `search_knowledge()`, and `traverse_graph()`.

---

## System Architecture

MdGraph enforces a strict physical separation between the **Compiler Layer** (heavy, state-mutating, LLM-driven) and the **Query Cache** (lightweight, read-optimized, vectorless index).

```
   1. Ingest                 2. Compile                     3. Store & Index
(Docling / Parsers)   →   (LiteLLM + OKF Schema)   →   (Git Repo + SQLite FTS5 / CTE)
                                                                    │
                                                                    ▼
                                                            4. Serve (FastMCP)
                                                                    │
                                                      ┌─────────────┴─────────────┐
                                                      ▼                           ▼
                                                 Google ADK /                 Cursor /
                                                  LangGraph                Claude Desktop
```

### Relational Cache Mapping

| Markdown OKF Source | Relational Cache Target | Query Optimization |
|---|---|---|
| **YAML Frontmatter** | JSON / JSONB Columns | Exact-match scalar filtering, tag intersections |
| **Markdown Body** | SQLite FTS5 / Postgres tsvector | BM25 full-text keyword search and relevance |
| **Explicit Links** `[x](./y.md)` | Graph Edge Table `(source, target)` | Recursive Common Table Expressions (CTEs) |
| **File Metadata** | Git Commit Hashes | Cache invalidation, freshness & time-travel |

---

## Installation

```bash
pip install mdgraph-ai
```

Or install in development/editable mode:

```bash
git clone https://github.com/firecodex/mdgraph.git
cd mdgraph
pip install -e ".[dev]"
```

For PostgreSQL enterprise backend:

```bash
pip install "mdgraph-ai[postgres]"
```

---

## Quickstart

### 1. Initialize an OKF Knowledge Base

```bash
mdgraph init ./knowledge
```

This creates a Git-initialized folder with a root `index.md` and a `concepts/` directory.

### 2. Ingest Documents

Ingest raw PDF, HTML, or text files into normalized Markdown:

```bash
mdgraph ingest ./raw_documents/ --dest ./normalized/
```

### 3. Compile into OKF Concepts

Decompose documents into interconnected OKF concept files with explicit markdown cross-links:

```bash
# Using an LLM (OpenAI, Anthropic, Gemini, Ollama)
mdgraph compile ./normalized/company_handbook.md --model openai/gpt-4o-mini

# Or use offline / rule-based compiler without API keys:
mdgraph compile ./normalized/company_handbook.md --offline
```

### 4. Search and Multi-Hop Traversal

Search concepts using BM25:

```bash
mdgraph query "hardware allowance"
```

Traverse multi-hop topological connections via Recursive CTE:

```bash
mdgraph traverse remote_work_policy --depth 3
```

Display full details of a concept:

```bash
mdgraph show remote_work_policy
```

Inspect knowledge graph statistics:

```bash
mdgraph stats
```

---

## Serving via Model Context Protocol (MCP)

Start the local FastMCP server for autonomous agent consumption:

```bash
# Start SSE server (default on port 8000)
mdgraph serve --port 8000

# Or run with stdio transport (for Cursor or Claude Desktop)
mdgraph serve --transport stdio
```

### Agent MCP Tools Exposed

Autonomous agents can call the following deterministic tools:

- `get_concept(node_id: str) -> dict`: Retrieve metadata, tags, and direct cross-links for a concept.
- `read_concept_body(node_id: str) -> str`: Read the exact, unmodified OKF markdown body from Git.
- `search_knowledge(query: str, tags: list[str] = None, concept_type: str = None, limit: int = 10) -> list[dict]`: BM25 full-text keyword search.
- `traverse_graph(node_id: str, max_depth: int = 2, direction: str = "out") -> dict`: Execute Recursive CTE to return topological neighbors and reasoning pathways.
- `find_path(source_id: str, target_id: str, max_depth: int = 5) -> dict`: Find the shortest path between two concepts.
- `list_concepts(concept_type: str = None, tag: str = None) -> list[dict]`: Scalar filtering.
- `get_graph_stats() -> dict`: Total concepts, edges, and tag distributions.
- `reindex(rebuild: bool = False) -> dict`: Refresh or rebuild relational cache from Git.

### Connecting to Claude Desktop / Cursor

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "mdgraph": {
      "command": "mdgraph",
      "args": ["serve", "--transport", "stdio"]
    }
  }
}
```

Or connect via SSE endpoint:
```text
http://localhost:8000/sse
```

---

## Python API Usage

You can embed MdGraph directly into your Python agent workflows:

```python
from mdgraph import GitRepo, SQLiteQueryCache, IndexSyncWorker, OKFConcept

# 1. Initialize Git truth and relational cache
repo = GitRepo("./knowledge")
cache = SQLiteQueryCache("./.mdgraph/cache.db")
sync_worker = IndexSyncWorker(repo, cache)

# 2. Add an OKF Concept
concept = OKFConcept(
    id="remote_work_policy",
    type="Policy",
    title="Remote Work Hardware Allowance",
    description="Home office equipment stipend rules",
    tags=["hr", "hardware", "remote"],
    body=(
        "# Remote Work Hardware Allowance\n\n"
        "Employees receive a yearly stipend managed by the "
        "[IT Department](./it_department.md).\n"
    )
)
concept.edges = OKFConcept.extract_links(concept.id, concept.body)

from mdgraph.storage.okf_file import OKFFileManager
fm = OKFFileManager(repo)
fm.save_concept(concept)

# 3. Synchronize cache
sync_worker.sync()

# 4. Search and Traverse
results = cache.search("hardware stipend")
traversal = cache.traverse("remote_work_policy", max_depth=2)

print("Nodes in topological neighborhood:", [n["id"] for n in traversal.nodes])
```

---

## Open Knowledge Format (OKF) Specification

MdGraph implements Google's Open Knowledge Format v0.2. Every concept is stored as plain Markdown with YAML frontmatter:

```markdown
---
type: Policy
title: Remote Work Hardware Allowance
description: Home office equipment stipend rules
tags: [hr, hardware, remote]
status: stable
---

# Remote Work Hardware Allowance

Employees receive a yearly stipend managed by 
the [IT Department](./it_department.md).

## Approved Purchases
All equipment must be sourced via the 
[Vendor Portal](./vendor_portal.md).
```

---

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) for details.
