"""Unit tests for OKF data models, link extraction, and serialization."""

import pytest
from pydantic import ValidationError

from mdgraph.models import OKFConcept, normalize_node_id


def test_normalize_node_id():
    assert normalize_node_id("./it_department.md") == "it_department"
    assert normalize_node_id("../policies/remote_work.md") == "remote_work"
    assert normalize_node_id("IT Department") == "it_department"
    assert normalize_node_id("concepts/vendor_portal.md#section-1") == "vendor_portal"
    assert normalize_node_id("Simple-Slug") == "simple-slug"


def test_okf_concept_validation():
    # 'type' is strictly required by Google OKF spec
    with pytest.raises(ValidationError):
        OKFConcept(id="test", type="", title="Test")

    concept = OKFConcept(
        id="sample_concept",
        type="Concept",
        title="Sample Concept",
        description="A test concept",
        tags=["test", "okf"],
    )
    assert concept.id == "sample_concept"
    assert concept.type == "Concept"
    assert "okf" in concept.tags


def test_okf_concept_to_markdown_and_from_markdown():
    original = OKFConcept(
        id="policy_a",
        type="Policy",
        title="Data Retention Policy",
        description="Guidelines for storing user data",
        tags=["security", "compliance"],
        status="stable",
        body=(
            "# Data Retention Policy\n\n"
            "This policy depends on the [Security Framework](./security_framework.md) "
            "and also [[backup_strategy]].\n"
        ),
    )

    md_text = original.to_markdown()
    assert md_text.startswith("---")
    assert "type: Policy" in md_text
    assert "title: Data Retention Policy" in md_text

    # Parse back
    parsed = OKFConcept.from_markdown(md_text, file_path="concepts/policy_a.md")
    assert parsed.id == "policy_a"
    assert parsed.type == "Policy"
    assert parsed.title == "Data Retention Policy"
    assert parsed.description == "Guidelines for storing user data"
    assert "security" in parsed.tags

    # Verify link extraction
    assert len(parsed.edges) == 2
    target_ids = {e.target_id for e in parsed.edges}
    assert "security_framework" in target_ids
    assert "backup_strategy" in target_ids


def test_link_extraction_ignores_external_urls():
    body = (
        "Check [Google](https://google.com) or [Email](mailto:info@example.com) "
        "and internal link [Architecture](./system_arch.md)."
    )
    edges = OKFConcept.extract_links("source_node", body)
    assert len(edges) == 1
    assert edges[0].target_id == "system_arch"
