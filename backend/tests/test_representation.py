from __future__ import annotations

from pathlib import Path

import pytest

from app.graph_service import GraphService
from app.judgement import JudgementStore, create_coding, set_tentative_level
from app.representation.instance import load_instance
from app.representation.judgement_graph import JudgementGraph, compute_overlaps
from app.representation.labels import EXAMINER_RELATIONS
from app.representation.response_graph import ResponseGraph
from app.responses import load_response
from app.views import levels_view, resolve_response_id

ASSESSMENT_ID = "C-JUN25-8464C1H-02_3"
CANDIDATE_ID = "A"


@pytest.fixture
def response_record():
    response_id = resolve_response_id("data", ASSESSMENT_ID, CANDIDATE_ID)
    return load_response(response_id, responses_dir=Path("data/responses"))


def test_response_graph_from_record(response_record):
    graph = ResponseGraph.from_record(response_record)
    assert graph.response_id == response_record["response_id"]
    assert len(graph.segments) == len(response_record["segments"])
    relations = {edge.relation for edge in graph.edges}
    assert "PART_OF" in relations
    assert "NEXT" in relations


def test_judgement_graph_overlaps(response_record):
    response_graph = ResponseGraph.from_record(response_record)
    span = {
        "id": "span-0-40",
        "response_id": response_record["response_id"],
        "start_char": 0,
        "end_char": 40,
        "text": response_record["text"][0:40],
    }
    from app.representation.judgement_graph import EvidenceSpanNode

    overlaps = compute_overlaps(
        [EvidenceSpanNode(**span)],
        response_graph.segments,
    )
    assert overlaps
    assert overlaps[0].overlap_chars > 0


def test_create_coding_partial_supports(response_record, tmp_path):
    graph_service = GraphService.from_data_dir(data_dir="data", assessment_id=ASSESSMENT_ID)
    store = JudgementStore(tmp_path / "judgements")
    state = store.load("ms-test", ASSESSMENT_ID, response_record["response_id"])
    state["marking_session_id"] = "ms-test"
    state["assessment_id"] = ASSESSMENT_ID
    relation = create_coding(
        state,
        response_record,
        graph_service,
        start_char=0,
        end_char=40,
        text=response_record["text"][0:40],
        criterion_id="ms_02_3-point-4",
        examiner_id="examiner",
        relation="PARTIALLY_SUPPORTS",
    )
    assert relation["relation"] == "PARTIALLY_SUPPORTS"
    assert "PARTIALLY_SUPPORTS" in EXAMINER_RELATIONS


def test_load_instance_assessment_only():
    instance = load_instance(data_dir="data", assessment_id=ASSESSMENT_ID)
    assert instance.assessment.assessment_id == ASSESSMENT_ID
    assert instance.response is None
    assert instance.judgement is None


def test_load_instance_with_response(response_record):
    instance = load_instance(
        data_dir="data",
        assessment_id=ASSESSMENT_ID,
        response_id=response_record["response_id"],
    )
    assert instance.response is not None
    assert instance.judgement is None


def test_judgement_graph_from_state(response_record, tmp_path):
    graph_service = GraphService.from_data_dir(data_dir="data", assessment_id=ASSESSMENT_ID)
    store = JudgementStore(tmp_path / "judgements")
    state = store.load("ms-j", ASSESSMENT_ID, response_record["response_id"])
    state["marking_session_id"] = "ms-j"
    state["assessment_id"] = ASSESSMENT_ID
    create_coding(
        state,
        response_record,
        graph_service,
        start_char=0,
        end_char=40,
        text=response_record["text"][0:40],
        criterion_id="ms_02_3-point-4",
        examiner_id="examiner",
    )
    levels = levels_view(graph_service, "data")["levels"]
    set_tentative_level(state, levels, 2, examiner_id="examiner")
    response_graph = ResponseGraph.from_record(response_record)
    judgement = JudgementGraph.from_state(state, response_graph=response_graph)
    assert len(judgement.spans) == 1
    assert len(judgement.links) == 1
    assert judgement.tentative_level is not None
    assert judgement.tentative_level.level == 2
