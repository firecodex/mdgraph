# <img src="assets/mdgraph.png" alt="MdGraph Logo" width="38" height="38" valign="middle"> MdGraph

[![PyPI version](https://img.shields.io/badge/pypi-0.1.1-blue.svg)](https://pypi.org/project/mdgraph/)
[![Python Versions](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)](https://pypi.org/project/mdgraph/)
[![License](https://img.shields.io/badge/license-Apache%202.0-yellow.svg)](LICENSE)
[![MCP Protocol](https://img.shields.io/badge/MCP-FastMCP-orange.svg)](https://modelcontextprotocol.io/)
[![REST API](https://img.shields.io/badge/REST%20API-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![CLI](https://img.shields.io/badge/CLI-Click%20%7C%20Rich-yellow.svg)](#)

> **Kill the Vector Chunks. Store Explicit Knowledge Graphs.**
> A vectorless Open Knowledge Format (OKF) context engine for agentic AI.

<p align="center">
  <img src="assets/mcp_multihop_demo.gif" alt="MdGraph FastMCP Multi-Hop Traversal Demo" width="880">
  <br>
  <em><strong>10-Second Demo</strong>: Autonomous agent dispatching <code>traverse_graph</code> over FastMCP — Sub-millisecond recursive CTE graph traversal with zero vector hallucinations.</em>
</p>

MdGraph is an open-source storage engine designed to replace traditional vector databases for AI agents. Rather than chunking text into opaque vector embeddings and relying on approximate cosine similarity, MdGraph implements Google's **Open Knowledge Format (OKF)** to store explicit, human-readable knowledge graphs using Markdown and Git.

### Three Primary Interfaces

MdGraph supports three first-class, interoperable operational interfaces:

1. 💻 **Command Line Interface (`mdgraph`)**: Full terminal control to initialize knowledge repositories, ingest local files/directories/URLs/YouTube videos, compile concepts offline or via LLM, build relational query indices, and execute topological multi-hop traversals.
2. 🤖 **Native FastMCP Server (`mdgraph serve`)**: Standardized Model Context Protocol server exposing deterministic tools (`get_concept`, `traverse_graph`, `search_knowledge`, `find_path`) over `stdio` and `sse` to autonomous agent fleets (Cursor, Claude Desktop, Google ADK, LangGraph, CrewAI).
3. ⚡ **Standalone FastAPI Service (`mdgraph api`)**: High-performance, asynchronous REST microservice for remote document ingestion, multipart file uploads, and one-shot compilation pipelines with zero overhead on core operations and interactive Swagger/OpenAPI documentation.

---

## Table of Contents

- [Key Pillars](#key-pillars)
- [System Architecture](#system-architecture)
  - [Relational Cache Mapping](#relational-cache-mapping)
- [Installation](#installation)
- [Quickstart (CLI)](#quickstart)
  - [1. Initialize Knowledge Base](#1-initialize-an-okf-knowledge-base)
  - [2. Universal Ingestion (Files, Web, YouTube)](#2-ingest-folders-websites-or-youtube-videos)
  - [3. LLM & Offline Compilation](#3-compile-into-okf-concepts)
  - [4. Synchronize or Rebuild Query Cache](#4-synchronize-or-rebuild-query-cache)
  - [5. BM25 Search & Recursive CTE Traversals](#5-search-and-multi-hop-traversal)
- [Serving via Model Context Protocol (FastMCP)](#serving-via-model-context-protocol-mcp)
  - [Agent MCP Tools Exposed](#agent-mcp-tools-exposed)
  - [Client Integration Scenarios (Claude, Cursor, Python SDK, LangGraph)](#mcp-client-integration-scenarios)
- [Standalone FastAPI REST Microservice](#standalone-fastapi-service-ingestion--compilation)
  - [REST API Endpoints & Swagger Docs](#rest-api-endpoints)
  - [cURL Command Examples](#rest-examples-with-curl)
- [Multi-Tenant Workspace Scoping (`tenant_id`)](#multi-tenant-workspace-scoping-tenant_id)
  - [Directory Layout & Relational Isolation](#workspace-directory-layout)
  - [Multi-Tenant CLI, REST, and FastMCP Usage](#multi-tenant-usage-across-interfaces)
- [Agent Reasoning Scenarios](#agent-reasoning-scenarios)
- [Storage Backends: SQLite vs PostgreSQL](#storage-options--deployment-architectures)
- [Cloud Deployment (Google Cloud Run & Docker)](#cloud-deployment-google-cloud-run--docker)
- [Configuration Reference](#configuration-reference)
- [Open Knowledge Format (OKF v0.2) Specification](#open-knowledge-format-okf-v02-specification)
- [Contributors](#contributors)
- [License](#license)

---

## Key Pillars

- **Three Supported Interfaces**: Interact seamlessly via the command line (**CLI**), autonomous agent protocol (**FastMCP Server**), or HTTP microservices (**FastAPI REST API**).
- **Universal Ingestion**: Ingest local folders (PDFs, HTML, markdown, text), live website URLs, or YouTube video transcripts into clean, structured Markdown without losing hierarchical structure or table integrity.
- **Pluggable LLM Compiler**: Compile knowledge using any LLM—from local Llama models via Ollama to Claude 3.5, Gemini 1.5, or GPT-4o—powered by LiteLLM and strict Pydantic validation.
- **Git-Backed Truth**: Markdown files with YAML frontmatter serve as the absolute source of truth. Every concept modification is auditable, versioned, and committed via Git.
- **Vectorless Indexing**: Ditches float arrays and cosine similarity. Uses SQLite FTS5 (for edge) or PostgreSQL (for enterprise) to index cross-links into graph edge tables and text into BM25 full-text search.
- **Sub-Millisecond Recursive CTE Traversal**: Multi-hop reasoning queries execute via SQL Recursive Common Table Expressions (`WITH RECURSIVE`), bypassing chunk ambiguity.
- **Native MCP Server**: Exposes your entire knowledge graph over FastMCP so agents can seamlessly call `get_concept()`, `search_knowledge()`, and `traverse_graph()`.
- **High-Performance REST API**: Dedicated asynchronous FastAPI endpoints for high-throughput ingestion, document parsing, and compilation without blocking the event loop.

---

## System Architecture

MdGraph enforces a strict physical separation between the **Compiler Layer** (heavy, state-mutating, LLM-driven) and the **Query Cache** (lightweight, read-optimized, vectorless index).

```
   1. Ingest                 2. Compile                     3. Store & Index
(Docling / Parsers)   →   (LiteLLM + OKF Schema)   →   (Git Repo + SQLite FTS5 / CTE)
                                                                    │
                                      ┌─────────────────────────────┴─────────────────────────────┐
                                      ▼                                                           ▼
                          4a. Serve (FastMCP)                                         4b. REST API (FastAPI)
                                      │                                                           │
                        ┌─────────────┴─────────────┐                               ┌─────────────┴─────────────┐
                        ▼                           ▼                               ▼                           ▼
                   Google ADK /                 Cursor /                       Microservices /             CI/CD & Webhooks
                    LangGraph                Claude Desktop                    Web Frontends
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

Install MdGraph via `pip`. When installing optional extras, always wrap the package name in quotes:

```bash
# Core framework (CLI, Native FastMCP Server, Git Engine, SQLite FTS5 / CTE)
pip install mdgraph-ai

# With Standalone FastAPI REST Microservice
pip install "mdgraph-ai[api]"

# With PostgreSQL Enterprise Backend (psycopg3)
pip install "mdgraph-ai[postgres]"

# Complete installation (all extras: API, PostgreSQL, and Dev tools)
pip install "mdgraph-ai[all]"
```

> [!TIP]
> **Zsh / macOS Users**: Always quote bracketed extras (e.g. `"mdgraph-ai[api]"`) to prevent zsh from interpreting brackets as glob patterns (`zsh: no matches found`).

### Local Development / Editable Mode
```bash
git clone https://github.com/firecodex/mdgraph.git
cd mdgraph
pip install -e ".[dev]"
```

---

## Quickstart

### 1. Initialize an OKF Knowledge Base

```bash
mdgraph init ./knowledge
```

This creates a Git-initialized folder with a root `index.md`, a `concepts/` directory, and default metadata.

### 2. Ingest Folders, Websites, or YouTube Videos

`mdgraph ingest` accepts a local folder, an individual file, a live website URL, or a YouTube video link:

```bash
# Ingest a directory of local files (PDFs, HTML, text, markdown)
mdgraph ingest ./raw_documents/ --dest ./normalized/

# Ingest an individual document (PDF, HTML, text)
mdgraph ingest ./specs/architecture.pdf --dest ./normalized/

# Ingest a live website URL (converts HTML and tables into structured Markdown)
mdgraph ingest https://docs.python.org/3/tutorial/ --dest ./normalized/

# Ingest a YouTube video URL (extracts metadata, channel, and timestamped transcripts)
mdgraph ingest https://www.youtube.com/watch?v=dQw4w9WgXcQ --dest ./normalized/

# Optional: Route ingestion into an isolated tenant workspace
mdgraph ingest ./specs/payments.pdf --tenant team_fintech
```

> **Destination directory**: If `--dest` is omitted, URLs default to `./normalized/` in your current working directory, and local files/folders default to `./normalized` relative to their parent directory.

### 3. Compile into OKF Concepts

Decompose documents into interconnected OKF concept files with explicit markdown cross-links:

```bash
# Using an LLM (OpenAI, Anthropic, Gemini, Ollama via LiteLLM)
mdgraph compile ./normalized/company_handbook.md --model openai/gpt-4o-mini

# Or compile offline / rule-based without an API key:
mdgraph compile ./normalized/company_handbook.md --offline

# Optional: Compile into a specific tenant workspace
mdgraph compile ./normalized/payments.md --tenant team_fintech --offline
```

### 4. Synchronize or Rebuild Query Cache

MdGraph keeps your Git Markdown files as the single source of truth and accelerates queries using an incremental relational cache:

```bash
# Incrementally sync recent Git commits into the query cache
mdgraph index

# Or completely wipe and rebuild the relational cache from Git
mdgraph index --rebuild

# Sync a specific tenant workspace
mdgraph index --tenant team_fintech
```

### 5. Search, Multi-Hop Traversal, & Inspection

Search concepts using BM25 full-text search:

```bash
mdgraph query "hardware allowance"
mdgraph query "payment gateway" --tenant team_fintech
```

Traverse multi-hop topological connections via Recursive Common Table Expressions (CTE):

```bash
# Traverse up to 3 hops away from root concept
mdgraph traverse remote_work_policy --depth 3

# Follow incoming backlinks instead of outgoing links
mdgraph traverse auth_service --direction in
```

Display full details and body of a concept:

```bash
mdgraph show remote_work_policy
mdgraph show remote_work_policy --raw
```

Inspect knowledge graph statistics and active workspaces:

```bash
# View global or tenant-scoped graph statistics
mdgraph stats
mdgraph stats --tenant team_fintech

# List all active tenant workspaces
mdgraph tenants
```

---

## Serving via Model Context Protocol (MCP)

MdGraph provides a built-in native **FastMCP** server that exposes deterministic knowledge graph operations to any autonomous agent framework supporting the Model Context Protocol.

```bash
# Start SSE HTTP server (default on port 8000)
mdgraph serve --port 8000

# Or run with stdio transport (for Cursor, Claude Desktop, or CLI pipelines)
mdgraph serve --transport stdio
```

### Agent MCP Tools Exposed

Autonomous agents can call the following deterministic tools:

| MCP Tool | Signature | Description |
|---|---|---|
| `get_concept` | `(node_id: str) -> dict` | Retrieve metadata, tags, and direct cross-links for a concept. |
| `read_concept_body` | `(node_id: str) -> str` | Read the exact, unmodified OKF markdown body from Git. |
| `search_knowledge` | `(query: str, tags: list[str] = None, concept_type: str = None, limit: int = 10) -> list[dict]` | BM25 full-text keyword search across title, body, and tags. |
| `traverse_graph` | `(node_id: str, max_depth: int = 2, direction: str = "out") -> dict` | Execute Recursive CTE to return topological neighbors and multi-hop pathways. |
| `find_path` | `(source_id: str, target_id: str, max_depth: int = 5) -> dict` | Find the shortest topological path between two concepts. |
| `list_concepts` | `(concept_type: str = None, tag: str = None) -> list[dict]` | Filter concepts by exact type or category tags. |
| `get_graph_stats` | `() -> dict` | Total concepts, edges, commit hash, and tag distribution. |
| `reindex` | `(rebuild: bool = False) -> dict` | Refresh or rebuild relational cache from Git truth. |

---

## MCP Client Integration Scenarios

### Scenario A: Claude Desktop & Cursor IDE (`stdio`)

Add MdGraph directly to your `claude_desktop_config.json` or `.cursor/mcp.json`:

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

Once configured, asking Claude or Cursor:
> *"What is our hardware policy and which department approves monitor purchases?"*

triggers autonomous calls to `search_knowledge("hardware")`, `traverse_graph("remote_work_policy")`, and `read_concept_body("vendor_portal")` with deterministic graph reasoning.

### Scenario B: Programmatic Python MCP Client (`mcp` SDK)

Connect any Python service directly to a running MdGraph MCP server:

```python
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def query_knowledge_graph():
    server_params = StdioServerParameters(
        command="mdgraph",
        args=["serve", "--transport", "stdio"]
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1. Search for entrypoint concept
            results = await session.call_tool("search_knowledge", {"query": "payment gateway"})
            print("Search Results:", results)

            # 2. Traverse multi-hop dependencies
            traversal = await session.call_tool("traverse_graph", {
                "node_id": "payment_gateway",
                "max_depth": 2
            })
            print("Topological Neighbors:", traversal)

asyncio.run(query_knowledge_graph())
```

### Scenario C: LangChain & LangGraph Agents

Wrap MdGraph MCP tools into LangChain tools using `langchain_mcp_adapters`:

```python
import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

async def run_langchain_agent():
    client = MultiServerMCPClient()
    # Connect to MdGraph SSE server
    await client.connect_to_server("mdgraph", url="http://localhost:8000/sse")
    tools = client.get_tools()

    llm = ChatOpenAI(model="gpt-4o")
    agent = create_react_agent(llm, tools)

    response = await agent.ainvoke({
        "messages": [("user", "Explain how customer onboarding connects to our billing system.")]
    })
    print(response["messages"][-1].content)

asyncio.run(run_langchain_agent())
```

---

## Standalone FastAPI Service (Ingestion & Compilation)

MdGraph provides an optional, standalone **FastAPI REST service** designed for production microservices, CI/CD pipelines, and agent webhooks. It allows remote clients to ingest documents (PDF, HTML, text, website URLs, YouTube video transcripts) and compile them into OKF concepts asynchronously over HTTP.

### Zero Performance Impact Architecture
- **Completely Optional**: FastAPI and its server dependencies are isolated in an optional extra (`pip install "mdgraph-ai[api]"`). The core CLI, storage engine, and query cache never import FastAPI unless the `api` command is explicitly run.
- **Asynchronous & Non-Blocking**: All CPU-heavy and I/O-heavy workloads (document parsing, YouTube caption fetching, LiteLLM calls, and Git commits) execute off-thread via `asyncio.to_thread`, preserving sub-millisecond event loop responsiveness under heavy concurrent load.

### Starting the Service

```bash
# Install optional REST API dependencies
pip install "mdgraph-ai[api]"

# Start standalone REST API server on default port 8080
mdgraph api --port 8080 --host 0.0.0.0

# Or run directly via Uvicorn ASGI
uvicorn mdgraph.server.rest_api:app --host 0.0.0.0 --port 8080 --workers 4
```

Interactive OpenAPI documentation is available out of the box at **`http://localhost:8080/docs`** (Swagger UI) and **`http://localhost:8080/redoc`** (ReDoc).

### REST API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` / `/api/v1/health` | Health check, knowledge repository path, and total concept count. |
| `POST` | `/api/v1/ingest` | Polymorphic ingestion accepting URLs, YouTube links, local paths, or folders. |
| `POST` | `/api/v1/ingest/url` | Ingest a public website URL or YouTube video link into normalized Markdown. |
| `POST` | `/api/v1/ingest/file` | Multipart file upload (`multipart/form-data`) supporting PDF, HTML, Markdown, and text. |
| `POST` | `/api/v1/ingest/text` | Ingest and normalize raw text or HTML strings. |
| `POST` | `/api/v1/compile` | Compile Markdown content into OKF concepts (supports LLM or offline, optional Git commit). |
| `POST` | `/api/v1/compile/file` | Compile an existing server-side file into OKF concepts. |
| `POST` | `/api/v1/pipeline` | **One-shot pipeline**: Ingest any source AND compile into OKF concepts in a single request. |
| `GET` | `/api/v1/concepts` | Search or list concepts from the relational query cache. |
| `GET` | `/api/v1/concepts/{node_id}` | Retrieve full concept metadata and Markdown body from Git. |

### REST Examples with cURL

```bash
# Ingest a website URL into normalized Markdown
curl -X POST "http://localhost:8080/api/v1/ingest/url" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://docs.python.org/3/tutorial/"}'

# Upload and ingest a PDF or HTML document
curl -X POST "http://localhost:8080/api/v1/ingest/file" \
  -F "file=@./specs/architecture.pdf"

# Compile raw markdown into OKF concepts offline and save to Git
curl -X POST "http://localhost:8080/api/v1/compile" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "# API Gateway\n\nHandles routing for [Auth Service](./auth_service.md).",
    "source_name": "gateway.md",
    "offline": true,
    "save_to_repo": true
  }'

# One-shot pipeline: Ingest a YouTube URL and compile into OKF concepts in Git
curl -X POST "http://localhost:8080/api/v1/pipeline" \
  -H "Content-Type: application/json" \
  -d '{
    "source": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "offline": true,
    "save_to_repo": true
  }'
```

---

## Agent Reasoning Scenarios

### Scenario 1: Multi-Hop Root-Cause & Policy Discovery

Vector similarity search struggles with questions where the answer spans multiple non-contiguous files:
> *"How do I buy an ergonomic keyboard, who approves it, and what are the security requirements?"*

```text
User Question
    │
    ▼
1. search_knowledge("ergonomic keyboard")  ──> Seed concept: [remote_work_policy]
    │
    ▼
2. traverse_graph("remote_work_policy", depth=2)
    ├── Outgoing edge ──> [vendor_portal]       (procurement workflow)
    ├── Outgoing edge ──> [it_department]       (approval rules)
    └── Outgoing edge ──> [security_guidelines] (device compliance)
    │
    ▼
3. read_concept_body("vendor_portal") & read_concept_body("security_guidelines")
    │
    ▼
Agent synthesizes a 100% cited, hallucination-free response.
```

### Scenario 2: Automated Knowledge Base Compilation & Synthesis

Incoming documentation (PDFs, HTML specs, or sprint tickets) can be parsed and continuously synthesized into OKF v2 concepts:

```python
from mdgraph.ingestion.ingestor import UniversalIngestor
from mdgraph.compiler.llm_compiler import LLMCompiler
from mdgraph.storage.okf_file import OKFFileManager
from mdgraph import GitRepo, SQLiteQueryCache, IndexSyncWorker

# 1. Normalize raw PDF/HTML, website URL, or YouTube video into clean markdown
ingestor = UniversalIngestor()
# Ingest local file/directory, website, or YouTube video:
normalized = ingestor.ingest("./raw_docs/architecture_v2.pdf")[0]
# Or from URL: ingestor.ingest("https://docs.python.org/3/tutorial/")
# Or from YouTube: ingestor.ingest("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

# 2. Decompose into interlinked OKF concepts with explicit relative links
compiler = LLMCompiler(model="openai/gpt-4o-mini")
concepts = compiler.compile(normalized.markdown_content, source_name="architecture_v2.pdf")

# 3. Commit to Git repository
repo = GitRepo("./knowledge")
file_manager = OKFFileManager(repo)
for concept in concepts:
    file_manager.save_concept(concept)

# 4. Synchronize relational query cache
cache = SQLiteQueryCache("./.mdgraph/cache.db")
IndexSyncWorker(repo, cache).sync()
```

### Scenario 3: Trust & Freshness Verification (OKF v0.2 Guardrails)

In multi-agent systems, agents can inspect trust signals to prevent acting on outdated or unverified content:

```python
from mdgraph.storage.okf_file import OKFFileManager
from mdgraph import GitRepo

repo = GitRepo("./knowledge")
fm = OKFFileManager(repo)
concept = fm.load_by_id("production_deployment_checklist")

# Verify agent trust signals
if concept.is_stale:
    print(f"Warning: Concept expired on {concept.stale_after}. Requesting human re-verification.")
elif not concept.is_verified:
    print("Warning: Concept was generated by AI and has not yet been attested by a human reviewer.")
else:
    print(f"Concept verified by: {concept.verified[0]['by']}. Safe to execute deployment.")
```

---

## Storage Options & Deployment Architectures

MdGraph decouples **long-term truth** (stored as human-readable Markdown files in Git) from **query acceleration** (cached in relational tables).

```text
┌────────────────────────────────────────────────────────┐
│            SINGLE SOURCE OF TRUTH (Git)               │
│  ./knowledge/concepts/*.md (OKF Frontmatter + Links)   │
└──────────────────────────┬─────────────────────────────┘
                           │
             Incremental Sync (Commit Hash)
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│               RELATIONAL QUERY CACHE                   │
│                                                        │
│   Option A: SQLite FTS5 (Local, Embedded, Zero-Config) │
│   Option B: PostgreSQL JSONB + tsvector (Enterprise)   │
└────────────────────────────────────────────────────────┘
```

### Storage Option 1: SQLite (Default, Zero-Config)

Ideal for local development, CLI tools, personal desktop agents, and single-container services.

* **Configuration**:
  ```yaml
  # config.yaml
  repo_path: "./knowledge"
  cache_path: "./.mdgraph/cache.db"
  db_type: "sqlite"
  ```
* **Performance**: Sub-millisecond BM25 keyword search via SQLite `fts5` and in-process Recursive CTE graph traversal.
* **In-Memory Mode**: Pass `:memory:` as `cache_path` for ephemeral or test workloads.

### Storage Option 2: PostgreSQL (Enterprise Multi-Tenant Backend)

Designed for distributed agent swarms, cloud deployments (Google Cloud Run, Kubernetes, AWS ECS), and large enterprise knowledge repositories.

* **Prerequisite**:
  ```bash
  pip install "mdgraph-ai[postgres]"
  ```
* **Configuration**:
  ```yaml
  # config.yaml
  repo_path: "./knowledge"
  db_type: "postgres"
  postgres_uri: "postgresql://postgres:password@localhost:5432/mdgraph"
  ```
  *(Or via environment variable: `export MDGRAPH_POSTGRES_URI="postgresql://..."`)*
* **Architecture Highlights**:
  - `JSONB` columns with GIN index for scalar filtering and tag intersection lookups.
  - Native PostgreSQL `tsvector` and `ts_rank` for full-text search.
  - High-concurrency Recursive CTEs for parallel agent graph traversal.

### Storage Backend Comparison

| Capability | SQLite (Default) | PostgreSQL (Enterprise) |
|---|---|---|
| **Setup Complexity** | Zero-config (single file) | Requires Postgres 14+ instance |
| **Concurrency** | Read-optimized (WAL mode) | Multi-tenant concurrent read/write |
| **Search Engine** | SQLite FTS5 + BM25 ranking | `tsvector` + `plainto_tsquery` |
| **Graph Traversal** | Recursive Common Table Expressions | Recursive CTEs + array cycle detection |
| **Metadata Filtering** | JSON extract functions | Native `JSONB` with containment operators (`?&`) |
| **Ideal For** | Local agents, CLI, CI/CD pipelines | Production cloud deployments & agent swarms |

### Disposable Cache & Fast Disaster Recovery

Because the Git repository is the single source of truth, **the database cache is completely disposable**. If your cache database is deleted, corrupted, or upgraded:

```bash
# Drop and rebuild the entire query cache from Git in sub-second time
mdgraph index --rebuild
```

---

## Multi-Tenant Workspace Scoping (`tenant_id`)

MdGraph includes native **multi-tenant workspace isolation**. Different teams, business units, or customer organizations can store, index, traverse, and query knowledge graphs within a shared repository and relational database without cross-tenant data leakage.

### Workspace Directory Layout
* **Default Workspace** (`default`): Stored directly in `concepts/{concept_id}.md` and root files (100% backwards-compatible with existing repositories).
* **Tenant Workspaces**: Stored in isolated subfolders under `tenants/{tenant_id}/concepts/{concept_id}.md`.

```text
knowledge/
├── index.md                       # Root index (default tenant)
├── concepts/                      # Default workspace concepts
│   ├── api_gateway.md
│   └── auth_service.md
└── tenants/                       # Multi-tenant workspaces
    ├── team_fintech/
    │   └── concepts/
    │       ├── payment_router.md  # fintech-isolated concept
    │       └── ledger.md
    └── team_security/
        └── concepts/
            └── payment_router.md  # Identical ID, complete tenant isolation
```

### Relational & CTE Isolation
* **Composite Primary Keys**: Both SQLite and PostgreSQL index tables utilize `PRIMARY KEY (tenant_id, id)`. Multiple tenants can define concepts with identical IDs without conflict.
* **Edge & CTE Boundary Enforcement**: All graph edges include `tenant_id`. Recursive CTE traversal queries (`WITH RECURSIVE`) enforce `edges.tenant_id = ?` across all anchor and recursive steps, guaranteeing that topological paths never jump between tenants.
* **BM25 Search Scoping**: Full-text queries are joined on `c.tenant_id = concepts_fts.tenant_id` to strictly isolate search hits.

### Multi-Tenant Usage Across Interfaces

The `tenant_id` is **completely optional** across all interfaces. When omitted:
* **Search & List**: Searches and lists concepts across **all workspaces** (or pass `--tenant <name>` to scope).
* **Traversals & Paths**: **Auto-detects** the root concept's tenant workspace automatically.
* **Ingestion & Compilation**: Persists to the `"default"` tenant workspace.

#### 1. CLI (`mdgraph`)
All commands accept `--tenant` (with `-t` and `-w` flags):
```bash
# Ingest with optional tenant subfolder routing
mdgraph ingest ./raw_docs/ --tenant team_fintech

# Compile into a specific tenant workspace (defaults to 'default' if omitted)
mdgraph compile ./specs/payments.md --tenant team_fintech --offline

# Search concepts (searches all workspaces if omitted or '--tenant all')
mdgraph query "payment router"                  # Searches across all workspaces
mdgraph query "payment router" --tenant team_fintech # Scoped to tenant

# Multi-hop traversal (auto-detects tenant if omitted)
mdgraph traverse payment_router                 # Auto-detects tenant workspace
mdgraph traverse payment_router -w team_fintech # Explicitly scoped

# Show concept (finds concept across workspaces if omitted)
mdgraph show payment_router

# List all active tenant workspaces
mdgraph tenants

# View statistics (global overview if omitted)
mdgraph stats                                   # Global multi-tenant stats
mdgraph stats --tenant team_fintech             # Scoped to tenant
```

#### 2. REST API (`mdgraph api`)
All endpoints accept an optional `tenant_id` body/query parameter or `X-Tenant-ID` HTTP header:
```bash
# Ingest document scoped to a tenant
curl -X POST "http://localhost:8080/api/v1/ingest/url" \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: team_fintech" \
  -d '{"url": "https://stripe.com/docs"}'

# Compile into a tenant workspace (defaults to 'default' if omitted)
curl -X POST "http://localhost:8080/api/v1/compile" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "# Payments\n\nDirects funds to [Ledger](./ledger.md).",
    "source_name": "payments.md",
    "tenant_id": "team_fintech",
    "offline": true,
    "save_to_repo": true
  }'

# Search concepts (returns all if omitted; isolated if X-Tenant-ID is set)
curl "http://localhost:8080/api/v1/concepts?query=funds"
curl "http://localhost:8080/api/v1/concepts?query=funds" -H "X-Tenant-ID: team_fintech"

# Graph traversal via REST (tenant optional, auto-detected if omitted)
curl "http://localhost:8080/api/v1/graph/traverse/payment_router"
curl "http://localhost:8080/api/v1/graph/paths?source=payments&target=ledger"

# List active tenant workspaces
curl "http://localhost:8080/api/v1/tenants"
```

#### 3. Agent MCP Tools (`mdgraph serve`)
All FastMCP tools accept an optional `tenant_id=None` parameter:
* `get_concept(node_id="payments")` *(searches all workspaces if `tenant_id` is None)*
* `read_concept_body(node_id="payments")`
* `search_knowledge(query="ledger")` *(searches all workspaces if `tenant_id` is None)*
* `search_knowledge(query="ledger", tenant_id="team_fintech")` *(isolated)*
* `traverse_graph(node_id="payments")` *(auto-detects tenant)*
* `find_path(source_id="payments", target_id="ledger")`
* `list_concepts()` *(lists all if `tenant_id` is None)*
* `list_tenants()`
* **Resources**: `okf://concepts/{node_id}`, `okf://tenants/{tenant_id}/concepts/{node_id}`, `okf://tenants`

---

## Cloud Deployment (Google Cloud Run & Docker)

MdGraph is container-ready and built for serverless deployment on **Google Cloud Run**, AWS ECS, or Kubernetes.

A production-optimized [`Dockerfile`](./Dockerfile) and [`.dockerignore`](./.dockerignore) are included in the repository root.

### 1. Build and Run Locally with Docker

```bash
# Build Docker image
docker build -t mdgraph:latest .

# Run REST API service on port 8080
docker run -p 8080:8080 mdgraph:latest

# Or run FastMCP Server over SSE on port 8000
docker run -p 8000:8000 mdgraph:latest mdgraph serve --transport sse --port 8000
```

### 2. Deploy to Google Cloud Run

Deploy the REST API microservice with automatic scaling down to zero:

```bash
# 1. Build and push image via Cloud Build (no local Docker daemon required)
export PROJECT_ID=$(gcloud config get-value project)
export REGION="us-central1"
export IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/mdgraph-docker/mdgraph:latest"

gcloud builds submit --tag $IMAGE_URI

# 2. Deploy REST API service
gcloud run deploy mdgraph-api \
  --image=$IMAGE_URI \
  --region=$REGION \
  --platform=managed \
  --allow-unauthenticated \
  --port=8080 \
  --memory=1Gi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=10 \
  --set-env-vars="MDGRAPH_DB_TYPE=sqlite,MDGRAPH_REPO_PATH=/app/knowledge"

# 3. Deploy FastMCP Server with long-lived SSE streaming & session affinity
gcloud run deploy mdgraph-mcp \
  --image=$IMAGE_URI \
  --command="mdgraph" \
  --args="serve,--transport,sse,--host,0.0.0.0,--port,8080" \
  --region=$REGION \
  --allow-unauthenticated \
  --port=8080 \
  --timeout=3600 \
  --session-affinity \
  --use-http2
```

> [!NOTE]
> For complete enterprise deployment documentation—including **Cloud SQL (PostgreSQL)**, **Cloud Storage (GCS) FUSE volume mounts**, and **GCP Secret Manager** integration—see the [`devops.md`](devops.md) guide.

---

## Configuration Reference

MdGraph can be configured using a YAML file (`mdgraph.yaml`, `config.yaml`, or `.mdgraph/config.yaml`), command-line flags, or environment variables.

### Configuration Hierarchy
1. Explicit CLI arguments (highest priority)
2. Environment variables (`MDGRAPH_*` and `PORT`)
3. YAML configuration file
4. Built-in defaults (lowest priority)

### Settings & Environment Variables

| Configuration Key | Environment Variable | Default | Description |
|---|---|---|---|
| `repo_path` | `MDGRAPH_REPO_PATH` | `./knowledge` | Path to Git repository containing OKF Markdown files. |
| `cache_path` | `MDGRAPH_CACHE_PATH` | `./.mdgraph/cache.db` | Path to SQLite query cache database file. |
| `db_type` | `MDGRAPH_DB_TYPE` | `sqlite` | Relational query cache engine: `'sqlite'` or `'postgres'`. |
| `postgres_uri` | `MDGRAPH_POSTGRES_URI` | `None` | PostgreSQL connection URI string when `db_type: postgres`. |
| `mcp_host` | `MDGRAPH_MCP_HOST` | `0.0.0.0` | Bind host for FastMCP SSE server. |
| `mcp_port` | `MDGRAPH_MCP_PORT` or `PORT` | `8000` | Port for FastMCP SSE server (Cloud Run auto-detects `PORT`). |
| `api_host` | `MDGRAPH_API_HOST` | `0.0.0.0` | Bind host for FastAPI REST service. |
| `api_port` | `MDGRAPH_API_PORT` or `PORT` | `8080` | Port for FastAPI REST service (Cloud Run auto-detects `PORT`). |
| `llm_model` | `MDGRAPH_LLM_MODEL` | `openai/gpt-4o-mini` | LiteLLM model string for concept compilation. |
| `llm_temperature` | — | `0.1` | Temperature for deterministic entity and link extraction. |
| `git_author_name` | — | `MdGraph Compiler` | Author name for automated Git commits. |
| `git_author_email` | — | `compiler@mdgraph.dev` | Author email for automated Git commits. |
| `auto_commit` | `MDGRAPH_AUTO_COMMIT` | `true` | Automatically commit concept modifications to Git. |

### Sample `mdgraph.yaml`

```yaml
# mdgraph.yaml
repo_path: "./knowledge"
cache_path: "./.mdgraph/cache.db"
db_type: "sqlite"

# FastMCP Server settings
mcp_host: "0.0.0.0"
mcp_port: 8000

# Standalone REST API settings
api_host: "0.0.0.0"
api_port: 8080

# Compiler LLM (OpenAI, Anthropic, Gemini, Ollama, Groq via LiteLLM)
llm_model: "openai/gpt-4o-mini"
llm_temperature: 0.1

# Automated Git commits
git_author_name: "MdGraph Compiler"
git_author_email: "compiler@mdgraph.dev"
auto_commit: true
```

---

## Open Knowledge Format (OKF v0.2) Specification

MdGraph natively conforms to Google's Open Knowledge Format v0.2. Concepts are plain Markdown files with YAML frontmatter:

```markdown
---
okf_version: "0.2"
type: Policy
title: Remote Work Hardware Allowance
description: Home office equipment stipend rules
tags: [hr, hardware, remote]
status: stable
stale_after: "2027-12-31"
generated:
  by: "system:mdgraph-init"
  at: "2026-10-17T00:00:00Z"
verified:
  - by: "human:hr_director"
    at: "2026-10-17T00:00:00Z"
    notes: "Approved for FY27"
sources:
  - "./raw_docs/hr_handbook_2026.pdf"
resource: "https://internal.company.com/policies/hardware"
---

# Remote Work Hardware Allowance

Employees receive a yearly stipend managed by 
the [IT Department](./it_department.md).

## Approved Purchases
All equipment must be sourced via the 
[Vendor Portal](./vendor_portal.md).
```

### OKF Schema Fields

| Field | Type | Description |
|---|---|---|
| `okf_version` | `str` | Specification version (`"0.2"`). |
| `type` | `str` | Semantic concept category (`Policy`, `System`, `Service`, `Entity`, `Tool`, `Article`). |
| `title` | `str` | Human-readable concept title. |
| `description` | `str` | High-level 1-line concept description. |
| `tags` | `list[str]` | Keyword tags for categorized indexing and intersections. |
| `status` | `str` | Lifecycle status: `stable`, `draft`, `deprecated`, `expired`, `archived`. |
| `stale_after` | `str` | ISO date after which concept is considered stale and needs re-attestation. |
| `generated` | `dict` | Provenance attribution: `{ "by": "agent:gpt-4o", "at": "..." }`. |
| `verified` | `list[dict]` | Trust attestations: `[{ "by": "human:reviewer", "at": "...", "notes": "..." }]`. |
| `sources` | `list[str]` | Upstream raw document file paths or URLs from which concept was compiled. |
| `resource` | `str` | Canonical URL or resource URI. |
| `tenant_id` | `str` | Workspace isolation identifier (`"default"` or tenant slug). |

### Future-Proofing & Extensibility
MdGraph's concept parser uses Pydantic with `model_config = ConfigDict(extra="allow")`. When future OKF versions (v0.3, v2+, v3) introduce new frontmatter fields, MdGraph absorbs and preserves them transparently without schema validation errors or data loss.

---

## Contributors

MdGraph is developed and maintained by:

<table>
  <tr>
    <td align="center">
      <a href="mailto:tony@firecodex.com">
        <img src="assets/tony_puthenveettil.png" width="100px;" alt="Tony Puthenveettil"/><br />
        <sub><b>Tony Puthenveettil</b></sub>
      </a>
      <br />
      <sub><a href="mailto:tony@firecodex.com">tony@firecodex.com</a></sub>
    </td>
  </tr>
</table>

---

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) for details.
