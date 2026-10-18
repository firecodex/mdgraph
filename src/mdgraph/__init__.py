"""MdGraph: A vectorless Open Knowledge Format (OKF) context engine for agentic AI.

Kill the Vector Chunks. Store Explicit Knowledge Graphs.
"""

__version__ = "0.1.1"

from mdgraph.compiler.llm_compiler import LLMCompiler
from mdgraph.compiler.mock_compiler import RuleBasedCompiler
from mdgraph.config import MdGraphConfig, load_config
from mdgraph.indexer.sqlite_cache import SQLiteQueryCache
from mdgraph.indexer.sync import IndexSyncWorker
from mdgraph.ingestion.ingestor import UniversalIngestor
from mdgraph.models import Edge, GraphResult, OKFConcept, TraverseResult
from mdgraph.server.mcp_server import create_mcp_server
from mdgraph.storage.git_repo import GitRepo
from mdgraph.storage.okf_file import OKFFileManager

__all__ = [
    "__version__",
    "OKFConcept",
    "Edge",
    "GraphResult",
    "TraverseResult",
    "GitRepo",
    "OKFFileManager",
    "SQLiteQueryCache",
    "IndexSyncWorker",
    "UniversalIngestor",
    "LLMCompiler",
    "RuleBasedCompiler",
    "create_mcp_server",
    "create_rest_api",
    "MdGraphConfig",
    "load_config",
]


def __getattr__(name: str):
    if name == "create_rest_api":
        from mdgraph.server.rest_api import create_rest_api

        return create_rest_api
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

