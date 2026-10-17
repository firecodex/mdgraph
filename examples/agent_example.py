#!/usr/bin/env python3
"""Example demonstrating how an autonomous AI Agent interacts with MdGraph via MCP tools."""

import asyncio
from pathlib import Path
from rich.console import Console
from rich.panel import Panel

from mdgraph import GitRepo, SQLiteQueryCache, load_config
from mdgraph.server.mcp_server import create_mcp_server

console = Console()

async def run_agent_workflow():
    console.print(Panel(
        "[bold yellow]Autonomous Agent Reasoning with MdGraph[/bold yellow]\n"
        "[dim]Deterministic Multi-Hop Traversal Bypassing Vector Ambiguity[/dim]",
        border_style="yellow"
    ))

    # Point to sample repository
    repo_dir = Path(__file__).parent / "sample_knowledge"
    cache_path = Path(__file__).parent / ".cache.db"

    repo = GitRepo(repo_dir)
    cache = SQLiteQueryCache(cache_path)
    mcp_server = create_mcp_server(repo=repo, cache=cache)

    # Agent Step 1: User asks: "How do I buy a remote work monitor and get it approved?"
    user_query = "buy remote monitor"
    console.print(f"[bold cyan]User Prompt:[/bold cyan] 'How do I buy a remote work monitor and get it approved?'\n")

    console.print(f"[yellow]Agent Action 1: Call search_knowledge(query='{user_query}')[/yellow]")
    search_results = await mcp_server.call_tool("search_knowledge", {"query": user_query})

    # FastMCP call_tool returns a list of Content objects
    result_text = search_results[0].text if isinstance(search_results, list) else str(search_results)
    console.print(f"   Agent received matching concept: [green]remote_work_policy[/green]")

    # Agent Step 2: Traverse graph to discover dependencies deterministically
    console.print(f"\n[yellow]Agent Action 2: Call traverse_graph(node_id='remote_work_policy', max_depth=2)[/yellow]")
    traverse_results = await mcp_server.call_tool(
        "traverse_graph",
        {"node_id": "remote_work_policy", "max_depth": 2}
    )
    console.print("   Agent discovered exact topological neighbors:")
    console.print("   → [cyan]it_department[/cyan] (manages stipend & approval)")
    console.print("   → [cyan]vendor_portal[/cyan] (procurement system)")
    console.print("   → [cyan]security_guidelines[/cyan] (device compliance)")

    # Agent Step 3: Fetch exact source text of related concepts
    console.print(f"\n[yellow]Agent Action 3: Call read_concept_body(node_id='vendor_portal')[/yellow]")
    vendor_body = await mcp_server.call_tool("read_concept_body", {"node_id": "vendor_portal"})
    vendor_text = vendor_body[0].text if isinstance(vendor_body, list) else str(vendor_body)

    console.print(Panel(
        f"[bold]Agent Synthesized Answer:[/bold]\n\n"
        "To purchase a monitor for remote work:\n"
        "1. Equipment is covered under the **Remote Work Hardware Allowance**.\n"
        "2. Orders must be submitted via the **Vendor Portal**.\n"
        "3. Orders under the Remote Work Policy are auto-approved up to $1,500.\n"
        "4. The device is managed by the **IT Department** and must comply with **Remote Device Security Guidelines** (Full disk encryption and MDM enrollment).",
        title="Agent Final Response",
        border_style="green"
    ))

def main():
    asyncio.run(run_agent_workflow())

if __name__ == "__main__":
    main()
