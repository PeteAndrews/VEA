from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import api
from app.classifier import (
    RELATIONS,
    EvidenceRelationClassifier,
    JevEvidenceRelationClassifier,
    RelationDecision,
    compute_needs_review,
    get_typesafe_api_key,
)
from app.evidence import (
    EvidencePipeline,
    EvidenceRef,
    HypothesisStore,
    build_criterion_context,
    build_response_local_context,
)
from app.responses import load_response
from app.graph_service import GraphService

pytest.importorskip("sentence_transformers")

ASSESSMENT_ID = "C-JUN25-8464C1H-02_3"
HIGHER_SEG_3 = "JUN25-8464C1H-02_3_response-higher-ambiguity-seg-3"
HIGHER_SEG_4 = "JUN25-8464C1H-02_3_response-higher-ambiguity-seg-4"
LOW_SEG_1 = "JUN25-8464C1H-02_3_response-low-mark-seg-1"
LOW_SEG_2 = "JUN25-8464C1H-02_3_response-low-mark-seg-2"
LOW_SEG_3 = "JUN25-8464C1H-02_3_response-low-mark-seg-3"
TOP_SEG_4 = "JUN25-8464C1H-02_3_response-top-mark-seg-4"
HIGHER_RESPONSE = "JUN25-8464C1H-02_3_response-higher-ambiguity"
LOW_RESPONSE = "JUN25-8464C1H-02_3_response-low-mark"
TOP_RESPONSE = "JUN25-8464C1H-02_3_response-top-mark"


class FakeEvidenceRelationClassifier(EvidenceRelationClassifier):
    name = "fake"

    def classify(self, evidence_text: str, criterion: dict, context: dict) -> RelationDecision:
        lowered = evidence_text.lower()
        criterion_id = criterion["id"]
        if "subtract" in lowered and criterion_id == "ms_02_3-detail-4a":
            relation = "SUPPORTS"
        elif "spatula" in lowered and criterion_id == "ms_02_3-point-3":
            relation = "DOES_NOT_SUPPORT"
        elif "thermometer" in lowered and criterion_id == "ms_02_3-point-4":
            relation = "PARTIALLY_SUPPORTS"
        else:
            relation = "UNCERTAIN"
        probabilities = {item: 0.0 for item in RELATIONS}
        probabilities[relation] = 0.9
        probabilities["UNCERTAIN"] = 0.1 if relation != "UNCERTAIN" else 0.9
        probability = probabilities[relation]
        confidence = probability
        return RelationDecision(
            evidence_id=context.get("evidence_id", "evidence"),
            criterion_id=criterion_id,
            relation=relation,
            probability=probability,
            confidence=confidence,
            probabilities=probabilities,
            classifier=self.name,
            model="fake",
            evidence_text=evidence_text,
            start_char=context.get("start_char"),
            end_char=context.get("end_char"),
            context_node_ids=list(context.get("context_node_ids", [])),
            needs_review=compute_needs_review(probability, confidence, probabilities),
        )


@pytest.fixture
def graph_service():
    return GraphService.from_data_dir(assessment_id=ASSESSMENT_ID)


@pytest.fixture
def fake_pipeline():
    return EvidencePipeline(
        data_dir="data",
        assessment_id=ASSESSMENT_ID,
        classifier=FakeEvidenceRelationClassifier(),
    )


def _guidance_node_ids(context: dict) -> set[str]:
    return {item["node_id"] for item in context["guidance"]}


def test_build_criterion_context_point_3_includes_rejects(graph_service):
    context = build_criterion_context(graph_service, "ms_02_3-point-3")
    node_ids = _guidance_node_ids(context)
    assert "commentary_02_3-guidance-18" in node_ids
    assert "commentary_02_3-guidance-20" in node_ids
    assert any(item["relation"] == "REJECTS" for item in context["guidance"])


def test_build_criterion_context_point_4_includes_accepts_and_constrains(graph_service):
    context = build_criterion_context(graph_service, "ms_02_3-point-4")
    node_ids = _guidance_node_ids(context)
    assert "commentary_02_3-guidance-23" in node_ids
    assert "commentary_02_3-guidance-22" in node_ids
    relations = {item["relation"] for item in context["guidance"]}
    assert "ACCEPTS" in relations
    assert "CONSTRAINS" in relations


def test_build_criterion_context_rejects_non_criterion(graph_service):
    with pytest.raises(ValueError, match="not a criterion"):
        build_criterion_context(graph_service, "commentary_02_3-guidance-18")


def test_build_response_local_context_includes_neighbors():
    record = load_response(HIGHER_RESPONSE, responses_dir=Path("data/responses"))
    evidence = EvidenceRef(
        evidence_id=HIGHER_SEG_4,
        response_id=HIGHER_RESPONSE,
        text=record["segments"][3]["text"],
        start_char=record["segments"][3]["start_char"],
        end_char=record["segments"][3]["end_char"],
        segment_id=HIGHER_SEG_4,
    )
    local = build_response_local_context(record, evidence)
    assert local["containing_segment"]["segment_id"] == HIGHER_SEG_4
    assert local["containing_sentence"] == record["segments"][3]["text"]
    assert local["preceding_segment"]["segment_id"] == HIGHER_SEG_3
    assert local["following_segment"]["segment_id"] == "JUN25-8464C1H-02_3_response-higher-ambiguity-seg-5"
    assert "context only" in local["note"]


def test_build_response_local_context_for_span():
    record = load_response(TOP_RESPONSE, responses_dir=Path("data/responses"))
    evidence = EvidenceRef(
        evidence_id=f"{TOP_RESPONSE}:212-333",
        response_id=TOP_RESPONSE,
        text=record["text"][212:333],
        start_char=212,
        end_char=333,
    )
    local = build_response_local_context(record, evidence)
    assert local["containing_segment"]["segment_id"] == "JUN25-8464C1H-02_3_response-top-mark-seg-4"
    assert local["containing_sentence"] == record["segments"][3]["text"]
    assert local["preceding_segment"]["segment_id"] == "JUN25-8464C1H-02_3_response-top-mark-seg-3"
    assert local["following_segment"]["segment_id"] == "JUN25-8464C1H-02_3_response-top-mark-seg-5"


def test_compute_needs_review_low_confidence():
    probabilities = {
        "SUPPORTS": 0.45,
        "PARTIALLY_SUPPORTS": 0.35,
        "DOES_NOT_SUPPORT": 0.15,
        "UNCERTAIN": 0.05,
    }
    assert compute_needs_review(0.45, 0.45, probabilities) is True


def test_compute_needs_review_close_top_two():
    probabilities = {
        "SUPPORTS": 0.52,
        "PARTIALLY_SUPPORTS": 0.41,
        "DOES_NOT_SUPPORT": 0.05,
        "UNCERTAIN": 0.02,
    }
    assert compute_needs_review(0.52, 0.52, probabilities) is True


def test_compute_needs_review_clear_winner():
    probabilities = {
        "SUPPORTS": 0.87,
        "PARTIALLY_SUPPORTS": 0.08,
        "DOES_NOT_SUPPORT": 0.02,
        "UNCERTAIN": 0.03,
    }
    assert compute_needs_review(0.87, 0.87, probabilities) is False


def test_resolve_evidence_span(fake_pipeline):
    evidence = fake_pipeline.resolve_evidence(
        response_id=HIGHER_RESPONSE,
        start_char=171,
        end_char=257,
    )
    assert evidence.evidence_id == f"{HIGHER_RESPONSE}:171-257"
    assert "subtract" in evidence.text.lower()


def test_hypothesis_store_upserts_without_duplicates(tmp_path):
    store = HypothesisStore(tmp_path / "hypotheses")
    decision = RelationDecision(
        evidence_id="seg-1",
        criterion_id="ms_02_3-point-4",
        relation="SUPPORTS",
        probability=0.9,
        confidence=0.9,
        probabilities={item: 0.0 for item in RELATIONS} | {"SUPPORTS": 0.9},
        classifier="fake",
        model="fake",
        evidence_text="example",
    )
    store.upsert(HIGHER_RESPONSE, decision)
    updated = RelationDecision(
        evidence_id="seg-1",
        criterion_id="ms_02_3-point-4",
        relation="PARTIALLY_SUPPORTS",
        probability=0.7,
        confidence=0.7,
        probabilities={item: 0.0 for item in RELATIONS} | {"PARTIALLY_SUPPORTS": 0.7},
        classifier="fake",
        model="fake",
        evidence_text="example",
    )
    store.upsert(HIGHER_RESPONSE, updated)
    hypotheses = store.list(HIGHER_RESPONSE)
    assert len(hypotheses) == 1
    assert hypotheses[0]["relation"] == "PARTIALLY_SUPPORTS"


def test_jev_payload_and_parse(monkeypatch):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "model": "jev-latest",
                "answers": {
                    "relation": {
                        "choice": "SUPPORTS",
                        "confidence": 0.87,
                        "probabilities": {
                            "SUPPORTS": 0.87,
                            "PARTIALLY_SUPPORTS": 0.08,
                            "DOES_NOT_SUPPORT": 0.02,
                            "UNCERTAIN": 0.03,
                        },
                    }
                },
            },
        )

    monkeypatch.setenv("TYPESAFE_API_KEY", "jv_live_test")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    classifier = JevEvidenceRelationClassifier(api_key="jv_live_test", client=client)
    context = {
        "evidence_id": "seg-1",
        "start_char": 0,
        "end_char": 10,
        "context_node_ids": ["ms_02_3-point-4"],
        "criterion": {"id": "ms_02_3-point-4", "text": "measure temperature"},
        "parent_criterion": None,
        "guidance": [],
        "question": "Plan a method",
        "response_context": {
            "preceding_segment": {"segment_id": "seg-0", "text": "Stir the mixture."},
            "following_segment": None,
            "note": "Surrounding response segments are context only, not part of the selected evidence.",
        },
    }
    decision = classifier.classify("record max temperature", context["criterion"], context)
    assert decision.relation == "SUPPORTS"
    assert decision.probability == pytest.approx(0.87)
    assert decision.needs_review is False
    assert set(decision.probabilities) == set(RELATIONS)
    state = captured["payload"]["state"]
    assert state["selected_evidence"]["text"] == "record max temperature"
    assert state["response_context"]["preceding_segment"]["text"] == "Stir the mixture."
    assert "context only" in state["response_context"]["note"]
    assert captured["payload"]["questions"]["relation"]["type"] == "choice"


def test_jev_missing_key_raises(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr("app.classifier.load_env_file", lambda *_args, **_kwargs: None)
    with pytest.raises(RuntimeError, match="TYPESAFE_API_KEY"):
        get_typesafe_api_key()


def test_jev_402_raises(monkeypatch):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, text="insufficient credits")

    monkeypatch.setenv("TYPESAFE_API_KEY", "jv_live_test")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    classifier = JevEvidenceRelationClassifier(api_key="jv_live_test", client=client)
    context = {
        "evidence_id": "seg-1",
        "criterion": {"id": "ms_02_3-point-4", "text": "criterion"},
        "parent_criterion": None,
        "guidance": [],
        "question": "Plan a method",
        "context_node_ids": ["ms_02_3-point-4"],
    }
    with pytest.raises(RuntimeError, match="insufficient credits"):
        classifier.classify("text", context["criterion"], context)


def test_cli_classify_span_accepts_trailing_criterion_id():
    from app.cli import build_parser, _resolve_criterion_id, _resolve_evidence_args

    args = build_parser().parse_args(
        [
            "classify",
            "--response-id",
            "JUN25-8464C1H-02_3_response-top-mark",
            "--start",
            "212",
            "--end",
            "333",
            "ms_02_3-point-4",
        ]
    )
    assert _resolve_criterion_id(args) == "ms_02_3-point-4"
    evidence = _resolve_evidence_args(args)
    assert evidence.response_id == "JUN25-8464C1H-02_3_response-top-mark"
    assert evidence.start_char == 212
    assert evidence.end_char == 333


def test_cli_classify_span_accepts_criterion_id_flag():
    from app.cli import build_parser, _resolve_criterion_id

    args = build_parser().parse_args(
        [
            "classify",
            "--response-id",
            "JUN25-8464C1H-02_3_response-top-mark",
            "--start",
            "212",
            "--end",
            "333",
            "--criterion-id",
            "ms_02_3-point-4",
        ]
    )
    assert _resolve_criterion_id(args) == "ms_02_3-point-4"


def test_fake_classify_support(fake_pipeline):
    evidence = fake_pipeline.resolve_evidence_from_segment(HIGHER_SEG_4)
    result = fake_pipeline.classify(evidence, "ms_02_3-detail-4a")
    assert result["relation"] == "SUPPORTS"
    assert result["status"] == "hypothesis"
    assert "needs_review" in result


@pytest.fixture
def api_client(monkeypatch):
    api._evidence_pipeline.cache_clear()

    def pipeline_factory():
        return EvidencePipeline(
            data_dir="data",
            assessment_id=ASSESSMENT_ID,
            classifier=FakeEvidenceRelationClassifier(),
        )

    monkeypatch.setattr(api, "_evidence_pipeline", pipeline_factory)
    return TestClient(api.app)


def test_api_assessment_overview(api_client):
    response = api_client.get(f"/assessments/{ASSESSMENT_ID}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["assessment_id"] == ASSESSMENT_ID
    assert any(item["id"] == "ms_02_3-point-4" for item in payload["criteria"])


def test_api_get_response(api_client):
    response = api_client.get(f"/responses/{HIGHER_RESPONSE}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["response_id"] == HIGHER_RESPONSE
    assert len(payload["segments"]) >= 1


def test_api_criterion_context(api_client):
    response = api_client.get("/criteria/ms_02_3-point-4/context")
    assert response.status_code == 200
    payload = response.json()
    assert payload["classification_context"]["criterion"]["id"] == "ms_02_3-point-4"
    assert "graph_context" in payload


def test_api_classify(api_client):
    response = api_client.post(
        "/classify",
        json={
            "response_id": HIGHER_RESPONSE,
            "segment_id": HIGHER_SEG_4,
            "criterion_id": "ms_02_3-detail-4a",
        },
    )
    assert response.status_code == 200
    assert response.json()["relation"] == "SUPPORTS"


def test_api_classify_validation_error(api_client):
    response = api_client.post(
        "/classify",
        json={
            "response_id": HIGHER_RESPONSE,
            "criterion_id": "ms_02_3-detail-4a",
        },
    )
    assert response.status_code == 422


@pytest.mark.slow
def test_api_candidates(api_client):
    response = api_client.post(
        f"/responses/{HIGHER_RESPONSE}/candidates",
        json={"segment_id": HIGHER_SEG_4, "top_k": 3, "scope": "criteria"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["matches"]) >= 1


def _jev_pipeline():
    if not os.environ.get("TYPESAFE_API_KEY", "").startswith("jv_live_"):
        pytest.skip("TYPESAFE_API_KEY with jv_live_ prefix not set")
    return EvidencePipeline(assessment_id=ASSESSMENT_ID)


@pytest.mark.jev
def test_jev_clear_support_top_mark():
    pipeline = _jev_pipeline()
    evidence = pipeline.resolve_evidence_from_segment(TOP_SEG_4)
    result = pipeline.classify(evidence, "ms_02_3-detail-4a")
    assert result["relation"] in {"SUPPORTS", "PARTIALLY_SUPPORTS"}
    assert result["probabilities"]["DOES_NOT_SUPPORT"] < 0.2
    assert "needs_review" in result


@pytest.mark.jev
def test_jev_clear_support_higher_ambiguity():
    pipeline = _jev_pipeline()
    evidence = pipeline.resolve_evidence_from_segment(HIGHER_SEG_4)
    result = pipeline.classify(evidence, "ms_02_3-detail-4a")
    assert result["relation"] in {"SUPPORTS", "PARTIALLY_SUPPORTS"}
    assert result["probabilities"]["DOES_NOT_SUPPORT"] < 0.2


@pytest.mark.jev
def test_jev_partial_low_mark():
    pipeline = _jev_pipeline()
    evidence = pipeline.resolve_evidence_from_segment(LOW_SEG_2)
    result = pipeline.classify(evidence, "ms_02_3-point-4")
    assert result["relation"] in {"PARTIALLY_SUPPORTS", "UNCERTAIN", "DOES_NOT_SUPPORT"}
    assert result["probabilities"]["SUPPORTS"] < 0.7


@pytest.mark.jev
def test_jev_non_support_spatula_mass():
    pipeline = _jev_pipeline()
    evidence = pipeline.resolve_evidence_from_segment(LOW_SEG_1)
    result = pipeline.classify(evidence, "ms_02_3-point-3")
    assert result["relation"] in {"PARTIALLY_SUPPORTS", "DOES_NOT_SUPPORT", "UNCERTAIN"}
    assert result["probabilities"]["SUPPORTS"] < 0.5


@pytest.mark.jev
def test_jev_non_support_unrelated_criterion():
    pipeline = _jev_pipeline()
    evidence = pipeline.resolve_evidence_from_segment(LOW_SEG_3)
    result = pipeline.classify(evidence, "ms_02_3-detail-2a")
    assert result["relation"] in {"DOES_NOT_SUPPORT", "UNCERTAIN", "PARTIALLY_SUPPORTS"}
    assert result["probabilities"]["SUPPORTS"] < 0.3


@pytest.mark.jev
def test_jev_ambiguous_temperature_only():
    pipeline = _jev_pipeline()
    evidence = pipeline.resolve_evidence_from_segment(HIGHER_SEG_3)
    result = pipeline.classify(evidence, "ms_02_3-point-4")
    assert result["relation"] in {"PARTIALLY_SUPPORTS", "UNCERTAIN", "SUPPORTS", "DOES_NOT_SUPPORT"}
    assert "needs_review" in result
    assert isinstance(result["needs_review"], bool)
