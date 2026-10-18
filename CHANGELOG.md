# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.1] - 2026-10-18

### Added
- **Multi-Tenant Workspace Scoping (`tenant_id`)**:
  - Full data model support in `OKFConcept` and `Edge` with YAML frontmatter serialization and path-based tenant inference (`tenants/{tenant_id}/...`).
  - Git storage subdirectories (`tenants/{tenant_id}/concepts/{concept_id}.md`) with 100% backward compatibility for single-tenant root concepts (`concepts/{concept_id}.md`).
  - Relational query caches (`SQLiteQueryCache`, `PostgresQueryCache`) with composite primary keys `(tenant_id, id)` and tenant-scoped indexes.
  - Isolated multi-hop graph traversals (`WITH RECURSIVE`) and shortest path algorithms preventing cross-tenant data leakage.
  - Tenant-scoped BM25 full-text search joining on unindexed tenant identifiers.
  - Multi-tenant CLI support: `--tenant` / `-t` / `-w` flag on `compile`, `index`, `query`, `traverse`, `show`, `stats`, plus new `mdgraph tenants` command.
  - Multi-tenant FastMCP server tools (`list_tenants()`, `tenant_id` parameters on all inspection, search, and traversal tools).
  - Multi-tenant FastAPI REST endpoints (`GET /api/v1/tenants`, `X-Tenant-ID` header and `tenant` query parameter resolution).
- **Standalone FastAPI REST API Service**:
  - Modular, high-performance async REST API with lifespan-managed repository and cache dependencies.
  - Ingestion endpoints (`POST /api/v1/ingest/url`, `POST /api/v1/ingest/file`, `POST /api/v1/ingest/text`).
  - Compilation endpoints (`POST /api/v1/compile/text`, `POST /api/v1/compile/file`).
  - One-shot pipeline endpoint (`POST /api/v1/pipeline`) and knowledge query endpoints (`GET /api/v1/concepts`, `GET /api/v1/concepts/{id}`).
  - Health checks (`/healthz`, `/readyz`).
- **Polymorphic Ingestion Engine**:
  - Ingestion support for public web URLs via `httpx` and `BeautifulSoup4`.
  - YouTube video transcript extraction via `youtube-transcript-api` and URL metadata resolution.
  - Polymorphic routing in `UniversalIngestor` accepting file paths, folder paths, web URLs, or YouTube links.
- **OKF v2.0 Specification & Forward Compatibility**:
  - Added support for Trust Signals (`trust_level`, `signature`, `verifier_id`), verification dates, and arbitrary dynamic future metadata namespaces.

## [0.1.0] - 2026-10-17

### Added
- **Google Open Knowledge Format (OKF v0.2)** implementation with Pydantic validation and serialization.
- **Universal Ingestion Pipeline** supporting PDF (`pypdf`, `docling`), HTML with structural table extraction, Markdown, and plain text.
- **Pluggable LLM Compiler** powered by `LiteLLM` supporting OpenAI, Anthropic, Gemini, and local Ollama models.
- **Deterministic Rule-Based Offline Compiler** for offline test and production setups without API keys.
- **Git-Backed Truth Storage Layer** ensuring Markdown files in Git serve as the single source of truth.
- **SQLite FTS5 Vectorless Relational Cache** with BM25 full-text keyword ranking.
- **Multi-Hop Graph Traversal** using native SQL Recursive Common Table Expressions (`WITH RECURSIVE`).
- **Shortest Path Topological Search** via SQL Recursive CTEs.
- **Optional Enterprise PostgreSQL Backend** with `JSONB`, `tsvector`, and recursive CTE support.
- **Incremental & Full Index Synchronization Worker** (`IndexSyncWorker`).
- **Native FastMCP Server** exposing `get_concept()`, `read_concept_body()`, `search_knowledge()`, `traverse_graph()`, `find_path()`, `list_concepts()`, `get_graph_stats()`, and `reindex()` over SSE and stdio transports.
- **Rich Interactive CLI (`mdgraph`)** with commands: `init`, `ingest`, `compile`, `index`, `query`, `traverse`, `show`, `stats`, `serve`.
- Comprehensive test suite with 23 passing tests across all modules.
