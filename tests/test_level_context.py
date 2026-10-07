from __future__ import annotations

from pathlib import Path

import pytest

from app.graph_service import GraphService
from app.interpretation_store import AIInterpretationStore
from app.judgement import create_coding, set_tentative_level
from app.level_context import build_level_judgement_context, build_rule_coverage
from app.responses import load_response
from app.views import levels_view, resolve_response_id

ASSESSMENT_ID = "C-JUN25-8464C1H-02_3"
CANDIDATE_ID = "A"
POINT_6 = "ms_02_3-point-6"


@pytest.fixture
def graph_service():
    return GraphService.from_data_dir(data_dir="data", assessment_id=ASSESSMENT_ID)


@pytest.fixture
def response_record():
    response_id = resolve_response_id("data", ASSESSMENT_ID, CANDIDATE_ID)
    return load_response(response_id, responses_dir=Path("data/responses"))


def _empty_state(response_record):
    return {
        "marking_session_id": "ms-test",
        "assessment_id": ASSESSMENT_ID,
        "response_id": response_record["response_id"],
        "evidence_spans": [],
        "relations": [],
        "tentative_level": None,
    }


def test_rule_coverage_marks_point_6_unsatisfied_for_level_3(graph_service):
    levels = levels_view(graph_service, "data")["levels"]
    state = _empty_state({"response_id": "resp"})
    set_tentative_level(state, levels, 3, examiner_id="examiner")
    from app.judgement import level_context_view

    level_context = level_context_view(graph_service, "data", 3, state=state)
    coverage = build_rule_coverage(level_context)
    point_6 = next(item for item in coverage if item["criterion_id"] == POINT_6)
    assert point_6["satisfied"] is False
    assert point_6["rule_text"]


def test_build_level_context_excludes_uncoded_candidates(graph_service, response_record):
    levels = levels_view(graph_service, "data")["levels"]
    state = _empty_state(response_record)
    set_tentative_level(state, levels, 3, examiner_id="examiner")
    create_coding(
        state,
        response_record,
        graph_service,
        start_char=0,
        end_char=40,
        text=response_record["text"][0:40],
        criterion_id=POINT_6,
        examiner_id="examiner",
    )
    context = build_level_judgement_context(
        graph_service=graph_service,
        record=response_record,
        judgement_state=state,
        ai_payload=AIInterpretationStore(Path("data/ai_interpretations")).load("ms-test", response_record["response_id"]),
        data_dir="data",
        stage="LEVEL_JUDGEMENT",
        stage_source="test",
    )
    assert "uncoded_candidates" not in context
    assert "full_response" in context
    assert "all_level_descriptors" in context
    assert any(item["criterion_id"] == POINT_6 for item in context["rule_coverage"])
