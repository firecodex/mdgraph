"""Command Line Interface (CLI) for MdGraph."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from mdgraph import __version__
from mdgraph.compiler.llm_compiler import LLMCompiler
from mdgraph.compiler.mock_compiler import RuleBasedCompiler
from mdgraph.config import load_config
from mdgraph.indexer.sqlite_cache import SQLiteQueryCache
from mdgraph.indexer.sync import IndexSyncWorker
from mdgraph.ingestion import UniversalIngestor, is_youtube_url
from mdgraph.server.mcp_server import create_mcp_server
from mdgraph.storage.git_repo import GitRepo
from mdgraph.storage.okf_file import OKFFileManager

console = Console()


def print_banner():
    banner = (
        "[bold yellow]MdGraph[/bold yellow] [dim]v" + __version__ + "[/dim]\n"
        "[dim]Vectorless Open Knowledge Format (OKF) Context Engine for Agentic AI[/dim]"
    )
    console.print(Panel(banner, border_style="yellow"))


@click.group(invoke_without_command=True)
@click.option("--version", is_flag=True, help="Show MdGraph version.")
@click.pass_context
def main(ctx: click.Context, version: bool):
    """MdGraph: Vectorless Open Knowledge Format (OKF) storage engine."""
    if version:
        console.print(f"[bold yellow]MdGraph[/bold yellow] version {__version__}")
        sys.exit(0)
    if ctx.invoked_subcommand is None:
        print_banner()
        console.print(ctx.get_help())


@main.command()
@click.argument("path", default="./knowledge", type=click.Path())
def init(path: str):
    """Initialize a new Git-backed OKF repository and directory structure."""
    repo_dir = Path(path).resolve()
    console.print(f"[yellow]Initializing OKF repository at:[/yellow] {repo_dir}")

    repo = GitRepo(repo_dir)
    concepts_dir = repo_dir / "concepts"
    concepts_dir.mkdir(parents=True, exist_ok=True)

    # Create sample concept if empty
    sample_file = concepts_dir / "example_concept.md"
    if not sample_file.exists():
        sample_content = (
            "---\n"
            "okf_version: \"0.2\"\n"
            "type: Concept\n"
            "title: Example OKF Concept\n"
            "description: An introductory node in the MdGraph Open Knowledge Format.\n"
            "tags: [example, getting-started]\n"
            "status: stable\n"
            "generated:\n"
            "  by: \"system:mdgraph-init\"\n"
            "  at: \"2026-10-17T00:00:00Z\"\n"
            "verified:\n"
            "  - by: \"human:admin\"\n"
            "    at: \"2026-10-17T00:00:00Z\"\n"
            "    notes: \"Initial baseline concept\"\n"
            "---\n\n"
            "# Example OKF Concept\n\n"
            "This is a sample concept. You can link to other concepts using standard Markdown links:\n"
            "For example, check the root [Knowledge Index](../index.md).\n"
        )
        sample_file.write_text(sample_content, encoding="utf-8")
        repo.commit("Add initial example concept")

    console.print(f"[bold green]✓[/bold green] OKF Git repository initialized at {repo_dir}")
    console.print("[dim]Run 'mdgraph index' to build the initial query cache.[/dim]")


@main.command()
@click.argument("source", type=str)
@click.option("--dest", "-d", default=None, help="Destination directory for normalized markdown files.")
@click.option("--tenant", "-t", "-w", default=None, help="Optional workspace tenant identifier.")
def ingest(source: str, dest: str | None, tenant: str | None):
    """Ingest documents (PDF, HTML, text, website URL, or YouTube video) and normalize into Markdown."""
    source_str = source.strip()
    is_url = source_str.startswith(("http://", "https://", "www.")) or is_youtube_url(source_str)

    if not is_url:
        src_path = Path(source).resolve()
        if not src_path.exists():
            raise click.BadParameter(f"Source path does not exist: {source}", param_hint="'source'")
        if dest:
            target_dir = Path(dest).resolve()
        elif tenant:
            target_dir = (Path.cwd() / "normalized" / tenant).resolve()
        else:
            target_dir = src_path.parent / "normalized"
    else:
        src_path = None
        if dest:
            target_dir = Path(dest).resolve()
        elif tenant:
            target_dir = (Path.cwd() / "normalized" / tenant).resolve()
        else:
            target_dir = Path.cwd() / "normalized"

    target_dir.mkdir(parents=True, exist_ok=True)
    ingestor = UniversalIngestor()

    results = []
    if is_url:
        console.print(f"[yellow]Ingesting URL:[/yellow] {source_str}")
        try:
            results = ingestor.ingest(source_str)
        except Exception as e:
            console.print(f"[bold red]✗ Failed to ingest URL:[/bold red] {e}")
            sys.exit(1)
    elif src_path and src_path.is_file():
        console.print(f"[yellow]Ingesting file:[/yellow] {src_path.name}")
        results.append(ingestor.ingest_file(src_path))
    elif src_path and src_path.is_dir():
        console.print(f"[yellow]Ingesting directory:[/yellow] {src_path}")
        results.extend(ingestor.ingest_directory(src_path))

    title_suffix = f" [tenant: {tenant}]" if tenant else ""
    table = Table(title=f"Ingested Documents{title_suffix}", border_style="yellow")
    table.add_column("Title", style="bold")
    table.add_column("Source Format", style="dim")
    table.add_column("Output File", style="green")

    for res in results:
        slug = re.sub(r"[^a-zA-Z0-9_\-]", "_", res.title.lower().strip())
        slug = re.sub(r"_+", "_", slug).strip("_")[:50]
        if not slug:
            slug = "document"
        out_file = target_dir / f"{slug}.md"
        out_file.write_text(res.markdown_content, encoding="utf-8")
        fmt = res.metadata.get("format", "unknown")
        table.add_row(
            res.title,
            fmt,
            str(out_file.relative_to(Path.cwd()) if out_file.is_relative_to(Path.cwd()) else out_file),
        )

    console.print(table)
    console.print(f"[bold green]✓[/bold green] Ingested {len(results)} document(s) to {target_dir}")


@main.command()
@click.argument("source", type=click.Path(exists=True))
@click.option("--config", "-c", "config_path", help="Path to configuration file.")
@click.option("--tenant", "-t", "-w", default=None, help="Workspace tenant identifier (defaults to 'default').")
@click.option("--model", "-m", help="LiteLLM model name (e.g. 'openai/gpt-4o-mini', 'ollama/llama3.2').")
@click.option("--offline", is_flag=True, help="Use deterministic rule-based compiler without calling LLM.")
def compile(source: str, config_path: str | None, tenant: str | None, model: str | None, offline: bool):
    """Compile normalized documents into explicit OKF concepts with cross-links."""
    cfg = load_config(config_path)
    if model:
        cfg.llm_model = model

    eff_tenant = tenant or "default"
    src_path = Path(source).resolve()
    content = src_path.read_text(encoding="utf-8", errors="replace")

    repo = GitRepo(cfg.repo_path)
    file_manager = OKFFileManager(repo)

    if offline:
        console.print("[dim]Using deterministic rule-based compiler...[/dim]")
        compiler = RuleBasedCompiler()
    else:
        console.print(f"[yellow]Compiling knowledge using model:[/yellow] [bold]{cfg.llm_model}[/bold]")
        compiler = LLMCompiler(model=cfg.llm_model, fallback_to_rules=True)

    concepts = compiler.compile(content, source_name=src_path.name, tenant_id=eff_tenant)
    if not concepts:
        console.print("[red]No concepts extracted from source document.[/red]")
        return

    table = Table(title=f"Extracted OKF Concepts [tenant: {eff_tenant}]", border_style="yellow")
    table.add_column("ID", style="bold yellow")
    table.add_column("Tenant", style="magenta")
    table.add_column("Type", style="cyan")
    table.add_column("Title")
    table.add_column("Outgoing Links", justify="right")

    for concept in concepts:
        file_manager.save_concept(concept)
        table.add_row(
            concept.id,
            concept.tenant_id,
            concept.type,
            concept.title,
            str(len(concept.edges)),
        )

    console.print(table)

    # Automatically reindex
    cache = SQLiteQueryCache(cfg.cache_path)
    sync_worker = IndexSyncWorker(repo, cache)
    summary = sync_worker.sync(tenant_id=eff_tenant)

    console.print(
        f"[bold green]✓[/bold green] Successfully saved and committed {len(concepts)} concepts to Git repo (tenant: {eff_tenant}).\n"
        f"[dim]Cache updated: {summary.indexed} indexed, {summary.updated} updated in {summary.duration_ms:.1f}ms.[/dim]"
    )


@main.command()
@click.option("--config", "-c", "config_path", help="Path to config file.")
@click.option("--tenant", "-t", "-w", default=None, help="Workspace tenant identifier (syncs all if omitted).")
@click.option("--rebuild", is_flag=True, help="Drop cache and rebuild entirely from Git tree.")
def index(config_path: str | None, tenant: str | None, rebuild: bool):
    """Synchronize Git Markdown files into relational query cache."""
    cfg = load_config(config_path)
    repo = GitRepo(cfg.repo_path)
    cache = SQLiteQueryCache(cfg.cache_path)
    sync_worker = IndexSyncWorker(repo, cache)

    tenant_msg = f" (tenant: {tenant})" if tenant else " (all tenants)"
    action = "Rebuilding" if rebuild else "Synchronizing"
    console.print(f"[yellow]{action} query cache from:[/yellow] {repo.repo_path}{tenant_msg}")

    if rebuild:
        summary = sync_worker.rebuild(tenant_id=tenant)
    else:
        summary = sync_worker.sync(tenant_id=tenant)

    console.print(
        f"[bold green]✓[/bold green] Complete: {summary.indexed} indexed, {summary.updated} updated, "
        f"{summary.deleted} deleted, {summary.skipped} skipped in {summary.duration_ms:.1f}ms."
    )


@main.command()
@click.argument("query_str")
@click.option("--config", "-c", "config_path", help="Path to config file.")
@click.option("--tenant", "-w", default=None, help="Workspace tenant identifier (searches all if omitted).")
@click.option("--tag", "-t", help="Filter by tag.")
@click.option("--type", "concept_type", help="Filter by concept type.")
@click.option("--limit", "-l", default=5, help="Result limit.")
@click.option("--traverse", is_flag=True, help="Traverse graph starting from top match.")
@click.option("--depth", default=2, help="Traversal depth if --traverse is enabled.")
def query(
    query_str: str,
    config_path: str | None,
    tenant: str | None,
    tag: str | None,
    concept_type: str | None,
    limit: int,
    traverse: bool,
    depth: int,
):
    """Execute BM25 keyword search over knowledge concepts."""
    cfg = load_config(config_path)
    cache = SQLiteQueryCache(cfg.cache_path)

    eff_tenant: str | None = None if (tenant is None or tenant.lower() == "all") else tenant
    tags_filter = [tag] if tag else None
    results = cache.search(
        query=query_str,
        tags=tags_filter,
        concept_type=concept_type,
        tenant_id=eff_tenant,
        limit=limit,
    )

    if not results:
        scope = f"in tenant '{tenant}'" if eff_tenant else "across all tenants"
        console.print(f"[dim]No matching concepts found for query: '{query_str}' {scope}[/dim]")
        return

    scope_title = f" [tenant: {tenant}]" if eff_tenant else " [all tenants]"
    table = Table(title=f"Search Results for '{query_str}'{scope_title}", border_style="yellow")
    table.add_column("ID", style="bold yellow")
    table.add_column("Tenant", style="magenta")
    table.add_column("Type", style="cyan")
    table.add_column("Title", style="bold")
    table.add_column("Snippet")
    table.add_column("Rank", justify="right", style="dim")

    for r in results:
        snip = (r.snippet or r.description).replace("<b>", "[bold yellow]").replace("</b>", "[/bold yellow]")
        table.add_row(r.id, r.tenant_id, r.type, r.title, snip, f"{r.rank:.2f}")

    console.print(table)

    if traverse and results:
        top_match = results[0]
        top_id = top_match.id
        top_tenant = top_match.tenant_id
        console.print(f"\n[bold yellow]Multi-Hop Traversal from '{top_id}' [tenant: {top_tenant}] (depth={depth}):[/bold yellow]")
        _print_traversal_tree(cache, top_id, depth, tenant_id=top_tenant)


@main.command()
@click.argument("node_id")
@click.option("--config", "-c", "config_path", help="Path to config file.")
@click.option("--tenant", "-w", default=None, help="Workspace tenant identifier (auto-detected if omitted).")
@click.option("--depth", "-d", default=2, help="Maximum traversal depth.")
@click.option("--direction", default="out", type=click.Choice(["out", "in", "both"]), help="Traversal direction.")
def traverse(node_id: str, config_path: str | None, tenant: str | None, depth: int, direction: str):
    """Traverse graph topological pathways via Recursive CTE."""
    cfg = load_config(config_path)
    cache = SQLiteQueryCache(cfg.cache_path)
    _print_traversal_tree(cache, node_id, depth, direction, tenant_id=tenant)


def _print_traversal_tree(
    cache: SQLiteQueryCache,
    root_id: str,
    depth: int,
    direction: str = "out",
    tenant_id: str | None = None,
):
    result = cache.traverse(root_id, max_depth=depth, direction=direction, tenant_id=tenant_id)
    resolved_tenant = result.tenant_id
    if not result.nodes:
        scope = f" in tenant '{resolved_tenant}'" if resolved_tenant else ""
        console.print(f"[red]Concept '{root_id}' not found{scope}.[/red]")
        return

    nodes_by_id = {n["id"]: n for n in result.nodes}
    root_node = nodes_by_id.get(root_id, {"title": root_id, "type": "Root"})

    tree = Tree(
        f"[bold yellow]{root_node.get('title', root_id)}[/bold yellow] [dim]({root_id})[/dim] "
        f"[{root_node.get('type')}] [magenta](tenant: {resolved_tenant})[/magenta]"
    )

    # Map edges
    children_map = {}
    for edge in result.edges:
        src = edge["source"]
        tgt = edge["target"]
        children_map.setdefault(src, []).append((tgt, edge["label"], edge["link_text"]))

    def add_branches(current_id: str, current_tree: Tree, current_depth: int):
        if current_depth >= depth:
            return
        for child_id, label, _link_text in children_map.get(current_id, []):
            child_info = nodes_by_id.get(child_id, {})
            label_text = f" --[{label or 'references'}]--> "
            title = child_info.get("title", child_id)
            c_type = child_info.get("type", "Node")
            branch = current_tree.add(
                f"[dim]{label_text}[/dim][bold cyan]{title}[/bold cyan] [dim]({child_id})[/dim] [{c_type}]"
            )
            add_branches(child_id, branch, current_depth + 1)

    add_branches(root_id, tree, 0)
    console.print(tree)

    console.print(
        f"\n[dim]Topological traversal: {len(result.nodes)} node(s), {len(result.edges)} edge(s), "
        f"{len(result.paths)} multi-hop path(s) explored via Recursive CTE (tenant: {resolved_tenant}).[/dim]"
    )


@main.command()
@click.argument("node_id")
@click.option("--config", "-c", "config_path", help="Path to config file.")
@click.option("--tenant", "-w", default=None, help="Workspace tenant identifier (searches all if omitted).")
@click.option("--raw", is_flag=True, help="Display raw markdown file directly.")
def show(node_id: str, config_path: str | None, tenant: str | None, raw: bool):
    """Display concept metadata, body, and edges."""
    cfg = load_config(config_path)
    repo = GitRepo(cfg.repo_path)

    try:
        content = repo.read_file(node_id, tenant_id=tenant)
    except FileNotFoundError:
        scope = f" for tenant '{tenant}'" if tenant else ""
        console.print(f"[red]Concept '{node_id}' not found in repository{scope}.[/red]")
        return

    if raw:
        console.print(content)
        return

    cache = SQLiteQueryCache(cfg.cache_path)
    data = cache.get_concept(node_id, tenant_id=tenant)
    if data:
        from rich.markdown import Markdown
        from rich.markup import escape
        panel_title = f"{data['title']} ({data['id']})"
        okf_ver = data.get("okf_version", "0.2")
        gen = data.get("generated", {})
        gen_by = gen.get("by", "unspecified") if isinstance(gen, dict) else str(gen)
        ver_list = data.get("verified", [])
        verified_str = f"[green]Verified ({len(ver_list)} attestation(s))[/green]" if ver_list else "[dim]Unverified[/dim]"
        stale = data.get("stale_after")
        is_stale = data.get("is_stale", False)
        fresh_str = f"[red]Stale (Expired {stale})[/red]" if is_stale else (f"[dim]Active (stale after {stale})[/dim]" if stale else "[dim]Active[/dim]")

        info = (
            f"[bold]Tenant:[/bold] [magenta]{data.get('tenant_id', 'default')}[/magenta]  |  [bold]Type:[/bold] {data['type']}  |  [bold]Status:[/bold] {data['status']}  |  [bold]OKF Spec:[/bold] v{okf_ver}\n"
            f"[bold]Generated By:[/bold] {gen_by}  |  [bold]Trust:[/bold] {verified_str}  |  [bold]Freshness:[/bold] {fresh_str}\n"
            f"[bold]Tags:[/bold] {', '.join(data['tags']) if data['tags'] else 'none'}\n"
            f"[bold]Description:[/bold] {escape(data['description'])}\n"
            f"[bold]File:[/bold] {data['file_path']}  |  [bold]Commit:[/bold] {data.get('commit_hash', 'uncommitted')[:8] if data.get('commit_hash') else 'none'}"
        )
        console.print(Panel(info, title=panel_title, border_style="yellow"))

        if data.get("outgoing_edges"):
            console.print("\n[bold]Outgoing Connections:[/bold]")
            for e in data["outgoing_edges"]:
                console.print(f"  → [yellow]{e['target_id']}[/yellow] ([dim]{e['label']}[/dim])")

        if data.get("incoming_edges"):
            console.print("\n[bold]Incoming Backlinks:[/bold]")
            for e in data["incoming_edges"]:
                console.print(f"  ← [cyan]{e['source_id']}[/cyan] ([dim]{e['label']}[/dim])")

        console.print("\n[bold]Body Content:[/bold]")
        console.print(Panel(Markdown(data["body"]), border_style="dim"))
    else:
        console.print(content)


@main.command()
@click.option("--config", "-c", "config_path", help="Path to config file.")
@click.option("--tenant", "-t", "-w", default=None, help="Workspace tenant identifier (shows global stats if omitted).")
def stats(config_path: str | None, tenant: str | None):
    """Show global statistics of the knowledge graph (optionally scoped to tenant)."""
    cfg = load_config(config_path)
    repo = GitRepo(cfg.repo_path)
    cache = SQLiteQueryCache(cfg.cache_path)

    st = cache.get_stats(tenant_id=tenant)
    head = repo.get_head_commit()

    title_suffix = f" [tenant: {tenant}]" if tenant else " [all tenants]"
    table = Table(title=f"Knowledge Graph Overview{title_suffix}", border_style="yellow")
    table.add_column("Metric", style="bold")
    table.add_column("Value", style="cyan")

    table.add_row("Total Concepts", str(st.total_concepts))
    table.add_row("Total Explicit Edges", str(st.total_edges))
    table.add_row("Active Tenants", ", ".join(st.tenants) if st.tenants else "none")
    table.add_row("Git HEAD Commit", (head[:10] + "...") if head else "none")
    table.add_row("Repository Path", cfg.repo_path)
    table.add_row("Cache Path", cfg.cache_path)

    console.print(table)

    if st.concept_types:
        type_table = Table(title="Concepts by Type", border_style="dim")
        type_table.add_column("Type")
        type_table.add_column("Count", justify="right")
        for ctype, count in st.concept_types.items():
            type_table.add_row(ctype, str(count))
        console.print(type_table)

    if st.top_tags:
        tags_str = ", ".join(f"{t} ({cnt})" for t, cnt in st.top_tags.items())
        console.print(f"[bold]Top Tags:[/bold] {tags_str}")


@main.command()
@click.option("--config", "-c", "config_path", help="Path to config file.")
def tenants(config_path: str | None):
    """List all active tenant workspaces."""
    cfg = load_config(config_path)
    cache = SQLiteQueryCache(cfg.cache_path)
    t_list = cache.list_tenants()

    table = Table(title="Active Tenant Workspaces", border_style="yellow")
    table.add_column("Tenant ID", style="bold yellow")

    for t in t_list:
        table.add_row(t)

    console.print(table)


@main.command()
@click.option("--config", "-c", "config_path", help="Path to config file.")
@click.option("--host", "-h", default=None, help="Host to bind for SSE server.")
@click.option("--port", "-p", default=None, type=int, help="Port to bind for SSE server.")
@click.option("--transport", "-t", default="sse", type=click.Choice(["sse", "stdio", "http"]), help="MCP transport protocol.")
def serve(config_path: str | None, host: str | None, port: int | None, transport: str):
    """Start the FastMCP server for autonomous agent fleets."""
    cfg = load_config(config_path)
    bind_host = host or cfg.mcp_host
    bind_port = port or cfg.mcp_port

    repo = GitRepo(cfg.repo_path)
    cache = SQLiteQueryCache(cfg.cache_path)
    mcp_app = create_mcp_server(config=cfg, repo=repo, cache=cache)

    print_banner()

    if transport == "stdio":
        console.print("[dim]Starting FastMCP server with stdio transport...[/dim]")
        mcp_app.run(transport="stdio")
    else:
        endpoint = f"http://{bind_host}:{bind_port}/sse"
        console.print(f"[bold green]Starting FastMCP server on:[/bold green] [bold yellow]{endpoint}[/bold yellow]")
        console.print("[dim]Connect autonomous agents (Google ADK, LangGraph, Cursor, Claude) to this endpoint.[/dim]")
        mcp_app.run(transport=transport, host=bind_host, port=bind_port)


@main.command(name="api")
@click.option("--config", "-c", "config_path", help="Path to config file.")
@click.option("--host", "-h", default=None, help="Host to bind for FastAPI REST service (default: 0.0.0.0).")
@click.option("--port", "-p", default=None, type=int, help="Port to bind for FastAPI REST service (default: 8080).")
@click.option("--repo", "-r", default=None, help="Path to OKF knowledge repo directory.")
@click.option("--cache", default=None, help="Path to SQLite query cache database.")
@click.option("--model", "-m", default=None, help="Default LiteLLM model string for compiler.")
@click.option("--reload", is_flag=True, help="Enable auto-reload for development.")
@click.option("--workers", "-w", default=1, type=int, help="Number of worker processes.")
def api(
    config_path: str | None,
    host: str | None,
    port: int | None,
    repo: str | None,
    cache: str | None,
    model: str | None,
    reload: bool,
    workers: int,
):
    """Start the standalone FastAPI REST service for Ingestion and Compilation."""
    try:
        import uvicorn

        from mdgraph.server.rest_api import create_rest_api
    except ImportError as e:
        console.print(
            "[bold red]✗ Missing dependencies for REST API service.[/bold red]\n"
            f"[dim]{e}[/dim]\n"
            "Install FastAPI and Uvicorn with: [yellow]pip install mdgraph-ai[api][/yellow] or [yellow]pip install fastapi uvicorn python-multipart[/yellow]"
        )
        sys.exit(1)

    cfg = load_config(config_path)
    if repo:
        cfg.repo_path = str(Path(repo).resolve())
    if cache:
        cfg.cache_path = str(Path(cache).resolve())
    if model:
        cfg.llm_model = model

    bind_host = host or cfg.api_host
    bind_port = port or cfg.api_port

    print_banner()
    console.print(f"[bold green]Starting FastAPI REST service on:[/bold green] [bold yellow]http://{bind_host}:{bind_port}[/bold yellow]")
    console.print(f"[dim]Interactive Swagger UI: http://{bind_host}:{bind_port}/docs[/dim]")
    console.print(f"[dim]Interactive ReDoc: http://{bind_host}:{bind_port}/redoc[/dim]")
    console.print(f"[dim]Knowledge Repo: {cfg.repo_path} | Cache: {cfg.cache_path}[/dim]")

    repo_obj = GitRepo(cfg.repo_path)
    cache_obj = SQLiteQueryCache(cfg.cache_path)
    fastapi_app = create_rest_api(config=cfg, repo=repo_obj, cache=cache_obj)

    uvicorn.run(
        fastapi_app,
        host=bind_host,
        port=bind_port,
        reload=reload,
        workers=workers if not reload else 1,
    )


if __name__ == "__main__":
    main()

