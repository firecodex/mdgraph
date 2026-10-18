"""Tests for Multi-tenant workspace scoping (tenant_id) across MdGraph."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from mdgraph.indexer.sqlite_cache import SQLiteQueryCache
from mdgraph.indexer.sync import IndexSyncWorker
from mdgraph.models import Edge, OKFConcept
from mdgraph.server.mcp_server import create_mcp_server
from mdgraph.server.rest_api import create_rest_api
from mdgraph.storage.git_repo import GitRepo
from mdgraph.storage.okf_file import OKFFileManager


def test_multitenant_model_serialization_and_inference():
    # 1. Tenant ID serialized to YAML frontmatter
    concept_tenant = OKFConcept(
        id="payment_gateway",
        tenant_id="fintech_org",
        type="System",
        title="Payment Gateway",
        description="Core fintech transaction router.",
        tags=["fintech", "payments"],
        body="# Payment Gateway\n\nHandles transactions via [Ledger](./ledger.md).",
    )
    md = concept_tenant.to_markdown()
    assert "tenant_id: fintech_org" in md

    # 2. Deserialization from frontmatter preserves tenant_id
    parsed = OKFConcept.from_markdown(md)
    assert parsed.tenant_id == "fintech_org"
    assert parsed.id == "payment_gateway"
    assert len(parsed.edges) == 1
    assert parsed.edges[0].tenant_id == "fintech_org"

    # 3. Path inference: if YAML has no tenant_id, infer from tenants/{tenant_id}/ path
    no_tenant_md = (
        "---\n"
        "id: secret_sauce\n"
        "type: Concept\n"
        "title: Secret Sauce\n"
        "---\n"
        "# Secret Sauce\n"
    )
    inferred = OKFConcept.from_markdown(
        no_tenant_md,
        file_path="tenants/kitchen_inc/concepts/secret_sauce.md",
    )
    assert inferred.tenant_id == "kitchen_inc"

    # 4. Edge model equality and hashing respects tenant_id
    e1 = Edge(source_id="a", target_id="b", tenant_id="tenant_1")
    e2 = Edge(source_id="a", target_id="b", tenant_id="tenant_2")
    assert e1 != e2
    assert len({e1, e2}) == 2


def test_sqlite_multitenant_isolation():
    cache = SQLiteQueryCache(":memory:")

    # Insert two concepts with the IDENTICAL node ID in different tenants
    concept_a = OKFConcept(
        id="architecture",
        tenant_id="tenant_a",
        type="Architecture",
        title="Tenant A Microservices",
        description="Kubernetes microservices architecture for Tenant A.",
        tags=["cloud", "k8s"],
        body="# Tenant A Microservices\n\nConnects to [Database](./db.md).",
    )
    concept_a.edges = [Edge(source_id="architecture", target_id="db", tenant_id="tenant_a")]

    concept_b = OKFConcept(
        id="architecture",
        tenant_id="tenant_b",
        type="Architecture",
        title="Tenant B Monolith",
        description="Modular monolith architecture for Tenant B.",
        tags=["monolith", "rails"],
        body="# Tenant B Monolith\n\nConnects to [Cache](./cache.md).",
    )
    concept_b.edges = [Edge(source_id="architecture", target_id="cache", tenant_id="tenant_b")]

    cache.insert_or_update_concept(concept_a)
    cache.insert_or_update_concept(concept_b)

    # 1. Concept lookups are isolated
    res_a = cache.get_concept("architecture", tenant_id="tenant_a")
    assert res_a is not None
    assert res_a["title"] == "Tenant A Microservices"
    assert res_a["outgoing_edges"][0]["target_id"] == "db"

    res_b = cache.get_concept("architecture", tenant_id="tenant_b")
    assert res_b is not None
    assert res_b["title"] == "Tenant B Monolith"
    assert res_b["outgoing_edges"][0]["target_id"] == "cache"

    # 2. BM25 Search isolation
    search_a = cache.search("Microservices", tenant_id="tenant_a")
    assert len(search_a) == 1
    assert search_a[0].title == "Tenant A Microservices"

    search_b = cache.search("Microservices", tenant_id="tenant_b")
    assert len(search_b) == 0

    search_all = cache.search("architecture", tenant_id=None)
    assert len(search_all) == 2

    # 3. Recursive CTE Traversal isolation
    trav_a = cache.traverse("architecture", tenant_id="tenant_a")
    targets_a = [e["target"] for e in trav_a.edges]
    assert "db" in targets_a
    assert "cache" not in targets_a

    trav_b = cache.traverse("architecture", tenant_id="tenant_b")
    targets_b = [e["target"] for e in trav_b.edges]
    assert "cache" in targets_b
    assert "db" not in targets_b

    # 4. Active tenants listing
    tenants = cache.list_tenants()
    assert "tenant_a" in tenants
    assert "tenant_b" in tenants

    # 5. Scoped deletion
    cache.delete_concept("architecture", tenant_id="tenant_a")
    assert cache.get_concept("architecture", tenant_id="tenant_a") is None
    assert cache.get_concept("architecture", tenant_id="tenant_b") is not None


def test_multitenant_git_storage_and_file_manager():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = GitRepo(tmpdir)
        fm = OKFFileManager(repo)

        # Save concept for tenant 'team_security'
        concept_sec = OKFConcept(
            id="auth_policy",
            tenant_id="team_security",
            type="Policy",
            title="Zero Trust Auth Policy",
            description="All services require mTLS.",
            body="# Zero Trust Auth Policy\n\nmTLS required.",
        )
        fm.save_concept(concept_sec)

        # Save concept for default tenant
        concept_def = OKFConcept(
            id="general_guide",
            tenant_id="default",
            type="Guide",
            title="General Getting Started",
            description="Welcome to the docs.",
            body="# General Getting Started\n\nHello world.",
        )
        fm.save_concept(concept_def)

        # Verify filesystem paths
        assert (Path(tmpdir) / "tenants" / "team_security" / "concepts" / "auth_policy.md").is_file()
        assert (Path(tmpdir) / "concepts" / "general_guide.md").is_file()

        # Scoped list_markdown_files
        sec_files = repo.list_markdown_files(tenant_id="team_security")
        assert len(sec_files) == 1
        assert sec_files[0].name == "auth_policy.md"

        def_files = repo.list_markdown_files(tenant_id="default")
        def_names = [f.name for f in def_files]
        assert "general_guide.md" in def_names
        assert "auth_policy.md" not in def_names

        # Load by ID scoped to tenant
        loaded_sec = fm.load_by_id("auth_policy", tenant_id="team_security")
        assert loaded_sec.id == "auth_policy"
        assert loaded_sec.tenant_id == "team_security"

        # List active tenants in GitRepo
        repo_tenants = repo.list_tenants()
        assert "team_security" in repo_tenants
        assert "default" in repo_tenants


def test_multitenant_sync_worker():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = GitRepo(tmpdir)
        fm = OKFFileManager(repo)
        cache = SQLiteQueryCache(":memory:")
        worker = IndexSyncWorker(repo, cache)

        # Create concepts in 2 tenants
        c1 = OKFConcept(
            id="service_mesh",
            tenant_id="infra_team",
            type="System",
            title="Service Mesh",
            body="# Service Mesh\n\nIstio control plane.",
        )
        c2 = OKFConcept(
            id="billing_engine",
            tenant_id="finance_team",
            type="System",
            title="Billing Engine",
            body="# Billing Engine\n\nStripe integration.",
        )
        fm.save_concept(c1)
        fm.save_concept(c2)

        # Sync only infra_team
        summary_infra = worker.sync(tenant_id="infra_team")
        assert summary_infra.indexed == 1
        assert cache.get_concept("service_mesh", tenant_id="infra_team") is not None
        assert cache.get_concept("billing_engine", tenant_id="finance_team") is None

        # Sync all
        summary_all = worker.sync()
        assert summary_all.indexed >= 1
        assert cache.get_concept("billing_engine", tenant_id="finance_team") is not None


def test_rest_api_multitenant_endpoints():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = GitRepo(tmpdir)
        cache = SQLiteQueryCache(":memory:")
        app = create_rest_api(repo=repo, cache=cache)
        with TestClient(app) as client:
            # 1. Compile endpoint with tenant_id
            doc_content = "# User Authentication\n\nHandles JWT authentication via [Tokens](./tokens.md).\n\n# Tokens\n\nSecret HMAC tokens."
            resp = client.post(
                "/api/v1/compile",
                json={
                    "content": doc_content,
                    "source_name": "auth.md",
                    "tenant_id": "org_cyber",
                    "offline": True,
                    "save_to_repo": True,
                    "sync_index": True,
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] == 2
            assert data["concepts"][0]["tenant_id"] == "org_cyber"

            # 2. Tenants endpoint lists org_cyber
            resp_tenants = client.get("/api/v1/tenants")
            assert resp_tenants.status_code == 200
            assert "org_cyber" in resp_tenants.json()

            # 3. Scoped search via Header X-Tenant-ID
            resp_search_cyber = client.get(
                "/api/v1/concepts?query=authentication",
                headers={"X-Tenant-ID": "org_cyber"},
            )
            assert resp_search_cyber.status_code == 200
            assert len(resp_search_cyber.json()) >= 1

            resp_search_other = client.get(
                "/api/v1/concepts?query=authentication",
                headers={"X-Tenant-ID": "org_other"},
            )
            assert resp_search_other.status_code == 200
            assert len(resp_search_other.json()) == 0

            # 4. Get concept scoped to tenant
            resp_get = client.get(
                "/api/v1/concepts/user_authentication",
                headers={"X-Tenant-ID": "org_cyber"},
            )
            assert resp_get.status_code == 200
            assert resp_get.json()["id"] == "user_authentication"
            assert resp_get.json()["tenant_id"] == "org_cyber"


def test_mcp_multitenant_tools():
    import asyncio

    with tempfile.TemporaryDirectory() as tmpdir:
        repo = GitRepo(tmpdir)
        fm = OKFFileManager(repo)
        cache = SQLiteQueryCache(":memory:")

        # Add concepts
        c = OKFConcept(
            id="compliance_rules",
            tenant_id="legal_dept",
            type="Policy",
            title="GDPR Compliance",
            body="# GDPR Compliance\n\nData retention limits.",
        )
        fm.save_concept(c)
        cache.insert_or_update_concept(c)

        mcp = create_mcp_server(repo=repo, cache=cache)

        # FastMCP exposes tools
        tools = asyncio.run(mcp.list_tools())
        tool_names = {t.name for t in tools}
        assert "list_tenants" in tool_names
        assert "get_concept" in tool_names

        # Test list_tenants tool
        tenants_res = asyncio.run(mcp.call_tool("list_tenants", {}))
        if isinstance(tenants_res, list) and tenants_res:
            assert "legal_dept" in tenants_res[0].text
        else:
            assert "legal_dept" in str(tenants_res)

        # Test get_concept tool with tenant_id
        concept_res = asyncio.run(mcp.call_tool("get_concept", {"node_id": "compliance_rules", "tenant_id": "legal_dept"}))
        if isinstance(concept_res, list) and concept_res:
            assert "GDPR Compliance" in concept_res[0].text
        elif isinstance(concept_res, dict):
            assert concept_res.get("title") == "GDPR Compliance"

        # Wrong tenant returns error
        err_res = asyncio.run(mcp.call_tool("get_concept", {"node_id": "compliance_rules", "tenant_id": "other_dept"}))
        if isinstance(err_res, list) and err_res:
            assert "not found" in err_res[0].text.lower() or "error" in err_res[0].text.lower()
        elif isinstance(err_res, dict):
            assert "error" in err_res


def test_optional_tenant_id_across_all_interfaces():
    """Verify tenant_id is completely optional across CLI, MCP tools, and REST API."""
    import asyncio

    from click.testing import CliRunner

    from mdgraph.cli import main

    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir = Path(tmpdir) / "repo"
        repo = GitRepo(repo_dir)
        fm = OKFFileManager(repo)
        cache_path = Path(tmpdir) / "cache.db"
        cache = SQLiteQueryCache(str(cache_path))

        # Create two concepts in different tenants: one in 'default', one in 'tenant_x'
        c_def = OKFConcept(
            id="root_policy",
            tenant_id="default",
            type="Policy",
            title="Root Company Policy",
            description="Baseline global policy.",
            body="# Root Company Policy\n\nAll staff must follow [Security Guidelines](./security_guidelines.md).",
        )
        c_def.edges = [Edge(source_id="root_policy", target_id="security_guidelines", tenant_id="default")]

        c_sec = OKFConcept(
            id="security_guidelines",
            tenant_id="default",
            type="Guidelines",
            title="Security Guidelines",
            description="Standard security controls.",
            body="# Security Guidelines\n\nUse complex passwords.",
        )

        c_custom = OKFConcept(
            id="custom_widget",
            tenant_id="tenant_x",
            type="Product",
            title="Custom Widget Spec",
            description="Tenant X widget specification.",
            body="# Custom Widget Spec\n\nDetails on the [Widget Component](./widget_comp.md).",
        )
        c_custom.edges = [Edge(source_id="custom_widget", target_id="widget_comp", tenant_id="tenant_x")]

        c_comp = OKFConcept(
            id="widget_comp",
            tenant_id="tenant_x",
            type="Component",
            title="Widget Component",
            description="Internal sub-assembly.",
            body="# Widget Component\n\nInternal gear system.",
        )

        for c in [c_def, c_sec, c_custom, c_comp]:
            fm.save_concept(c)
            cache.insert_or_update_concept(c)

        # -------------------------------------------------------------------
        # 1. MCP Tools: All calls work with tenant_id omitted (None)
        # -------------------------------------------------------------------
        mcp = create_mcp_server(repo=repo, cache=cache)

        # get_concept without tenant_id finds the concept
        res_def = asyncio.run(mcp.call_tool("get_concept", {"node_id": "root_policy"}))
        assert "Root Company Policy" in str(res_def)

        res_custom = asyncio.run(mcp.call_tool("get_concept", {"node_id": "custom_widget"}))
        assert "Custom Widget Spec" in str(res_custom)

        # read_concept_body without tenant_id
        body_res = asyncio.run(mcp.call_tool("read_concept_body", {"node_id": "custom_widget"}))
        assert "Widget Component" in str(body_res)

        # search_knowledge without tenant_id searches across ALL tenants
        s_all = asyncio.run(mcp.call_tool("search_knowledge", {"query": "policy"}))
        assert "Root Company Policy" in str(s_all)

        s_all_custom = asyncio.run(mcp.call_tool("search_knowledge", {"query": "Widget"}))
        assert "Custom Widget Spec" in str(s_all_custom)

        # traverse_graph without tenant_id auto-detects root tenant
        trav_res = asyncio.run(mcp.call_tool("traverse_graph", {"node_id": "custom_widget"}))
        assert "widget_comp" in str(trav_res)

        # find_path without tenant_id
        path_res = asyncio.run(mcp.call_tool("find_path", {"source_id": "custom_widget", "target_id": "widget_comp"}))
        assert "found" in str(path_res).lower()

        # list_concepts without tenant_id returns all concepts
        list_res = asyncio.run(mcp.call_tool("list_concepts", {}))
        assert "root_policy" in str(list_res)
        assert "custom_widget" in str(list_res)

        # get_graph_stats without tenant_id
        stats_res = asyncio.run(mcp.call_tool("get_graph_stats", {}))
        assert "total_concepts" in str(stats_res)

        # -------------------------------------------------------------------
        # 2. REST API: Endpoints work without tenant_id / X-Tenant-ID
        # -------------------------------------------------------------------
        app = create_rest_api(repo=repo, cache=cache)
        with TestClient(app) as client:
            # GET /api/v1/concepts without tenant lists concepts from all workspaces
            resp_concepts = client.get("/api/v1/concepts")
            assert resp_concepts.status_code == 200
            ids = [item["id"] for item in resp_concepts.json()]
            assert "root_policy" in ids
            assert "custom_widget" in ids

            # GET /api/v1/concepts/{node_id} without tenant loads from whichever workspace
            resp_single_def = client.get("/api/v1/concepts/root_policy")
            assert resp_single_def.status_code == 200
            assert resp_single_def.json()["id"] == "root_policy"

            resp_single_custom = client.get("/api/v1/concepts/custom_widget")
            assert resp_single_custom.status_code == 200
            assert resp_single_custom.json()["id"] == "custom_widget"
            assert resp_single_custom.json()["tenant_id"] == "tenant_x"

            # Graph traversal endpoint without tenant
            resp_trav = client.get("/api/v1/graph/traverse/custom_widget")
            assert resp_trav.status_code == 200
            assert resp_trav.json()["tenant_id"] == "tenant_x"

            # Graph paths endpoint without tenant
            resp_paths = client.get("/api/v1/graph/paths?source=custom_widget&target=widget_comp")
            assert resp_paths.status_code == 200
            assert resp_paths.json()["found"] is True

            # Graph stats endpoint without tenant
            resp_stats = client.get("/api/v1/graph/stats")
            assert resp_stats.status_code == 200
            assert resp_stats.json()["total_concepts"] >= 4

        # -------------------------------------------------------------------
        # 3. CLI: Commands execute successfully without --tenant
        # -------------------------------------------------------------------
        runner = CliRunner()
        cfg_file = Path(tmpdir) / "config.yaml"
        cfg_file.write_text(f"repo_path: '{repo_dir}'\ncache_path: '{cache_path}'\n")

        # cli query without --tenant
        res_q = runner.invoke(main, ["query", "Policy", "-c", str(cfg_file)])
        assert res_q.exit_code == 0
        assert "root_policy" in res_q.output

        # cli traverse without --tenant
        res_t = runner.invoke(main, ["traverse", "root_policy", "-c", str(cfg_file)])
        assert res_t.exit_code == 0
        assert "security_guidelines" in res_t.output

        # cli show without --tenant
        res_s = runner.invoke(main, ["show", "custom_widget", "-c", str(cfg_file)])
        assert res_s.exit_code == 0
        assert "Custom Widget Spec" in res_s.output

        # cli stats without --tenant
        res_st = runner.invoke(main, ["stats", "-c", str(cfg_file)])
        assert res_st.exit_code == 0
        assert "Total Concepts" in res_st.output
