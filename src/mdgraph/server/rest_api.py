"""Standalone FastAPI REST service for high-performance Ingestion and Compilation.

This service runs independently from the core CLI and FastMCP server. It exposes
asynchronous REST endpoints for ingesting heterogeneous documents (PDFs, HTML,
text, live web URLs, YouTube video transcripts) and compiling them into OKF concepts.
"""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

try:
    from fastapi import FastAPI, File, Form, Header, HTTPException, Query, UploadFile, status
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel, Field
except ImportError as e:
    raise ImportError(
        "FastAPI and its dependencies are required to run the mdgraph REST API service. "
        "Install them with: pip install 'mdgraph-ai[api]' or pip install fastapi python-multipart"
    ) from e

from mdgraph import __version__
from mdgraph.compiler.llm_compiler import LLMCompiler
from mdgraph.compiler.mock_compiler import RuleBasedCompiler
from mdgraph.config import MdGraphConfig, load_config
from mdgraph.indexer.sqlite_cache import SQLiteQueryCache
from mdgraph.indexer.sync import IndexSyncWorker
from mdgraph.ingestion.base import IngestionResult
from mdgraph.ingestion.html import HTMLParser
from mdgraph.ingestion.ingestor import UniversalIngestor
from mdgraph.models import OKFConcept
from mdgraph.storage.git_repo import GitRepo
from mdgraph.storage.okf_file import OKFFileManager

# ---------------------------------------------------------------------------
# Pydantic Schemas for Request & Response
# ---------------------------------------------------------------------------

class IngestURLRequest(BaseModel):
    url: str = Field(..., description="Website URL or YouTube video URL to ingest", examples=["https://docs.python.org/3/tutorial/"])
    dest: str | None = Field(default=None, description="Optional folder path to write normalized Markdown output")
    tenant_id: str | None = Field(default=None, description="Optional tenant identifier for destination directory routing")


class IngestPathRequest(BaseModel):
    path: str = Field(..., description="Path to local file or folder on server to ingest", examples=["./raw_documents/"])
    dest: str | None = Field(default=None, description="Optional destination directory for normalized markdown files")
    tenant_id: str | None = Field(default=None, description="Optional tenant identifier for destination directory routing")


class IngestTextRequest(BaseModel):
    text: str = Field(..., description="Raw text or HTML string to normalize into Markdown")
    title: str = Field(default="Document", description="Title for the document")
    format: str = Field(default="text", description="Input format hint ('html', 'markdown', or 'text')")
    dest: str | None = Field(default=None, description="Optional destination folder to save the markdown file")
    tenant_id: str | None = Field(default=None, description="Optional tenant identifier for destination directory routing")


class IngestGeneralRequest(BaseModel):
    source: str = Field(..., description="Web URL, YouTube URL, local file path, or local directory path")
    dest: str | None = Field(default=None, description="Optional destination directory for normalized markdown files")
    tenant_id: str | None = Field(default=None, description="Optional tenant identifier for destination directory routing")


class IngestedDocument(BaseModel):
    title: str
    source_path: str
    format: str
    markdown_content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    output_file: str | None = None


class IngestResponse(BaseModel):
    status: str = "ok"
    count: int
    documents: list[IngestedDocument]


class CompileRequest(BaseModel):
    content: str = Field(..., description="Markdown document text to compile into OKF concepts")
    source_name: str | None = Field(default=None, description="Originating document name or URL")
    tenant_id: str | None = Field(default=None, description="Workspace tenant identifier (defaults to 'default')")
    model: str | None = Field(default=None, description="LiteLLM model string (e.g., 'openai/gpt-4o-mini', 'ollama/llama3.2')")
    offline: bool = Field(default=False, description="Use deterministic rule-based compiler without calling external LLM")
    save_to_repo: bool = Field(default=False, description="Whether to write compiled concepts into the Git repository")
    sync_index: bool = Field(default=True, description="Whether to update query cache after saving to Git")


class CompileFileRequest(BaseModel):
    file_path: str = Field(..., description="Path to markdown file on the server to compile")
    tenant_id: str | None = Field(default=None, description="Workspace tenant identifier (defaults to 'default')")
    model: str | None = Field(default=None, description="LiteLLM model string")
    offline: bool = Field(default=False, description="Use deterministic rule-based compiler")
    save_to_repo: bool = Field(default=False, description="Whether to write compiled concepts into the Git repository")
    sync_index: bool = Field(default=True, description="Whether to update query cache after saving to Git")


class ConceptSummary(BaseModel):
    id: str
    tenant_id: str = Field(default="default", description="Tenant workspace identifier")
    title: str
    type: str
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    outgoing_links: list[str] = Field(default_factory=list)
    body: str
    file_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CompileResponse(BaseModel):
    status: str = "ok"
    count: int
    concepts: list[ConceptSummary]
    saved_to_repo: bool
    repo_path: str | None = None
    commit_hash: str | None = None


class PipelineRequest(BaseModel):
    source: str | None = Field(default=None, description="URL (website or YouTube) or local file/folder path to ingest")
    content: str | None = Field(default=None, description="Direct markdown or text content (if source is omitted)")
    source_name: str | None = Field(default=None, description="Document title/identifier for direct content")
    tenant_id: str | None = Field(default=None, description="Workspace tenant identifier (defaults to 'default')")
    model: str | None = Field(default=None, description="LiteLLM model override")
    offline: bool = Field(default=False, description="Use deterministic rule-based compiler")
    save_to_repo: bool = Field(default=True, description="Persist compiled concepts into Git repository")
    sync_index: bool = Field(default=True, description="Synchronize relational query cache after saving to Git")


class PipelineResponse(BaseModel):
    status: str = "ok"
    ingested_count: int
    ingested_documents: list[IngestedDocument]
    concept_count: int
    concepts: list[ConceptSummary]
    saved_to_repo: bool
    commit_hash: str | None = None


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "mdgraph-rest-api"
    version: str
    repo_path: str
    cache_path: str
    total_concepts: int
    head_commit: str | None = None
    tenants: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def _sanitize_slug(title: str) -> str:
    """Sanitize title into a safe filename slug."""
    slug = re.sub(r"[^a-zA-Z0-9_\-]", "_", title.lower().strip())
    slug = re.sub(r"_+", "_", slug).strip("_")[:50]
    return slug or "document"


def _write_result_to_dest(res: IngestionResult, dest_dir: Path) -> Path:
    """Write normalized result markdown to destination folder."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    slug = _sanitize_slug(res.title)
    out_file = dest_dir / f"{slug}.md"
    out_file.write_text(res.markdown_content, encoding="utf-8")
    return out_file


def _concept_to_summary(concept: OKFConcept) -> ConceptSummary:
    """Convert an OKFConcept domain model to a clean ConceptSummary DTO."""
    return ConceptSummary(
        id=concept.id,
        tenant_id=concept.tenant_id,
        title=concept.title,
        type=concept.type,
        description=concept.description,
        tags=concept.tags,
        outgoing_links=concept.outgoing_links,
        body=concept.body,
        file_path=concept.file_path,
        metadata=concept.metadata,
    )


# ---------------------------------------------------------------------------
# FastAPI Application Factory
# ---------------------------------------------------------------------------

def create_rest_api(
    config: MdGraphConfig | None = None,
    repo: GitRepo | None = None,
    cache: SQLiteQueryCache | None = None,
) -> FastAPI:
    """Create and configure the standalone FastAPI REST service.

    Args:
        config: Optional MdGraph runtime configuration.
        repo: Optional initialized GitRepo instance.
        cache: Optional initialized SQLiteQueryCache instance.

    Returns:
        Configured FastAPI application ready to run with Uvicorn.
    """
    cfg = config or load_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup: initialize state components
        r = repo or GitRepo(cfg.repo_path)
        c = cache or SQLiteQueryCache(cfg.cache_path)
        app.state.config = cfg
        app.state.repo = r
        app.state.cache = c
        app.state.file_manager = OKFFileManager(r)
        app.state.ingestor = UniversalIngestor()
        app.state.rule_compiler = RuleBasedCompiler()
        app.state.llm_compiler = LLMCompiler(
            model=cfg.llm_model,
            temperature=cfg.llm_temperature,
        )
        yield
        # Shutdown cleanup (if needed)

    app = FastAPI(
        title="MdGraph Ingestion & Compilation API",
        description=(
            "Standalone high-performance REST service for ingesting heterogeneous documents "
            "(PDF, HTML, text, Web URLs, YouTube video transcripts) and compiling them into "
            "vectorless Open Knowledge Format (OKF) concepts backed by Git and SQLite/PostgreSQL."
        ),
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Enable CORS for external agents and browser clients
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -----------------------------------------------------------------------
    # Health & Meta Endpoints
    # -----------------------------------------------------------------------

    @app.get("/", tags=["Health"])
    @app.get("/health", tags=["Health"])
    @app.get("/api/v1/health", response_model=HealthResponse, tags=["Health"])
    async def get_health() -> HealthResponse:
        """Get health status, configured paths, active tenants, and knowledge base metrics."""
        r: GitRepo = app.state.repo
        c: SQLiteQueryCache = app.state.cache

        def _stats():
            stats_data = c.get_stats()
            head = r.get_head_commit()
            return stats_data.total_concepts, head, stats_data.tenants

        total, head, tenants = await asyncio.to_thread(_stats)
        return HealthResponse(
            status="ok",
            service="mdgraph-rest-api",
            version=__version__,
            repo_path=cfg.repo_path,
            cache_path=cfg.cache_path,
            total_concepts=total,
            head_commit=head,
            tenants=tenants,
        )

    @app.get("/api/v1/tenants", tags=["Tenants"])
    async def list_tenants() -> list[str]:
        """List all active tenant workspace identifiers across the repository."""
        c: SQLiteQueryCache = app.state.cache
        return await asyncio.to_thread(c.list_tenants)

    # -----------------------------------------------------------------------
    # Ingestion Endpoints
    # -----------------------------------------------------------------------

    @app.post("/api/v1/ingest", response_model=IngestResponse, tags=["Ingestion"])
    async def ingest_general(
        req: IngestGeneralRequest,
        x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    ) -> IngestResponse:
        """Polymorphic ingest: accepts website URL, YouTube URL, local file, or local folder."""
        ingestor: UniversalIngestor = app.state.ingestor
        eff_tenant = req.tenant_id or x_tenant_id

        def _do_ingest():
            results = ingestor.ingest(req.source)
            docs = []
            if req.dest:
                dest_dir = Path(req.dest).resolve()
            elif eff_tenant:
                dest_dir = (Path.cwd() / "normalized" / eff_tenant).resolve()
            else:
                dest_dir = None

            for res in results:
                out_path = _write_result_to_dest(res, dest_dir) if dest_dir else None
                docs.append(IngestedDocument(
                    title=res.title,
                    source_path=res.source_path,
                    format=res.metadata.get("format", "unknown"),
                    markdown_content=res.markdown_content,
                    metadata=res.metadata,
                    output_file=str(out_path) if out_path else None,
                ))
            return docs

        try:
            documents = await asyncio.to_thread(_do_ingest)
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

        return IngestResponse(count=len(documents), documents=documents)

    @app.post("/api/v1/ingest/url", response_model=IngestResponse, tags=["Ingestion"])
    async def ingest_url(
        req: IngestURLRequest,
        x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    ) -> IngestResponse:
        """Ingest a live website URL or YouTube video URL into normalized Markdown."""
        ingestor: UniversalIngestor = app.state.ingestor
        eff_tenant = req.tenant_id or x_tenant_id

        def _do_url_ingest():
            res = ingestor.ingest_url(req.url)
            if req.dest:
                dest_dir = Path(req.dest).resolve()
            elif eff_tenant:
                dest_dir = (Path.cwd() / "normalized" / eff_tenant).resolve()
            else:
                dest_dir = None
            out_path = _write_result_to_dest(res, dest_dir) if dest_dir else None
            return [IngestedDocument(
                title=res.title,
                source_path=res.source_path,
                format=res.metadata.get("format", "unknown"),
                markdown_content=res.markdown_content,
                metadata=res.metadata,
                output_file=str(out_path) if out_path else None,
            )]

        try:
            documents = await asyncio.to_thread(_do_url_ingest)
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

        return IngestResponse(count=len(documents), documents=documents)

    @app.post("/api/v1/ingest/file", response_model=IngestResponse, tags=["Ingestion"])
    async def ingest_uploaded_file(
        file: Annotated[UploadFile, File(...)],
        dest: Annotated[str | None, Form()] = None,
        tenant: Annotated[str | None, Form()] = None,
        x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    ) -> IngestResponse:
        """Upload a file (PDF, HTML, text, markdown) to parse into normalized Markdown."""
        ingestor: UniversalIngestor = app.state.ingestor
        filename = file.filename or "uploaded_file"
        suffix = Path(filename).suffix or ".txt"
        eff_tenant = tenant or x_tenant_id

        # Save to temporary file safely
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = Path(tmp.name)
            content = await file.read()
            tmp_path.write_bytes(content)

        def _do_parse():
            try:
                res = ingestor.ingest_file(tmp_path)
                res.source_path = filename
                if res.title == tmp_path.stem.replace("_", " ").title():
                    res.title = Path(filename).stem.replace("_", " ").title()

                if dest:
                    dest_dir = Path(dest).resolve()
                elif eff_tenant:
                    dest_dir = (Path.cwd() / "normalized" / eff_tenant).resolve()
                else:
                    dest_dir = None

                out_path = _write_result_to_dest(res, dest_dir) if dest_dir else None
                return [IngestedDocument(
                    title=res.title,
                    source_path=res.source_path,
                    format=res.metadata.get("format", "unknown"),
                    markdown_content=res.markdown_content,
                    metadata=res.metadata,
                    output_file=str(out_path) if out_path else None,
                )]
            finally:
                if tmp_path.exists():
                    os.unlink(tmp_path)

        try:
            documents = await asyncio.to_thread(_do_parse)
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

        return IngestResponse(count=len(documents), documents=documents)

    @app.post("/api/v1/ingest/text", response_model=IngestResponse, tags=["Ingestion"])
    async def ingest_raw_text(
        req: IngestTextRequest,
        x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    ) -> IngestResponse:
        """Directly normalize raw text or HTML without an uploaded file."""
        eff_tenant = req.tenant_id or x_tenant_id

        def _do_text_ingest():
            fmt = req.format.lower().strip()
            if fmt == "html" or "<html" in req.text.lower():
                parser = HTMLParser()
                res = parser.parse_string(req.text, source_path=req.title)
            else:
                res = IngestionResult(
                    source_path=req.title,
                    title=req.title,
                    markdown_content=req.text,
                    metadata={"format": fmt or "text"},
                )

            if req.dest:
                dest_dir = Path(req.dest).resolve()
            elif eff_tenant:
                dest_dir = (Path.cwd() / "normalized" / eff_tenant).resolve()
            else:
                dest_dir = None

            out_path = _write_result_to_dest(res, dest_dir) if dest_dir else None
            return [IngestedDocument(
                title=res.title,
                source_path=res.source_path,
                format=res.metadata.get("format", "text"),
                markdown_content=res.markdown_content,
                metadata=res.metadata,
                output_file=str(out_path) if out_path else None,
            )]

        try:
            documents = await asyncio.to_thread(_do_text_ingest)
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

        return IngestResponse(count=len(documents), documents=documents)

    # -----------------------------------------------------------------------
    # Compilation Endpoints
    # -----------------------------------------------------------------------

    @app.post("/api/v1/compile", response_model=CompileResponse, tags=["Compilation"])
    async def compile_text(
        req: CompileRequest,
        x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    ) -> CompileResponse:
        """Compile Markdown content into interlinked OKF concepts scoped to a tenant."""
        r: GitRepo = app.state.repo
        c: SQLiteQueryCache = app.state.cache
        fm: OKFFileManager = app.state.file_manager
        tenant_id = req.tenant_id or x_tenant_id or "default"

        def _do_compile():
            # Select compiler
            if req.offline:
                compiler = app.state.rule_compiler
            elif req.model:
                compiler = LLMCompiler(model=req.model, temperature=cfg.llm_temperature)
            else:
                compiler = app.state.llm_compiler

            concepts: list[OKFConcept] = compiler.compile(
                req.content,
                source_name=req.source_name,
                tenant_id=tenant_id,
            )

            commit_hash = None
            if req.save_to_repo:
                for concept in concepts:
                    fm.save_concept(concept)
                commit_hash = r.get_head_commit()
                if req.sync_index:
                    IndexSyncWorker(r, c).sync(tenant_id=tenant_id)

            summaries = [_concept_to_summary(cp) for cp in concepts]
            return summaries, commit_hash

        try:
            summaries, commit_hash = await asyncio.to_thread(_do_compile)
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e

        return CompileResponse(
            count=len(summaries),
            concepts=summaries,
            saved_to_repo=req.save_to_repo,
            repo_path=cfg.repo_path if req.save_to_repo else None,
            commit_hash=commit_hash,
        )

    @app.post("/api/v1/compile/file", response_model=CompileResponse, tags=["Compilation"])
    async def compile_file(
        req: CompileFileRequest,
        x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    ) -> CompileResponse:
        """Compile a file on the server filesystem into OKF concepts scoped to a tenant."""
        p = Path(req.file_path).resolve()
        if not p.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"File not found: {req.file_path}")

        try:
            content = p.read_text(encoding="utf-8")
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to read file: {e}") from e

        compile_req = CompileRequest(
            content=content,
            source_name=p.name,
            tenant_id=req.tenant_id or x_tenant_id or "default",
            model=req.model,
            offline=req.offline,
            save_to_repo=req.save_to_repo,
            sync_index=req.sync_index,
        )
        return await compile_text(compile_req, x_tenant_id=x_tenant_id)

    # -----------------------------------------------------------------------
    # End-to-End Pipeline Endpoint
    # -----------------------------------------------------------------------

    @app.post("/api/v1/pipeline", response_model=PipelineResponse, tags=["Pipeline"])
    async def run_pipeline(
        req: PipelineRequest,
        x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    ) -> PipelineResponse:
        """One-shot ingestion and compilation scoped to a tenant."""
        ingestor: UniversalIngestor = app.state.ingestor
        r: GitRepo = app.state.repo
        c: SQLiteQueryCache = app.state.cache
        fm: OKFFileManager = app.state.file_manager
        tenant_id = req.tenant_id or x_tenant_id or "default"

        def _do_pipeline():
            # 1. Ingest
            if req.source:
                ingested_results = ingestor.ingest(req.source)
            elif req.content:
                ingested_results = [IngestionResult(
                    source_path=req.source_name or "direct_input",
                    title=req.source_name or "Direct Input",
                    markdown_content=req.content,
                    metadata={"format": "markdown"},
                )]
            else:
                raise ValueError("Must provide either 'source' (URL or file/folder) or 'content' string")

            # 2. Select compiler
            if req.offline:
                compiler = app.state.rule_compiler
            elif req.model:
                compiler = LLMCompiler(model=req.model, temperature=cfg.llm_temperature)
            else:
                compiler = app.state.llm_compiler

            # 3. Compile all ingested documents
            all_concepts: list[OKFConcept] = []
            ingested_docs: list[IngestedDocument] = []
            for res in ingested_results:
                ingested_docs.append(IngestedDocument(
                    title=res.title,
                    source_path=res.source_path,
                    format=res.metadata.get("format", "unknown"),
                    markdown_content=res.markdown_content,
                    metadata=res.metadata,
                ))
                cps = compiler.compile(res.markdown_content, source_name=res.title, tenant_id=tenant_id)
                all_concepts.extend(cps)

            # 4. Save to Git repository & sync index if requested
            commit_hash = None
            if req.save_to_repo:
                for cp in all_concepts:
                    fm.save_concept(cp)
                commit_hash = r.get_head_commit()
                if req.sync_index:
                    IndexSyncWorker(r, c).sync(tenant_id=tenant_id)

            summaries = [_concept_to_summary(cp) for cp in all_concepts]
            return ingested_docs, summaries, commit_hash

        try:
            ingested_docs, summaries, commit_hash = await asyncio.to_thread(_do_pipeline)
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

        return PipelineResponse(
            ingested_count=len(ingested_docs),
            ingested_documents=ingested_docs,
            concept_count=len(summaries),
            concepts=summaries,
            saved_to_repo=req.save_to_repo,
            commit_hash=commit_hash,
        )

    # -----------------------------------------------------------------------
    # Concept Read Endpoints (Optional Convenience)
    # -----------------------------------------------------------------------

    @app.get("/api/v1/concepts", tags=["Concepts"])
    async def list_concepts(
        query: Annotated[str | None, Query(description="BM25 search term")] = None,
        concept_type: Annotated[str | None, Query(description="Filter by concept type")] = None,
        tag: Annotated[str | None, Query(description="Filter by tag")] = None,
        tenant: Annotated[str | None, Query(description="Filter by tenant ID (omitted or 'all' for all tenants)")] = None,
        x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
        limit: Annotated[int, Query(le=100)] = 20,
    ) -> list[dict[str, Any]]:
        """List or search concepts from relational query cache with optional multi-tenant isolation."""
        cache_backend: SQLiteQueryCache = app.state.cache
        raw_tenant = tenant if tenant is not None else x_tenant_id
        eff_tenant: str | None = None if (raw_tenant is None or raw_tenant.lower() == "all") else raw_tenant

        def _do_search():
            if query:
                tags_list = [tag] if tag else None
                s_results = cache_backend.search(
                    query=query,
                    tags=tags_list,
                    concept_type=concept_type,
                    tenant_id=eff_tenant,
                    limit=limit,
                )
                return [r.model_dump() for r in s_results]
            return cache_backend.list_concepts(
                concept_type=concept_type,
                tag=tag,
                tenant_id=eff_tenant,
                limit=limit,
            )

        return await asyncio.to_thread(_do_search)

    @app.get("/api/v1/concepts/{node_id}", tags=["Concepts"])
    async def get_concept(
        node_id: str,
        tenant: Annotated[str | None, Query(description="Optional tenant ID")] = None,
        x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    ) -> dict[str, Any]:
        """Get full concept details and markdown body from the Git repository."""
        fm: OKFFileManager = app.state.file_manager
        eff_tenant = tenant or x_tenant_id

        def _do_get():
            try:
                cp = fm.load_by_id(node_id, tenant_id=eff_tenant)
                return _concept_to_summary(cp).model_dump()
            except Exception as e:
                scope = f" in tenant '{eff_tenant}'" if eff_tenant else ""
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Concept '{node_id}' not found{scope}: {e}") from e

        return await asyncio.to_thread(_do_get)

    # -----------------------------------------------------------------------
    # Graph Exploration Endpoints
    # -----------------------------------------------------------------------

    @app.get("/api/v1/graph/traverse/{node_id}", tags=["Graph"])
    async def traverse_graph(
        node_id: str,
        depth: Annotated[int, Query(ge=1, le=10, description="Maximum traversal hops")] = 2,
        direction: Annotated[str, Query(description="Traversal direction ('out', 'in', 'both')")] = "out",
        tenant: Annotated[str | None, Query(description="Optional tenant workspace")] = None,
        x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    ) -> dict[str, Any]:
        """Execute exact multi-hop topological traversal via SQL Recursive CTE."""
        c: SQLiteQueryCache = app.state.cache
        eff_tenant = tenant or x_tenant_id

        def _do_traverse():
            res = c.traverse(node_id=node_id, max_depth=depth, direction=direction, tenant_id=eff_tenant)
            return res.model_dump()

        return await asyncio.to_thread(_do_traverse)

    @app.get("/api/v1/graph/paths", tags=["Graph"])
    async def find_shortest_path(
        source: Annotated[str, Query(description="Starting concept ID")],
        target: Annotated[str, Query(description="Destination concept ID")],
        depth: Annotated[int, Query(ge=1, le=15, description="Maximum hops to explore")] = 5,
        tenant: Annotated[str | None, Query(description="Optional tenant workspace")] = None,
        x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    ) -> dict[str, Any]:
        """Find the shortest topological path between two concepts via SQL Recursive CTE."""
        c: SQLiteQueryCache = app.state.cache
        eff_tenant = tenant or x_tenant_id

        def _do_find_path():
            path = c.find_path(source, target, max_depth=depth, tenant_id=eff_tenant)
            if path:
                return {
                    "found": True,
                    "source": source,
                    "target": target,
                    "tenant_id": eff_tenant or "auto",
                    "path": path,
                    "length": len(path) - 1,
                }
            return {
                "found": False,
                "source": source,
                "target": target,
                "tenant_id": eff_tenant or "auto",
                "path": [],
                "message": f"No path exists within max_depth {depth}.",
            }

        return await asyncio.to_thread(_do_find_path)

    @app.get("/api/v1/graph/stats", tags=["Graph"])
    async def get_graph_stats(
        tenant: Annotated[str | None, Query(description="Optional tenant workspace")] = None,
        x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    ) -> dict[str, Any]:
        """Get summary statistics of the indexed knowledge graph (optionally scoped to a tenant)."""
        c: SQLiteQueryCache = app.state.cache
        r: GitRepo = app.state.repo
        eff_tenant = tenant or x_tenant_id

        def _do_stats():
            st = c.get_stats(tenant_id=eff_tenant)
            d = st.model_dump()
            d["git_head"] = r.get_head_commit()
            return d

        return await asyncio.to_thread(_do_stats)

    return app


# Default ASGI application instance for `uvicorn mdgraph.server.rest_api:app`
app = create_rest_api()
