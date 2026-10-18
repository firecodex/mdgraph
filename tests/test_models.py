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


def test_okf_v2_spec_and_trust_signals():
    """Verify full compliance with Google OKF v0.2 / v2 specification: provenance, verification, freshness."""
    concept = OKFConcept(
        okf_version="0.2",
        id="payment_gateway",
        type="System",
        title="Payment Gateway Integration",
        description="Architecture specification for payments",
        resource="https://cloud.google.com/architecture/payments",
        tags=["fintech", "payments"],
        status="stable",
        stale_after="2035-12-31",
        generated={
            "by": "agent:compiler-v2",
            "at": "2026-10-17T12:00:00Z",
        },
        verified=[
            {
                "by": "human:compliance_lead",
                "at": "2026-10-17T14:00:00Z",
                "notes": "Verified PCI-DSS compliance",
            }
        ],
        sources=["./normalized/fintech_spec.md"],
        body="# Payment Gateway\n\nConnects to [Core Ledger](./core_ledger.md).\n",
    )

    # Trust helpers
    assert concept.is_verified is True
    assert concept.is_stale is False
    assert concept.provenance_author == "agent:compiler-v2"

    # Serialize to Markdown
    md_text = concept.to_markdown()
    assert "okf_version: '0.2'" in md_text or "okf_version: \"0.2\"" in md_text or "okf_version: 0.2" in md_text
    assert "resource: https://cloud.google.com/architecture/payments" in md_text
    assert "generated:" in md_text
    assert "verified:" in md_text
    assert "stale_after: '2035-12-31'" in md_text or "stale_after: 2035-12-31" in md_text

    # Parse back from Markdown
    parsed = OKFConcept.from_markdown(md_text, file_path="concepts/payment_gateway.md")
    assert parsed.okf_version == "0.2"
    assert parsed.resource == "https://cloud.google.com/architecture/payments"
    assert parsed.is_verified is True
    assert len(parsed.verified) == 1
    assert parsed.verified[0]["by"] == "human:compliance_lead"
    assert parsed.generated["by"] == "agent:compiler-v2"
    assert parsed.sources == ["./normalized/fintech_spec.md"]
    assert len(parsed.edges) == 1
    assert parsed.edges[0].target_id == "core_ledger"


def test_future_okf_version_compatibility():
    """Verify forward-compatibility with future OKF specifications (v3, v4, etc.) and arbitrary metadata."""
    future_markdown = (
        "---\n"
        "okf_version: \"3.1.0\"\n"
        "type: AutonomousWorkflow\n"
        "title: Multi-Agent Consensus Protocol\n"
        "description: Protocol for distributed agent deliberation\n"
        "status: stable\n"
        "confidence_score: 0.994\n"
        "agent_consensus_signatures:\n"
        "  - agent_id: agent_alpha\n"
        "    sha256: 7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069\n"
        "  - agent_id: agent_beta\n"
        "    sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855\n"
        "future_runtime_flag: true\n"
        "---\n\n"
        "# Consensus Protocol\n\n"
        "Coordinates with [Worker Swarm](./worker_swarm.md).\n"
    )

    # Parsing must NOT crash on future version or unknown fields
    parsed = OKFConcept.from_markdown(future_markdown, file_path="concepts/consensus.md")
    assert parsed.okf_version == "3.1.0"
    assert parsed.type == "AutonomousWorkflow"
    assert parsed.title == "Multi-Agent Consensus Protocol"

    # Future fields must be captured losslessly
    assert parsed.metadata["confidence_score"] == 0.994
    assert parsed.metadata["future_runtime_flag"] is True
    assert len(parsed.metadata["agent_consensus_signatures"]) == 2

    # Round-trip serialization back to Markdown must preserve future keys
    reserialized = parsed.to_markdown()
    assert "okf_version: '3.1.0'" in reserialized or "okf_version: \"3.1.0\"" in reserialized or "okf_version: 3.1.0" in reserialized
    assert "confidence_score: 0.994" in reserialized
    assert "future_runtime_flag: true" in reserialized
    assert "agent_consensus_signatures:" in reserialized
    assert "[Worker Swarm](./worker_swarm.md)" in reserialized

