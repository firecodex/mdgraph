"""Server package for Model Context Protocol (MCP) and REST API integrations."""

from mdgraph.server.mcp_server import create_mcp_server

__all__ = ["create_mcp_server", "create_rest_api"]


def __getattr__(name: str):
    if name == "create_rest_api":
        from mdgraph.server.rest_api import create_rest_api

        return create_rest_api
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

