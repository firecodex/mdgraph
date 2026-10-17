"""Unit tests for SQLite FTS5 and Recursive CTE Vectorless Query Cache."""

from mdgraph.models import Edge, OKFConcept


def test_sqlite_cache_upsert_and_get(sqlite_cache, sample_okf_concept):
    sqlite_cache.insert_or_update_concept(sample_okf_concept)
    retrieved = sqlite_cache.get_concept(sample_okf_concept.id)

    assert retrieved is not None
    assert retrieved["id"] == "remote_work_policy"
    assert retrieved["type"] == "Policy"
    assert "hardware" in retrieved["tags"]
    assert len(retrieved["outgoing_edges"]) == 2


def test_sqlite_cache_bm25_search(sqlite_cache, sample_okf_concept):
    sqlite_cache.insert_or_update_concept(sample_okf_concept)

    # Search keyword in description or body
    results = sqlite_cache.search("stipend")
    assert len(results) >= 1
    assert results[0].id == "remote_work_policy"

    # Search with tag filter
    tag_results = sqlite_cache.search("hardware", tags=["hr"])
    assert len(tag_results) >= 1

    # Search non-matching term
    assert len(sqlite_cache.search("nonexistent_keyword_xyz")) == 0


def test_sqlite_recursive_cte_traversal(sqlite_cache):
    # Create graph: A -> B -> C -> D, and A -> E
    # Cycle test: C -> A
    concepts = [
        OKFConcept(id="node_a", type="Concept", title="Node A", body="Links to [Node B](./node_b.md) and [Node E](./node_e.md)"),
        OKFConcept(id="node_b", type="Concept", title="Node B", body="Links to [Node C](./node_c.md)"),
        OKFConcept(id="node_c", type="Concept", title="Node C", body="Links to [Node D](./node_d.md) and [Node A](./node_a.md)"),
        OKFConcept(id="node_d", type="Concept", title="Node D", body="Leaf node."),
        OKFConcept(id="node_e", type="Concept", title="Node E", body="Leaf branch."),
    ]
    for c in concepts:
        c.edges = OKFConcept.extract_links(c.id, c.body)
        sqlite_cache.insert_or_update_concept(c)

    # Traverse depth=1 from A: should get B and E
    t1 = sqlite_cache.traverse("node_a", max_depth=1)
    reachable_1 = {n["id"] for n in t1.nodes if not n.get("is_root")}
    assert reachable_1 == {"node_b", "node_e"}

    # Traverse depth=2 from A: should reach B, E, C
    t2 = sqlite_cache.traverse("node_a", max_depth=2)
    reachable_2 = {n["id"] for n in t2.nodes if not n.get("is_root")}
    assert "node_c" in reachable_2

    # Traverse depth=3 from A: should reach D (A -> B -> C -> D)
    t3 = sqlite_cache.traverse("node_a", max_depth=3)
    reachable_3 = {n["id"] for n in t3.nodes if not n.get("is_root")}
    assert "node_d" in reachable_3

    # Incoming traversal: from D, reverse CTE should reach C, B, A
    t_in = sqlite_cache.traverse("node_d", max_depth=3, direction="in")
    reached_in = {n["id"] for n in t_in.nodes if not n.get("is_root")}
    assert "node_c" in reached_in
    assert "node_b" in reached_in
    assert "node_a" in reached_in


def test_sqlite_find_path(sqlite_cache):
    # Setup chain: start -> mid -> end
    c1 = OKFConcept(id="start_node", type="Concept", title="Start", body="Links to [Mid](./mid_node.md)")
    c2 = OKFConcept(id="mid_node", type="Concept", title="Mid", body="Links to [End](./end_node.md)")
    c3 = OKFConcept(id="end_node", type="Concept", title="End", body="Destination")

    for c in (c1, c2, c3):
        c.edges = OKFConcept.extract_links(c.id, c.body)
        sqlite_cache.insert_or_update_concept(c)

    path = sqlite_cache.find_path("start_node", "end_node", max_depth=4)
    assert path == ["start_node", "mid_node", "end_node"]

    no_path = sqlite_cache.find_path("end_node", "start_node", max_depth=4)
    assert no_path is None


def test_sqlite_stats(sqlite_cache, sample_okf_concept):
    sqlite_cache.insert_or_update_concept(sample_okf_concept)
    stats = sqlite_cache.get_stats()

    assert stats.total_concepts == 1
    assert stats.total_edges == 2
    assert stats.concept_types.get("Policy") == 1
    assert "hardware" in stats.top_tags
