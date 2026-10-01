from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import api
from app.classifier import RELATIONS, EvidenceRelationClassifier, RelationDecision
from app.graph_service import GraphService
from app.intervention import (
    build_intervention_context,
    decide_intervention,
    run_evidence_check,
)
from app.judgement import create_coding
from app.responses import load_response
from app.stages import derive_stage
from app.views import resolve_response_id

ASSESSMENT_ID = "C-JUN25-8464C1H-02_3"
CANDIDATE_ID = "A"
DETAIL_4A = "ms_02_3-detail-4a"
POINT_4 = "ms_02_3-point-4"
POINT_5 = "ms_02_3-point-5"
POINT_6 = "ms_02_3-point-6"


class FakeClassifier(EvidenceRelationClassifier):
    name = "fake"

    def __init__(self, relation: str = "SUPPORTS", needs_review: bool = False) -> None:
        self.relation = relation
        self.needs_review = needs_review

    def classify(self, evidence_text: str, criterion: dict, context: dict) -> RelationDecision:
        probabilities = {item: 0.0 for item in RELATIONS}
        probabilities[self.relation] = 0.55 if self.needs_review else 0.9
        if self.relation != "UNCERTAIN":
            probabilities["UNCERTAIN"] = 0.1
        return RelationDecision(
            evidence_id=context.get("evidence_id", "evidence"),
            criterion_id=criterion["id"],
            relation=self.relation,
            probability=probabilities[self.relation],
            confidence=probabilities[self.relation],
            probabilities=probabilities,
            classifier=self.name,
            model="fake",
            evidence_text=evidence_text,
            start_char=context.get("start_char"),
            end_char=context.get("end_char"),
            context_node_ids=list(context.get("context_node_ids", [])),
            needs_review=self.needs_review,
        )


@pytest.fixture
def graph_service():
    return GraphService.from_data_dir(data_dir="data", assessment_id=ASSESSMENT_ID)


@pytest.fixture
def response_record():
    response_id = resolve_response_id("data", ASSESSMENT_ID, CANDIDATE_ID)
    return load_response(response_id, responses_dir=Path("data/responses"))


@pytest.fixture
def sample_span(response_record):
    text = response_record["text"]
    start_char = 0
    end_char = 40
    return {
        "start_char": start_char,
        "end_char": end_char,
        "text": text[start_char:end_char],
    }


@pytest.fixture
def client(tmp_path):
    api._graph_service.cache_clear()
    api._evidence_pipeline.cache_clear()
    api.JUDGEMENTS_DIR = tmp_path / "judgements"
    api.AI_INTERPRETATIONS_DIR = tmp_path / "ai_interpretations"
    api._evidence_classifier_instance = None
    return TestClient(api.app)


@pytest.fixture
def session(client):
    return client.post("/marking-sessions", json={"examiner_id": "Alex Parker"}).json()


def _prefix(session_id: str) -> str:
    return f"/marking-sessions/{session_id}/assessments/{ASSESSMENT_ID}/candidates/{CANDIDATE_ID}"


def _create_coding(client, session, sample_span, criterion_id=POINT_4):
    created = client.post(
        f"{_prefix(session['marking_session_id'])}/judgement/codings",
        json={**sample_span, "criterion_id": criterion_id},
    )
    assert created.status_code == 200
    return created.json()["codings"][0]


def test_derive_stage_orientation():
    assert derive_stage({"relations": [], "tentative_level": None}) == "ORIENTATION"


def test_derive_stage_evidence_mapping():
    assert derive_stage({"relations": [{"id": "rel-1"}], "tentative_level": None}) == "EVIDENCE_MAPPING"


def test_derive_stage_level_judgement():
    assert derive_stage({"relations": [], "tentative_level": {"level": 2}}) == "LEVEL_JUDGEMENT"


def test_detail_4a_context_includes_rejects(graph_service):
    context = build_intervention_context(graph_service, DETAIL_4A)
    relations = {item["relation"] for item in context["items"]}
    assert "REJECTS" in relations
    assert any(item["node_id"] == "commentary_02_3-guidance-21" for item in context["items"])


def test_point_6_context_includes_rule_requires(graph_service):
    context = build_intervention_context(graph_service, POINT_6)
    assert any(item["relation"] == "REQUIRES" for item in context["items"])


def test_policy_reanchor_over_review_with_anchor(graph_service):
    context = build_intervention_context(graph_service, DETAIL_4A)
    decision = {
        "relation": "PARTIALLY_SUPPORTS",
        "needs_review": True,
    }
    result = decide_intervention(decision, context)
    assert result["type"] == "REANCHOR"


def test_policy_review_without_anchor():
    decision = {"relation": "UNCERTAIN", "needs_review": True}
    result = decide_intervention(decision, {"items": []})
    assert result["type"] == "REVIEW"


def test_policy_silence_for_clarifies_only_support(graph_service):
    context = build_intervention_context(graph_service, POINT_4)
    clarifies_only = {
        **context,
        "items": [item for item in context["items"] if item["relation"] == "CLARIFIES"],
    }
    decision = {"relation": "SUPPORTS", "needs_review": False}
    result = decide_intervention(decision, clarifies_only)
    assert result["type"] == "SILENCE"


def test_policy_rejects_support_is_nuance(graph_service):
    context = build_intervention_context(graph_service, DETAIL_4A)
    anchors = [item for item in context["items"] if item["relation"] == "REJECTS"]
    decision = {"relation": "SUPPORTS", "needs_review": False}
    result = decide_intervention(decision, {**context, "items": anchors})
    assert result["type"] == "NUANCE"


def test_ai_check_stores_interpretation(client, session, sample_span, tmp_path, response_record):
    coding = _create_coding(client, session, sample_span)
    api._evidence_classifier_instance = FakeClassifier("PARTIALLY_SUPPORTS")
    response = client.post(
        f"{_prefix(session['marking_session_id'])}/judgement/codings/{coding['id']}/ai-check",
        json={"stage": "EVIDENCE_MAPPING", "last_action": "link_evidence"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["coding_id"] == coding["id"]
    assert payload["intervention"]["type"] in {"CHALLENGE", "REANCHOR", "REVIEW"}
    assert "response_id" not in payload

    stored = json.loads(
        (tmp_path / "ai_interpretations" / session["marking_session_id"] / f"{response_record['response_id']}.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(stored["interpretations"]) == 1


def test_ai_check_silence_stored_as_silent(client, session, sample_span):
    coding = _create_coding(client, session, sample_span, criterion_id=POINT_5)
    api._evidence_classifier_instance = FakeClassifier("SUPPORTS")
    response = client.post(
        f"{_prefix(session['marking_session_id'])}/judgement/codings/{coding['id']}/ai-check",
        json={"last_action": "link_evidence"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "silent"
    assert response.json()["intervention"]["type"] == "SILENCE"


def test_ai_check_error_does_not_touch_judgement(client, session, sample_span, tmp_path, response_record):
    coding = _create_coding(client, session, sample_span)
    before = (
        tmp_path / "judgements" / session["marking_session_id"] / f"{response_record['response_id']}.json"
    ).read_bytes()

    class BrokenClassifier(EvidenceRelationClassifier):
        name = "broken"

        def classify(self, evidence_text: str, criterion: dict, context: dict) -> RelationDecision:
            raise RuntimeError("jev unavailable")

    api._evidence_classifier_instance = BrokenClassifier()
    response = client.post(
        f"{_prefix(session['marking_session_id'])}/judgement/codings/{coding['id']}/ai-check",
        json={"last_action": "link_evidence"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "error"
    after = (
        tmp_path / "judgements" / session["marking_session_id"] / f"{response_record['response_id']}.json"
    ).read_bytes()
    assert before == after


def test_dismiss_and_explore(client, session, sample_span):
    coding = _create_coding(client, session, sample_span, criterion_id=DETAIL_4A)
    api._evidence_classifier_instance = FakeClassifier("DOES_NOT_SUPPORT")
    created = client.post(
        f"{_prefix(session['marking_session_id'])}/judgement/codings/{coding['id']}/ai-check",
        json={"last_action": "link_evidence"},
    ).json()
    ai_id = created["id"]

    dismissed = client.patch(
        f"{_prefix(session['marking_session_id'])}/ai-interpretations/{ai_id}",
        json={"status": "dismissed"},
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "dismissed"

    api._evidence_classifier_instance = FakeClassifier("DOES_NOT_SUPPORT")
    recreated = client.post(
        f"{_prefix(session['marking_session_id'])}/judgement/codings/{coding['id']}/ai-check",
        json={"last_action": "link_evidence"},
    ).json()
    explored = client.patch(
        f"{_prefix(session['marking_session_id'])}/ai-interpretations/{recreated['id']}",
        json={"status": "explore"},
    )
    assert explored.status_code == 200
    assert explored.json()["status"] == "explore"
    assert explored.json()["explore_context"]["criterion_id"] == DETAIL_4A


def test_span_recheck_supersedes_previous(client, session, sample_span, response_record):
    coding = _create_coding(client, session, sample_span)
    api._evidence_classifier_instance = FakeClassifier("PARTIALLY_SUPPORTS")
    first = client.post(
        f"{_prefix(session['marking_session_id'])}/judgement/codings/{coding['id']}/ai-check",
        json={"last_action": "link_evidence"},
    ).json()

    new_start = 50
    new_end = 90
    patched = client.patch(
        f"{_prefix(session['marking_session_id'])}/judgement/codings/{coding['id']}",
        json={
            "start_char": new_start,
            "end_char": new_end,
            "text": response_record["text"][new_start:new_end],
        },
    )
    assert patched.status_code == 200

    api._evidence_classifier_instance = FakeClassifier("SUPPORTS")
    second = client.post(
        f"{_prefix(session['marking_session_id'])}/judgement/codings/{coding['id']}/ai-check",
        json={"last_action": "revise_coding"},
    ).json()
    assert second["id"] != first["id"]

    listed = client.get(f"{_prefix(session['marking_session_id'])}/ai-interpretations").json()
    active_ids = [item["id"] for item in listed["interpretations"]]
    assert second["id"] in active_ids
    assert first["id"] not in active_ids
