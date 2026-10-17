"""Unit tests for Native FastMCP server integration."""

import asyncio
from mdgraph.models import OKFConcept
from mdgraph.server.mcp_server import create_mcp_server
from mdgraph.storage.okf_file import OKFFileManager


def test_mcp_server_tools_and_resources(git_repo, sqlite_cache):
    # Seed knowledge graph
    fm = OKFFileManager(git_repo)
    c1 = OKFConcept(
        id="agent_framework",
        type="Architecture",
        title="Agentic Framework",
        description="Architecture of autonomous agents",
        tags=["ai", "agents"],
        body="# Agentic Framework\n\nDepends on [Vectorless Storage](./vectorless_storage.md).",
    )
    c1.edges = OKFConcept.extract_links(c1.id, c1.body)
    fm.save_concept(c1)

    c2 = OKFConcept(
        id="vectorless_storage",
        type="System",
        title="Vectorless Storage",
        description="Explicit graph storage",
        tags=["storage", "okf"],
        body="# Vectorless Storage\n\nUses SQLite and Git.",
    )
    fm.save_concept(c2)

    mcp = create_mcp_server(repo=git_repo, cache=sqlite_cache)

    # FastMCP exposes tools
    tools = asyncio.run(mcp.list_tools())
    tool_names = {t.name for t in tools}
    assert "get_concept" in tool_names
    assert "read_concept_body" in tool_names
    assert "search_knowledge" in tool_names
    assert "traverse_graph" in tool_names
    assert "find_path" in tool_names
    assert "get_graph_stats" in tool_names

    # Test calling tool: get_concept
    concept_res = asyncio.run(mcp.call_tool("get_concept", {"node_id": "agent_framework"}))
    assert concept_res is not None
    # Result in FastMCP call_tool is a list of content items or dict
    if isinstance(concept_res, list) and concept_res:
        text_content = concept_res[0].text
        assert "Agentic Framework" in text_content
    elif isinstance(concept_res, dict):
        assert concept_res.get("title") == "Agentic Framework"

    # Test calling tool: read_concept_body
    body_res = asyncio.run(mcp.call_tool("read_concept_body", {"node_id": "agent_framework"}))
    if isinstance(body_res, list) and body_res:
        assert "# Agentic Framework" in body_res[0].text

    # Test calling tool: search_knowledge
    search_res = asyncio.run(mcp.call_tool("search_knowledge", {"query": "Vectorless"}))
    if isinstance(search_res, list) and search_res:
        assert "vectorless_storage" in str(search_res[0].text)

    # Test calling tool: traverse_graph
    traverse_res = asyncio.run(mcp.call_tool("traverse_graph", {"node_id": "agent_framework", "max_depth": 2}))
    if isinstance(traverse_res, list) and traverse_res:
        assert "vectorless_storage" in str(traverse_res[0].text)

    # Test calling tool: find_path
    path_res = asyncio.run(mcp.call_tool("find_path", {"source_id": "agent_framework", "target_id": "vectorless_storage"}))
    if isinstance(path_res, list) and path_res:
        assert "vectorless_storage" in str(path_res[0].text)
