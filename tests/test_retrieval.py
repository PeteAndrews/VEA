from __future__ import annotations

from pathlib import Path

import pytest
import torch

from app.graph import load_graph
from app.responses import (
    attach_response_to_graph,
    ingest_response_file,
    load_response,
    segment_response_text,
)
from app.retrieval import EMBED_DIM, RetrievalService, is_retrieval_eligible, scope_matches

pytest.importorskip("sentence_transformers")

RESPONSE_TXT = Path("data/responses/JUN25-8464C1H-02_3_response-higher-ambiguity.txt")
RESPONSE_ID = "JUN25-8464C1H-02_3_response-higher-ambiguity"


@pytest.fixture
def ingested_response(tmp_path):
    responses_dir = tmp_path / "responses"
    record = ingest_response_file(RESPONSE_TXT, responses_dir=responses_dir)
    return record, tmp_path


def test_segment_response_text_offsets():
    text = RESPONSE_TXT.read_text(encoding="utf-8")
    segments = segment_response_text(text)
    assert len(segments) == 7
    assert "maximum temperature" in segments[2]["text"].lower()
    assert "subtract" in segments[3]["text"].lower()
    assert "2 g, 3 g, 4 g and 5 g" in segments[4]["text"]
    for segment in segments:
        assert text[segment["start_char"] : segment["end_char"]] == segment["text"]


def test_response_graph_nodes(ingested_response):
    record, _data_dir = ingested_response
    graph = load_graph(data_dir="data")
    attach_response_to_graph(graph, record)

    seg1 = f"{RESPONSE_ID}-seg-1"
    seg2 = f"{RESPONSE_ID}-seg-2"
    assert graph.nodes[seg1]["start_char"] is not None
    assert graph.nodes[seg1]["end_char"] is not None
    assert graph.nodes[seg1]["node_type"] == "response"
    assert graph.nodes[RESPONSE_ID]["structural_only"] is True

    next_edges = [edge for edge in graph.out_edges[seg1] if edge["relation"] == "NEXT"]
    assert len(next_edges) == 1
    assert next_edges[0]["target"] == seg2


def test_scope_membership():
    graph = load_graph(data_dir="data")
    nodes = graph.nodes

    assert scope_matches(nodes["ms_02_3-point-4"], "criteria")
    assert not scope_matches(nodes["ms_02_3-point-4"], "commentary")
    assert scope_matches(nodes["commentary_02_3-guidance-23"], "commentary")
    assert not scope_matches(nodes["commentary_02_3-guidance-23"], "criteria")
    assert scope_matches(nodes["q_02_3-instruction-1"], "question")
    assert not scope_matches(nodes["q_02_3-instruction-1"], "criteria")
    assert not scope_matches(nodes["ms_02_3-indicative-content"], "all")
    assert is_retrieval_eligible(nodes["q_02_3-stimulus-1"])


def _segment_id(record: dict, needle: str) -> str:
    for segment in record["segments"]:
        if needle.lower() in segment["text"].lower():
            return segment["id"]
    raise AssertionError(f"No segment containing {needle!r}")


@pytest.mark.slow
def test_embeddings_cache_scopes_and_retrieval(monkeypatch):
    monkeypatch.setenv("VEA_EMBED_DEVICE", "cpu")
    data_dir = Path("data")
    responses_dir = data_dir / "responses"
    cache_dir = data_dir / "cache"
    responses_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    record = ingest_response_file(RESPONSE_TXT, responses_dir=responses_dir)

    retrieval = RetrievalService.from_data_dir(data_dir=data_dir)
    assert retrieval._retrieval_embeddings is not None
    assert retrieval._retrieval_embeddings.shape[1] == EMBED_DIM

    for node_type in retrieval.graph.data.node_types:
        if node_type == "response":
            continue
        store = retrieval.graph.data[node_type]
        assert store.emb.shape == (int(store.num_nodes), EMBED_DIM)
        assert store.retrieval_mask.shape == (int(store.num_nodes),)
        if store.retrieval_mask.any():
            assert store.emb[store.retrieval_mask].norm(dim=1).min() > 0
            assert torch.all(store.emb[~store.retrieval_mask] == 0)

    criteria_ids, _ = retrieval._scoped_embeddings("criteria")
    commentary_ids, _ = retrieval._scoped_embeddings("commentary")
    question_ids, _ = retrieval._scoped_embeddings("question")
    assert "ms_02_3-point-4" in criteria_ids
    assert "commentary_02_3-guidance-23" in commentary_ids
    assert "q_02_3-instruction-1" in question_ids
    assert "q_02_3-instruction-1" not in criteria_ids

    second = RetrievalService.from_data_dir(data_dir=data_dir, response_id=RESPONSE_ID)
    second._embed_and_save_response(record)

    max_temp_seg = _segment_id(record, "maximum temperature")
    subtract_seg = _segment_id(record, "subtract")
    repeat_mass_seg = _segment_id(record, "2 g, 3 g, 4 g")

    max_result = second.similar(max_temp_seg, top_k=3, scope="criteria")
    assert max_result["scope"] == "criteria"
    assert max_result["matches"][0]["node_id"] == "ms_02_3-point-4"
    assert max_result["matches"][0]["cosine_similarity"] >= max_result["matches"][1]["cosine_similarity"]

    subtract_result = second.similar(subtract_seg, top_k=3, scope="criteria")
    subtract_ids = [match["node_id"] for match in subtract_result["matches"]]
    assert subtract_ids[0] == "ms_02_3-detail-4a"

    repeat_result = second.similar(repeat_mass_seg, top_k=3, scope="criteria")
    repeat_ids = [match["node_id"] for match in repeat_result["matches"]]
    assert repeat_ids[0] == "ms_02_3-point-5"

    all_result = second.similar(max_temp_seg, top_k=10, scope="all")
    all_node_types = {match["node_type"] for match in all_result["matches"]}
    assert "question" in all_node_types or "commentary" in all_node_types

    context = second.response_context(max_temp_seg, top_k=3, scope="criteria")
    point_match = next(item for item in context["matches"] if item["node_id"] == "ms_02_3-point-4")
    assert "ACCEPTS" in point_match["context"]["incoming"]
    assert context["scope"] == "criteria"
    assert all(match["retrieval"] == "candidate" for match in context["matches"])
