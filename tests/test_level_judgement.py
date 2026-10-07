from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import api
from app.classifier import RELATIONS, EvidenceRelationClassifier, RelationDecision
from app.graph_service import GraphService
from app.interpretation_store import AIInterpretationStore, active_level_interpretation
from app.judgement import create_coding, set_tentative_level
from app.level_classifier import FakeLevelJudgementClassifier
from app.level_judgement import run_level_check
from app.responses import load_response
from app.views import levels_view, resolve_response_id

ASSESSMENT_ID = "C-JUN25-8464C1H-02_3"
CANDIDATE_ID = "A"
POINT_6 = "ms_02_3-point-6"


class FakeEvidenceClassifier(EvidenceRelationClassifier):
    name = "fake"

    def classify(self, evidence_text: str, criterion: dict, context: dict) -> RelationDecision:
        relation = "SUPPORTS"
        probabilities = {item: 0.0 for item in RELATIONS}
        probabilities[relation] = 0.9
        return RelationDecision(
            evidence_id="evidence",
            criterion_id=criterion["id"],
            relation=relation,
            probability=0.9,
            confidence=0.9,
            probabilities=probabilities,
            classifier=self.name,
            model="fake",
            evidence_text=evidence_text,
        )


@pytest.fixture
def graph_service():
    return GraphService.from_data_dir(data_dir="data", assessment_id=ASSESSMENT_ID)


@pytest.fixture
def response_record():
    response_id = resolve_response_id("data", ASSESSMENT_ID, CANDIDATE_ID)
    return load_response(response_id, responses_dir=Path("data/responses"))


@pytest.fixture
def client(tmp_path):
    api._graph_service.cache_clear()
    api._evidence_pipeline.cache_clear()
    api.JUDGEMENTS_DIR = tmp_path / "judgements"
    api.AI_INTERPRETATIONS_DIR = tmp_path / "ai_interpretations"
    api.CONVERSATIONS_DIR = tmp_path / "conversations"
    api._evidence_classifier_instance = FakeEvidenceClassifier()
    api._level_classifier_instance = FakeLevelJudgementClassifier("ALIGNS")
    api._conversation_llm_instance = None
    api._prompt_loader_instance = None
    return TestClient(api.app)


@pytest.fixture
def session(client):
    return client.post("/marking-sessions", json={"examiner_id": "Alex Parker"}).json()


def _prefix(session_id: str) -> str:
    return f"/marking-sessions/{session_id}/assessments/{ASSESSMENT_ID}/candidates/{CANDIDATE_ID}"


def test_level_check_requires_tentative_level(client, session):
    sid = session["marking_session_id"]
    response = client.post(f"{_prefix(sid)}/judgement/tentative-level/ai-check", json={})
    assert response.status_code == 422


def test_level_check_challenge_when_point_6_missing(client, session, response_record):
    sid = session["marking_session_id"]
    client.put(f"{_prefix(sid)}/judgement/tentative-level", json={"level": 3})
    response = client.post(f"{_prefix(sid)}/judgement/tentative-level/ai-check", json={})
    assert response.status_code == 200
    payload = response.json()
    assert payload["intervention"]["type"] == "CHALLENGE"
    assert payload["verdict"]["alignment"] == "PARTIALLY_ALIGNS"
    assert any("Missing requirement" in item for item in payload["summary"]["needs_attention"])


def test_level_check_supersedes_on_fingerprint_change(graph_service, response_record, tmp_path):
    levels = levels_view(graph_service, "data")["levels"]
    state = {
        "marking_session_id": "ms-test",
        "assessment_id": ASSESSMENT_ID,
        "response_id": response_record["response_id"],
        "evidence_spans": [],
        "relations": [],
        "tentative_level": None,
    }
    set_tentative_level(state, levels, 3, examiner_id="examiner")
    store = AIInterpretationStore(tmp_path / "ai_interpretations")
    payload = store.load("ms-test", response_record["response_id"])

    first = run_level_check(
        classifier=FakeLevelJudgementClassifier("ALIGNS"),
        evidence_classifier=FakeEvidenceClassifier(),
        graph_service=graph_service,
        record=response_record,
        judgement_state=state,
        ai_payload=payload,
        data_dir="data",
        stage="LEVEL_JUDGEMENT",
        stage_source="test",
    )
    store.add_level(payload, first)
    store.save(payload)

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
    payload = store.load("ms-test", response_record["response_id"])
    second = run_level_check(
        classifier=FakeLevelJudgementClassifier("ALIGNS"),
        evidence_classifier=FakeEvidenceClassifier(),
        graph_service=graph_service,
        record=response_record,
        judgement_state=state,
        ai_payload=payload,
        data_dir="data",
        stage="LEVEL_JUDGEMENT",
        stage_source="test",
    )
    store.add_level(payload, second)
    store.save(payload)

    active = active_level_interpretation(payload, state)
    assert active["id"] == second["id"]
    superseded = [item for item in payload["level_interpretations"] if item["status"] == "superseded"]
    assert len(superseded) == 1


def test_uncoded_candidates_do_not_upgrade_verdict(graph_service, response_record, tmp_path):
    levels = levels_view(graph_service, "data")["levels"]
    state = {
        "marking_session_id": "ms-test",
        "assessment_id": ASSESSMENT_ID,
        "response_id": response_record["response_id"],
        "evidence_spans": [],
        "relations": [],
        "tentative_level": None,
    }
    set_tentative_level(state, levels, 3, examiner_id="examiner")
    payload = AIInterpretationStore(tmp_path / "ai").load("ms-test", response_record["response_id"])
    interpretation = run_level_check(
        classifier=FakeLevelJudgementClassifier("ALIGNS"),
        evidence_classifier=FakeEvidenceClassifier(),
        graph_service=graph_service,
        record=response_record,
        judgement_state=state,
        ai_payload=payload,
        data_dir="data",
        stage="LEVEL_JUDGEMENT",
        stage_source="test",
    )
    assert interpretation["verdict"]["alignment"] == "PARTIALLY_ALIGNS"
    assert interpretation["intervention"]["type"] == "CHALLENGE"
