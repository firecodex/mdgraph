"""Command Line Interface (CLI) for MdGraph."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from mdgraph import __version__
from mdgraph.compiler.llm_compiler import LLMCompiler
from mdgraph.compiler.mock_compiler import RuleBasedCompiler
from mdgraph.config import MdGraphConfig, load_config
from mdgraph.indexer.sqlite_cache import SQLiteQueryCache
from mdgraph.indexer.sync import IndexSyncWorker
from mdgraph.ingestion.ingestor import UniversalIngestor
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
            "type: Concept\n"
            "title: Example OKF Concept\n"
            "description: An introductory node in the MdGraph Open Knowledge Format.\n"
            "tags: [example, getting-started]\n"
            "status: stable\n"
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
@click.argument("source", type=click.Path(exists=True))
@click.option("--dest", "-d", default=None, help="Destination directory for normalized markdown files.")
def ingest(source: str, dest: Optional[str]):
    """Ingest documents (PDF, HTML, text) and normalize into Markdown."""
    src_path = Path(source).resolve()
    ingestor = UniversalIngestor()

    results = []
    if src_path.is_file():
        console.print(f"[yellow]Ingesting file:[/yellow] {src_path.name}")
        results.append(ingestor.ingest_file(src_path))
    else:
        console.print(f"[yellow]Ingesting directory:[/yellow] {src_path}")
        results.extend(ingestor.ingest_directory(src_path))

    target_dir = Path(dest).resolve() if dest else src_path.parent / "normalized"
    target_dir.mkdir(parents=True, exist_ok=True)

    table = Table(title="Ingested Documents", border_style="yellow")
    table.add_column("Title", style="bold")
    table.add_column("Source Format", style="dim")
    table.add_column("Output File", style="green")

    for res in results:
        slug = res.title.lower().replace(" ", "_")[:50]
        out_file = target_dir / f"{slug}.md"
        out_file.write_text(res.markdown_content, encoding="utf-8")
        fmt = res.metadata.get("format", "unknown")
        table.add_row(res.title, fmt, str(out_file.relative_to(Path.cwd()) if out_file.is_relative_to(Path.cwd()) else out_file))

    console.print(table)
    console.print(f"[bold green]✓[/bold green] Ingested {len(results)} document(s) to {target_dir}")


@main.command()
@click.argument("source", type=click.Path(exists=True))
@click.option("--config", "-c", "config_path", help="Path to configuration file.")
@click.option("--model", "-m", help="LiteLLM model name (e.g. 'openai/gpt-4o-mini', 'ollama/llama3.2').")
@click.option("--offline", is_flag=True, help="Use deterministic rule-based compiler without calling LLM.")
def compile(source: str, config_path: Optional[str], model: Optional[str], offline: bool):
    """Compile normalized documents into explicit OKF concepts with cross-links."""
    cfg = load_config(config_path)
    if model:
        cfg.llm_model = model

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

    concepts = compiler.compile(content, source_name=src_path.name)
    if not concepts:
        console.print("[red]No concepts extracted from source document.[/red]")
        return

    table = Table(title="Extracted OKF Concepts", border_style="yellow")
    table.add_column("ID", style="bold yellow")
    table.add_column("Type", style="cyan")
    table.add_column("Title")
    table.add_column("Outgoing Links", justify="right")

    for concept in concepts:
        file_manager.save_concept(concept)
        table.add_row(
            concept.id,
            concept.type,
            concept.title,
            str(len(concept.edges)),
        )

    console.print(table)

    # Automatically reindex
    cache = SQLiteQueryCache(cfg.cache_path)
    sync_worker = IndexSyncWorker(repo, cache)
    summary = sync_worker.sync()

    console.print(
        f"[bold green]✓[/bold green] Successfully saved and committed {len(concepts)} concepts to Git repo.\n"
        f"[dim]Cache updated: {summary.indexed} indexed, {summary.updated} updated in {summary.duration_ms:.1f}ms.[/dim]"
    )


@main.command()
@click.option("--config", "-c", "config_path", help="Path to config file.")
@click.option("--rebuild", is_flag=True, help="Drop cache and rebuild entirely from Git tree.")
def index(config_path: Optional[str], rebuild: bool):
    """Synchronize Git Markdown files into relational query cache."""
    cfg = load_config(config_path)
    repo = GitRepo(cfg.repo_path)
    cache = SQLiteQueryCache(cfg.cache_path)
    sync_worker = IndexSyncWorker(repo, cache)

    action = "Rebuilding" if rebuild else "Synchronizing"
    console.print(f"[yellow]{action} query cache from:[/yellow] {repo.repo_path}")

    if rebuild:
        summary = sync_worker.rebuild()
    else:
        summary = sync_worker.sync()

    console.print(
        f"[bold green]✓[/bold green] Complete: {summary.indexed} indexed, {summary.updated} updated, "
        f"{summary.deleted} deleted, {summary.skipped} skipped in {summary.duration_ms:.1f}ms."
    )


@main.command()
@click.argument("query_str")
@click.option("--config", "-c", "config_path", help="Path to config file.")
@click.option("--tag", "-t", help="Filter by tag.")
@click.option("--type", "concept_type", help="Filter by concept type.")
@click.option("--limit", "-l", default=5, help="Result limit.")
@click.option("--traverse", is_flag=True, help="Traverse graph starting from top match.")
@click.option("--depth", default=2, help="Traversal depth if --traverse is enabled.")
def query(
    query_str: str,
    config_path: Optional[str],
    tag: Optional[str],
    concept_type: Optional[str],
    limit: int,
    traverse: bool,
    depth: int,
):
    """Execute BM25 keyword search over knowledge concepts."""
    cfg = load_config(config_path)
    cache = SQLiteQueryCache(cfg.cache_path)

    tags_filter = [tag] if tag else None
    results = cache.search(query=query_str, tags=tags_filter, concept_type=concept_type, limit=limit)

    if not results:
        console.print(f"[dim]No matching concepts found for query: '{query_str}'[/dim]")
        return

    table = Table(title=f"Search Results for '{query_str}'", border_style="yellow")
    table.add_column("ID", style="bold yellow")
    table.add_column("Type", style="cyan")
    table.add_column("Title", style="bold")
    table.add_column("Snippet")
    table.add_column("Rank", justify="right", style="dim")

    for r in results:
        snip = (r.snippet or r.description).replace("<b>", "[bold yellow]").replace("</b>", "[/bold yellow]")
        table.add_row(r.id, r.type, r.title, snip, f"{r.rank:.2f}")

    console.print(table)

    if traverse and results:
        top_id = results[0].id
        console.print(f"\n[bold yellow]Multi-Hop Traversal from '{top_id}' (depth={depth}):[/bold yellow]")
        _print_traversal_tree(cache, top_id, depth)


@main.command()
@click.argument("node_id")
@click.option("--config", "-c", "config_path", help="Path to config file.")
@click.option("--depth", "-d", default=2, help="Maximum traversal depth.")
@click.option("--direction", default="out", type=click.Choice(["out", "in", "both"]), help="Traversal direction.")
def traverse(node_id: str, config_path: Optional[str], depth: int, direction: str):
    """Traverse graph topological pathways via Recursive CTE."""
    cfg = load_config(config_path)
    cache = SQLiteQueryCache(cfg.cache_path)
    _print_traversal_tree(cache, node_id, depth, direction)


def _print_traversal_tree(cache: SQLiteQueryCache, root_id: str, depth: int, direction: str = "out"):
    result = cache.traverse(root_id, max_depth=depth, direction=direction)
    if not result.nodes:
        console.print(f"[red]Concept '{root_id}' not found in cache.[/red]")
        return

    nodes_by_id = {n["id"]: n for n in result.nodes}
    root_node = nodes_by_id.get(root_id, {"title": root_id, "type": "Root"})

    tree = Tree(f"[bold yellow]{root_node.get('title', root_id)}[/bold yellow] [dim]({root_id})[/dim] [{root_node.get('type')}]")

    # Map edges
    children_map = {}
    for edge in result.edges:
        src = edge["source"]
        tgt = edge["target"]
        children_map.setdefault(src, []).append((tgt, edge["label"], edge["link_text"]))

    def add_branches(current_id: str, current_tree: Tree, current_depth: int):
        if current_depth >= depth:
            return
        for child_id, label, link_text in children_map.get(current_id, []):
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
        f"{len(result.paths)} multi-hop path(s) explored via Recursive CTE.[/dim]"
    )


@main.command()
@click.argument("node_id")
@click.option("--config", "-c", "config_path", help="Path to config file.")
@click.option("--raw", is_flag=True, help="Display raw markdown file directly.")
def show(node_id: str, config_path: Optional[str], raw: bool):
    """Display concept metadata, body, and edges."""
    cfg = load_config(config_path)
    repo = GitRepo(cfg.repo_path)

    try:
        content = repo.read_file(node_id)
    except FileNotFoundError:
        console.print(f"[red]Concept '{node_id}' not found in repository.[/red]")
        return

    if raw:
        console.print(content)
        return

    cache = SQLiteQueryCache(cfg.cache_path)
    data = cache.get_concept(node_id)
    if data:
        from rich.markdown import Markdown
        from rich.markup import escape
        panel_title = f"{data['title']} ({data['id']})"
        info = (
            f"[bold]Type:[/bold] {data['type']}  |  [bold]Status:[/bold] {data['status']}\n"
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
def stats(config_path: Optional[str]):
    """Show global statistics of the knowledge graph."""
    cfg = load_config(config_path)
    repo = GitRepo(cfg.repo_path)
    cache = SQLiteQueryCache(cfg.cache_path)

    st = cache.get_stats()
    head = repo.get_head_commit()

    table = Table(title="Knowledge Graph Overview", border_style="yellow")
    table.add_column("Metric", style="bold")
    table.add_column("Value", style="cyan")

    table.add_row("Total Concepts", str(st.total_concepts))
    table.add_row("Total Explicit Edges", str(st.total_edges))
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
@click.option("--host", "-h", default=None, help="Host to bind for SSE server.")
@click.option("--port", "-p", default=None, type=int, help="Port to bind for SSE server.")
@click.option("--transport", "-t", default="sse", type=click.Choice(["sse", "stdio", "http"]), help="MCP transport protocol.")
def serve(config_path: Optional[str], host: Optional[str], port: Optional[int], transport: str):
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


if __name__ == "__main__":
    main()
