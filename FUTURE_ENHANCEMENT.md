Viewed postgres_cache.py:1-100

To take **MdGraph** from its current solid architecture to a high-scale, enterprise-grade production deployment, there are several key architectural enhancements and performance improvements to consider across storage, database, compilation, security, and operations:

---

### 1. Concurrency & Git Storage Optimization

| Area | Current Behavior | Enterprise Enhancement |
|---|---|---|
| **Git Write Contention** | Synchronous `git commit` via subprocess calls per concept write. | **Git Index Lock Contention**: Concurrent parallel writes will hit `.git/index.lock`. Implement an **In-Memory Write Queue / Batch Commit Worker** that aggregates concept writes and commits every $N$ seconds or $M$ changes in a single transaction. |
| **Git Backend Performance** | Spawns OS subprocesses (`subprocess.run(["git", ...])`). | For high-frequency reads/writes, adopt **`pygit2` / `libgit2`** (C bindings) to interact with the Git object database in-process without OS process fork overhead. |
| **Distributed Multi-Node Sync** | Local Git directory. | Implement an automated **background Git Sync worker** (`git fetch`/`pull`/`push` with exponential backoff) or webhook listener to synchronize changes across multiple stateless API/MCP nodes and a central Git remote (GitHub Enterprise, GitLab, or AWS CodeCommit). |
| **Scale for 100,000+ Concepts** | Standard directory scan with `os.walk`. | Implement Git tree hash diffing (`git diff-tree`) instead of filesystem scans, and use **Git LFS** or S3 pointers for raw binary attachments (large PDFs, video transcripts). |

---

### 2. Database & Relational Cache Scaling

| Area | Current Behavior | Enterprise Enhancement |
|---|---|---|
| **PostgreSQL Connection Management** | Single direct connection via `psycopg.connect`. | Replace single connection with **`psycopg_pool.ConnectionPool`** (configurable `min_size`, `max_size`, `timeout`) to support high-concurrency API and MCP traffic. |
| **Read/Write Splitting** | All queries target the primary database. | Support separate **Primary (Write)** and **Replica (Read)** DSNs so Recursive CTE traversals and BM25 searches offload to read replicas. |
| **Hybrid Reranking** | SQLite FTS5 / Postgres `tsvector` BM25 keyword matching. | Add an optional **Cross-Encoder Reranker** (e.g., Cohere Rerank, FlashRank, or BGE-Reranker) on top of the BM25 candidate set ($top\text{-}50 \to top\text{-}5$) to boost semantic ranking while retaining vectorless graph determinism. |
| **Graph Partitioning** | Global `edges` table. | For millions of edges, add PostgreSQL **declarative table partitioning** by `label` or `source_id` prefix. |

---

### 3. Asynchronous Ingestion & Compiler Scalability

| Area | Current Behavior | Enterprise Enhancement |
|---|---|---|
| **Batch Ingestion Pipeline** | In-process execution with `asyncio.to_thread`. | For bulk ingestion (thousands of PDFs/URLs), integrate a distributed task queue (**Celery**, **ARQ**, or **Temporal**) backed by Redis/RabbitMQ with durable job tracking, retries, and dead-letter queues. |
| **LLM Quota & Rate Limiting** | Direct LiteLLM calls with fallback to rules. | Implement a **Token Bucket / Concurrency Semaphore** to respect model provider rate limits (RPM/TPM) and handle HTTP 429 backoff with jitter across concurrent requests. |
| **Document Chunking for Massive Documents** | Whole-document extraction into single LLM prompt. | Add sliding-window hierarchical decomposition for 500+ page documents with chapter-level and section-level concept extraction. |

---

### 4. Security, Governance & Access Control

| Area | Current Behavior | Enterprise Enhancement |
|---|---|---|
| **Authentication & Authorization** | Open endpoints (development mode). | Add **API Key & JWT / OAuth2 (OIDC)** authentication middleware to both FastAPI and FastMCP endpoints. |
| **Row-Level & Concept-Level RBAC** | All concepts visible to all callers. | Leverage OKF frontmatter metadata (`tags`, `confidentiality`, `teams`) to enforce **Attribute-Based Access Control (ABAC)** in PostgreSQL queries (e.g., users only query concepts matching their permitted department tags). |
| **Adversarial Prompt Injection Defense** | Standard LLM prompt format. | Ingested web pages and YouTube transcripts may contain prompt injection attempts. Add pre-compiler sanitization and use structured tool-calling / JSON schema outputs rather than free-form text completions. |
| **Audit Logging** | Local Git commit author strings. | Enforce cryptographically signed Git commits (**GPG / SSH signing**) to verify concept provenance in compliance-regulated environments (SOC2, HIPAA). |

---

### 5. Multi-Tenancy & Workspace Isolation

| Area | Current Behavior | Enterprise Enhancement |
|---|---|---|
| **Workspace Scoping** | Single knowledge base path per instance. | Add multi-tenant support: `tenant_id` or `workspace_id` column partitioning in PostgreSQL, and separate Git branches or directories (`tenants/{org_id}/concepts`) for full tenant isolation. |

---

### 6. Observability & Telemetry

| Area | Current Behavior | Enterprise Enhancement |
|---|---|---|
| **Distributed Tracing** | Console output with `rich`. | Integrate **OpenTelemetry (OTel)** tracing across the entire pipeline: trace an incoming agent query through FastMCP $\to$ Recursive CTE in PostgreSQL $\to$ Git raw read $\to$ response. |
| **Metrics Collection** | Basic `cache.get_stats()`. | Expose standard Prometheus metrics endpoint (`/metrics`): `mdgraph_queries_total`, `mdgraph_cte_latency_seconds`, `mdgraph_compile_tokens_total`, `mdgraph_git_commit_latency_seconds`. |
| **Structured Logging** | Standard Python logging / Rich print. | Switch to structured JSON logging (`structlog` or `loguru`) for automated parsing by Datadog, Splunk, or AWS CloudWatch. |

---

### Recommended Implementation Roadmap

1. **Phase 1 (Immediate - High ROI)**:
   - Add PostgreSQL connection pooling (`psycopg_pool`).
   - Add API Key / Bearer Token authentication to FastAPI and MCP endpoints.
   - Implement an async batch commit queue for Git writes to eliminate `.git/index.lock` contention under parallel writes.

2. **Phase 2 (Scale & Reliability)**:
   - Add background Git remote sync (`push`/`pull` worker).
   - Implement OpenTelemetry tracing and Prometheus metrics (`/metrics`).
   - Add Token Bucket rate limiter for LiteLLM calls.

3. **Phase 3 (Enterprise Governance & Multi-Tenancy)**:
   - Implement Tag-based RBAC/ABAC query filtering.
   - Multi-tenant workspace scoping (`tenant_id`).
   - GPG commit signing for automated Git audit trails.