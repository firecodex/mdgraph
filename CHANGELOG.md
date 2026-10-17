# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

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
