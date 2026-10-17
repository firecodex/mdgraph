"""MdGraph: A vectorless Open Knowledge Format (OKF) context engine for agentic AI.

Kill the Vector Chunks. Store Explicit Knowledge Graphs.
"""

__version__ = "0.1.0"

from mdgraph.models import OKFConcept, Edge, GraphResult, TraverseResult
from mdgraph.storage.git_repo import GitRepo
from mdgraph.storage.okf_file import OKFFileManager
from mdgraph.indexer.sqlite_cache import SQLiteQueryCache
from mdgraph.indexer.sync import IndexSyncWorker
from mdgraph.ingestion.ingestor import UniversalIngestor
from mdgraph.compiler.llm_compiler import LLMCompiler
from mdgraph.compiler.mock_compiler import RuleBasedCompiler
from mdgraph.server.mcp_server import create_mcp_server
from mdgraph.config import MdGraphConfig, load_config

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
    "MdGraphConfig",
    "load_config",
]
