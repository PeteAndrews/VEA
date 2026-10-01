from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import app
from app.graph import JEV_LABELS, load_graph
from app.graph_service import GraphService


@pytest.fixture
def graph():
    return load_graph(data_dir="data")


@pytest.fixture
def service(graph):
    return GraphService(graph)


def test_graph_construction(graph):
    assert len(graph.nodes) == 48
    assert graph.edge_count >= 23

    assessment_edges = [
        e for edges in graph.out_edges.values() for e in edges if e["kind"] == "assessment"
    ]
    assert len(assessment_edges) == 23

    for node_id, (node_type, pyg_index) in graph.index.items():
        stored_id = graph.data[node_type].node_id[pyg_index]
        assert stored_id == node_id
        assert graph.data[node_type].segment_type[pyg_index] == graph.nodes[node_id]["segment_type"]

    assert list(graph.data.jev_labels) == list(JEV_LABELS)
    assert graph.jev_labels == JEV_LABELS


def test_segment_type_preserved(graph):
    node = graph.nodes["ms_02_3-indicative-content"]
    assert node["node_type"] == "mark_point"
    assert node["segment_type"] == "indicative_content_group"
    assert node["structural_only"] is True
    assert graph.nodes["commentary_02_3-heading-1"]["structural_only"] is True
    assert graph.nodes["ms_02_3-point-4"]["structural_only"] is False


def test_next_edges_are_sibling_order_only(graph):
    next_edges = [
        e for edges in graph.out_edges.values() for e in edges if e["relation"] == "NEXT"
    ]
    assert next_edges

    for edge in next_edges:
        source = graph.nodes[edge["source"]]
        target = graph.nodes[edge["target"]]
        assert source["document_id"] == target["document_id"]
        assert source.get("parent_id") == target.get("parent_id")
        assert edge["source_order"] < edge["target_order"]
        assert target["order"] - source["order"] >= 1


def test_point_4_accepts_relationship(service):
    node = service.get_node("ms_02_3-point-4")
    assert node["node_type"] == "mark_point"
    assert node["segment_type"] == "indicative_point"

    incoming = service.get_incoming("ms_02_3-point-4", relation="ACCEPTS")
    assert len(incoming) == 1
    edge = incoming[0]
    assert edge["source"] == "commentary_02_3-guidance-23"
    assert edge["llm_confidence"] == 1.0
    assert edge["jev_relation"] == "ACCEPTS"
    assert edge["jev_probabilities"]["ACCEPTS"] == pytest.approx(0.98)


def test_level_3_and_rule_relationships(service):
    applies = service.get_incoming("ms_02_3-level-3", relation="APPLIES_TO")
    assert len(applies) == 1
    assert applies[0]["source"] == "ms_02_3-level-rule-3"
    assert applies[0]["llm_confidence"] == pytest.approx(0.99)
    assert applies[0]["jev_relation"] == "CLARIFIES"
    assert applies[0]["agreement"] is False
    assert applies[0]["needs_review"] is True
    assert len(applies[0]["jev_probabilities"]) == len(JEV_LABELS)

    requires = service.get_outgoing("ms_02_3-level-rule-3", relation="REQUIRES")
    assert len(requires) == 1
    assert requires[0]["target"] == "ms_02_3-point-6"


def test_context_hides_structural_only_nodes(service):
    context = service.get_context("ms_02_3-point-4")
    assert context["parent"] is None
    assert len(context["children"]) == 1
    assert context["children"][0]["id"] == "ms_02_3-detail-4a"

    with_structural = service.get_context("ms_02_3-point-4", include_structural=True)
    assert with_structural["parent"]["id"] == "ms_02_3-indicative-content"
    assert with_structural["parent"]["structural_only"] is True


def test_find_path_level_3_to_point_6(service):
    path = service.find_path("ms_02_3-level-3", "ms_02_3-point-6", kind="assessment")
    assert path is not None
    assert len(path) == 2
    assert path[0]["source"] == "ms_02_3-level-rule-3"
    assert path[0]["target"] == "ms_02_3-level-3"
    assert path[0]["relation"] == "APPLIES_TO"
    assert path[1]["source"] == "ms_02_3-level-rule-3"
    assert path[1]["target"] == "ms_02_3-point-6"
    assert path[1]["relation"] == "REQUIRES"
    assert all(step["kind"] == "assessment" for step in path)

    structural_path = service.find_path("ms_02_3-level-3", "ms_02_3-point-6", kind="structural")
    assert structural_path is not None
    assert all(step["kind"] == "structural" for step in structural_path)


def test_neighbors_kind_filter(service):
    structural = service.get_neighbors("ms_02_3-point-4", kind="structural")
    assert structural
    assert all(item["kind"] == "structural" for item in structural)

    assessment = service.get_neighbors("ms_02_3-point-4", kind="assessment")
    assert assessment
    assert all(item["kind"] == "assessment" for item in assessment)
    assert not service.get_neighbors("ms_02_3-level-3", kind="assessment", relation="NEXT")


def test_api_health_and_not_found():
    client = TestClient(app)
    health = client.get("/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"
    assert body["node_count"] == 48
    assert body["jev_labels"] == list(JEV_LABELS)

    missing = client.get("/graph/nodes/does-not-exist")
    assert missing.status_code == 404
