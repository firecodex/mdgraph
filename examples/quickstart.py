#!/usr/bin/env python3
"""MdGraph Quickstart Example: Demonstrating the vectorless OKF context engine."""

from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from mdgraph import GitRepo, IndexSyncWorker, SQLiteQueryCache

console = Console()

def main():
    console.print(Panel(
        "[bold yellow]MdGraph Quickstart Demonstration[/bold yellow]\n"
        "[dim]Kill the Vector Chunks. Store Explicit Knowledge Graphs.[/dim]",
        border_style="yellow"
    ))

    # 1. Point to sample repository
    repo_dir = Path(__file__).parent / "sample_knowledge"
    cache_path = Path(__file__).parent / ".cache.db"

    console.print(f"[yellow]1. Initializing Git truth layer at:[/yellow] {repo_dir}")
    repo = GitRepo(repo_dir, auto_init=True)
    repo.commit("Initial commit of sample enterprise knowledge")

    # 2. Initialize relational query cache
    console.print(f"[yellow]2. Connecting to SQLite relational cache at:[/yellow] {cache_path}")
    cache = SQLiteQueryCache(cache_path)

    # 3. Synchronize files into SQLite cache
    console.print("[yellow]3. Running IndexSyncWorker to build relational cache and FTS5...[/yellow]")
    sync_worker = IndexSyncWorker(repo, cache)
    summary = sync_worker.rebuild()
    console.print(f"   ✓ Synchronized {summary.indexed} concepts in {summary.duration_ms:.2f}ms\n")

    # 4. Perform BM25 Full-Text Keyword Search
    query = "hardware stipend"
    console.print(f"[yellow]4. Executing BM25 keyword search for:[/yellow] '{query}'")
    results = cache.search(query, limit=3)
    for r in results:
        console.print(f"   → Match: [bold]{r.title}[/bold] ([cyan]{r.id}[/cyan]) - Rank: {r.rank:.2f}")
        if r.snippet:
            console.print(f"     Snippet: [dim]{r.snippet}[/dim]")

    # 5. Multi-Hop Topological Traversal via SQL Recursive CTE
    start_node = "remote_work_policy"
    console.print(f"\n[yellow]5. Executing Recursive CTE Traversal from:[/yellow] '{start_node}' (depth=2)")
    traversal = cache.traverse(start_node, max_depth=2)
    console.print(f"   ✓ Explored {len(traversal.nodes)} nodes and {len(traversal.edges)} edges:")
    for edge in traversal.edges:
        console.print(f"     [bold]{edge['source']}[/bold] --[{edge['label']}]--> [bold cyan]{edge['target']}[/bold cyan] (depth {edge['depth']})")

    # 6. Topological Path Finding
    dest_node = "security_guidelines"
    console.print(f"\n[yellow]6. Finding shortest topological path from '{start_node}' to '{dest_node}'...[/yellow]")
    path = cache.find_path(start_node, dest_node, max_depth=5)
    if path:
        console.print(f"   ✓ Shortest path: [bold green]{' ➔ '.join(path)}[/bold green]")

    # 7. Knowledge Graph Statistics
    stats = cache.get_stats()
    console.print("\n[yellow]7. Knowledge Graph Stats:[/yellow]")
    console.print(f"   Total Concepts: {stats.total_concepts}")
    console.print(f"   Total Cross-Links: {stats.total_edges}")
    console.print(f"   Concept Types: {stats.concept_types}")
    console.print(f"   Top Tags: {stats.top_tags}")

    console.print("\n[bold green]✓ Quickstart demonstration completed successfully![/bold green]")
    console.print("[dim]To start the native FastMCP server, run: mdgraph serve --port 8000[/dim]")

if __name__ == "__main__":
    main()
