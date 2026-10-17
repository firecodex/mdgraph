"""Unit tests for knowledge graph compilers."""

from mdgraph.compiler.llm_compiler import LLMCompiler
from mdgraph.compiler.mock_compiler import RuleBasedCompiler


def test_rule_based_compiler_sections_and_links():
    text = (
        "# Remote Work Policy\n\n"
        "Employees can work remotely up to 3 days per week.\n"
        "Expenses are managed through the Vendor Portal.\n\n"
        "## Vendor Portal\n\n"
        "The Vendor Portal facilitates ordering hardware and supplies.\n"
        "See also Remote Work Policy for eligibility.\n"
    )

    compiler = RuleBasedCompiler()
    concepts = compiler.compile(text, source_name="company_rules.md")

    assert len(concepts) == 2
    concept_ids = {c.id for c in concepts}
    assert "remote_work_policy" in concept_ids
    assert "vendor_portal" in concept_ids

    # Check auto-link creation between sections
    rwp = next(c for c in concepts if c.id == "remote_work_policy")
    vp = next(c for c in concepts if c.id == "vendor_portal")

    assert rwp.type == "Policy"
    # Check edges
    outgoing = {e.target_id for e in rwp.edges}
    assert "vendor_portal" in outgoing


def test_llm_compiler_fallback():
    compiler = LLMCompiler(model="mock/test-model", fallback_to_rules=True)
    text = (
        "# Database Architecture\n\n"
        "Uses SQLite FTS5 for full-text search and recursive CTEs for graphs.\n\n"
        "## Recursive CTE Queries\n\n"
        "Enables instant multi-hop traversals.\n"
    )
    concepts = compiler.compile(text, source_name="architecture.md")
    assert len(concepts) >= 2
    assert any(c.id == "database_architecture" for c in concepts)
