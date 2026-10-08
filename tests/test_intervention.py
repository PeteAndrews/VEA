from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import api
from app.classifier import RELATIONS, EvidenceRelationClassifier, RelationDecision, build_jev_state
from app.graph_service import GraphService
from app.evidence import build_response_local_context_for_span
from app.intervention import (
    _expansion_candidates,
    _search_additional_evidence,
    build_intervention_context,
    decide_intervention,
    intervention_needs_review,
    nuance_items,
    popup_guidance_items,
    reanchor_items,
    run_evidence_check,
)
from app.judgement import create_coding
from app.responses import load_response
from app.stages import derive_stage
from app.views import resolve_response_id

ASSESSMENT_ID = "C-JUN25-8464C1H-02_3"
BIOLOGY_ASSESSMENT_ID = "B-JUN24-84612H-05_6"
CANDIDATE_ID = "A"
BIOLOGY_ANSWER_DETAIL_ID = "ms_05_6-contraception-detail-fsh"
DETAIL_1A = "ms_02_3-detail-1a"
DETAIL_2A = "ms_02_3-detail-2a"
DETAIL_3B = "ms_02_3-detail-3b"
DETAIL_4A = "ms_02_3-detail-4a"
POINT_4 = "ms_02_3-point-4"
POINT_5 = "ms_02_3-point-5"
POINT_6 = "ms_02_3-point-6"


class FakeClassifier(EvidenceRelationClassifier):
    name = "fake"

    def __init__(
        self,
        relation: str = "SUPPORTS",
        *,
        needs_review: bool = False,
    ) -> None:
        self.relation = relation
        self.needs_review = needs_review

    def classify(self, evidence_text: str, criterion: dict, context: dict) -> RelationDecision:
        if "Repeat using fresh water" in evidence_text:
            relation = "SUPPORTS"
            probability = 0.9
        elif self.needs_review and "using a measuring cylinder" in evidence_text:
            relation = "SUPPORTS"
            probability = 0.9
        elif self.needs_review and evidence_text.strip().startswith("cylinder and pour"):
            relation = "SUPPORTS"
            probability = 0.55
        else:
            relation = self.relation
            probability = 0.55 if self.needs_review else 0.9
        probabilities = {item: 0.0 for item in RELATIONS}
        probabilities[relation] = probability
        if relation == "SUPPORTS" and self.needs_review and probability < 0.6:
            probabilities["PARTIALLY_SUPPORTS"] = 0.39
        if relation != "UNCERTAIN":
            probabilities["UNCERTAIN"] = 0.01
        return RelationDecision(
            evidence_id=context.get("evidence_id", "evidence"),
            criterion_id=criterion["id"],
            relation=relation,
            probability=probabilities[relation],
            confidence=probabilities[relation],
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
    api.CONVERSATIONS_DIR = tmp_path / "conversations"
    api._evidence_classifier_instance = None
    api._conversation_llm_instance = None
    api._prompt_loader_instance = None
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


def test_biology_answer_detail_context_includes_parent_key_step():
    graph_service = GraphService.from_data_dir(data_dir="data", assessment_id=BIOLOGY_ASSESSMENT_ID)
    context = build_intervention_context(graph_service, BIOLOGY_ANSWER_DETAIL_ID)
    assert context["criterion"]["id"] == BIOLOGY_ANSWER_DETAIL_ID
    assert context["criterion"]["segment_type"] == "answer_detail"
    assert context["parent_criterion"]["id"] == "ms_05_6-contraception-point-1"


def test_detail_4a_context_includes_rejects(graph_service):
    context = build_intervention_context(graph_service, DETAIL_4A)
    relations = {item["relation"] for item in context["items"]}
    assert "REJECTS" in relations
    assert any(item["node_id"] == "commentary_02_3-guidance-21" for item in context["items"])


def test_point_6_context_includes_rule_requires(graph_service):
    context = build_intervention_context(graph_service, POINT_6)
    assert any(item["relation"] == "REQUIRES" for item in context["items"])


def test_point_4_context_includes_parsed_alternatives(graph_service):
    context = build_intervention_context(graph_service, POINT_4)
    criterion = context["criterion"]
    assert criterion["alternatives"]
    assert "highest temperature reached by the mixture" in criterion["primary"]
    assert any("set time period" in alt for alt in criterion["alternatives"])


def test_jev_state_notes_alternatives_for_or_criterion(graph_service):
    context = build_intervention_context(graph_service, POINT_4)
    state = build_jev_state(
        "Record the highest temperature reached.",
        context["criterion"],
        {"guidance": context["guidance"], "response_context": {}},
    )
    assert "alternatives_note" in state["criterion_context"]
    assert state["criterion_context"]["criterion"]["alternatives"]


def _decision(
    relation: str,
    *,
    probability: float = 0.90,
    probabilities: dict[str, float] | None = None,
    needs_review: bool = False,
) -> dict:
    if probabilities is None:
        probabilities = {item: 0.0 for item in RELATIONS}
        probabilities[relation] = probability
        if relation != "UNCERTAIN":
            probabilities["UNCERTAIN"] = 0.05
    return {
        "relation": relation,
        "probability": probability,
        "probabilities": probabilities,
        "needs_review": needs_review,
    }


def test_policy_reanchor_over_review_with_anchor(graph_service):
    context = build_intervention_context(graph_service, DETAIL_4A)
    decision = _decision(
        "PARTIALLY_SUPPORTS",
        probability=0.72,
        probabilities={
            "SUPPORTS": 0.08,
            "PARTIALLY_SUPPORTS": 0.72,
            "DOES_NOT_SUPPORT": 0.15,
            "UNCERTAIN": 0.05,
        },
        needs_review=True,
    )
    assert intervention_needs_review(decision) is False
    result = decide_intervention(decision, context)
    assert result["type"] == "REANCHOR"


def test_policy_review_without_anchor():
    decision = _decision("UNCERTAIN", probability=0.55, needs_review=True)
    result = decide_intervention(decision, {"items": []})
    assert result["type"] == "REVIEW"
    assert "jev_uncertain" in result["reasons"]


def test_policy_review_low_probability():
    decision = _decision(
        "SUPPORTS",
        probability=0.55,
        probabilities={
            "SUPPORTS": 0.55,
            "PARTIALLY_SUPPORTS": 0.30,
            "DOES_NOT_SUPPORT": 0.10,
            "UNCERTAIN": 0.05,
        },
    )
    assert intervention_needs_review(decision) is True
    result = decide_intervention(decision, {"items": []})
    assert result["type"] == "REVIEW"
    assert "low_probability" in result["reasons"]


def test_policy_review_close_top_two():
    decision = _decision(
        "SUPPORTS",
        probability=0.62,
        probabilities={
            "SUPPORTS": 0.62,
            "PARTIALLY_SUPPORTS": 0.50,
            "DOES_NOT_SUPPORT": 0.05,
            "UNCERTAIN": 0.03,
        },
    )
    assert intervention_needs_review(decision) is True
    result = decide_intervention(decision, {"items": []})
    assert result["type"] == "REVIEW"
    assert "close_probabilities" in result["reasons"]


def test_policy_supports_clear_margin_ignores_diagnostic_needs_review():
    decision = _decision(
        "SUPPORTS",
        probability=0.67,
        probabilities={
            "SUPPORTS": 0.67,
            "PARTIALLY_SUPPORTS": 0.33,
            "DOES_NOT_SUPPORT": 0.0,
            "UNCERTAIN": 0.0,
        },
        needs_review=True,
    )
    assert intervention_needs_review(decision) is False
    result = decide_intervention(decision, {"items": []})
    assert result["type"] == "SILENCE"


def test_policy_silence_for_clarifies_only_support(graph_service):
    context = build_intervention_context(graph_service, POINT_4)
    clarifies_only = {
        **context,
        "items": [item for item in context["items"] if item["relation"] == "CLARIFIES"],
    }
    decision = _decision("SUPPORTS")
    result = decide_intervention(decision, clarifies_only)
    assert result["type"] == "SILENCE"


def test_policy_rejects_support_is_nuance(graph_service):
    context = build_intervention_context(graph_service, DETAIL_4A)
    anchors = [item for item in context["items"] if item["relation"] == "REJECTS"]
    decision = _decision("SUPPORTS")
    result = decide_intervention(decision, {**context, "items": anchors})
    assert result["type"] == "NUANCE"


def test_reanchor_items_direct_only(graph_service):
    detail_4a = build_intervention_context(graph_service, DETAIL_4A)
    detail_2a = build_intervention_context(graph_service, DETAIL_2A)
    assert reanchor_items(detail_4a)
    assert not reanchor_items(detail_2a)


def test_parent_only_anchor_uncertain_is_review_not_reanchor(graph_service):
    context = build_intervention_context(graph_service, DETAIL_2A)
    decision = _decision("UNCERTAIN", probability=0.55, needs_review=True)
    result = decide_intervention(decision, context)
    assert result["type"] == "REVIEW"


def test_parent_constrains_support_is_silence_for_child_detail(graph_service):
    context = build_intervention_context(graph_service, DETAIL_2A)
    decision = _decision("SUPPORTS")
    result = decide_intervention(decision, context)
    assert result["type"] == "SILENCE"
    assert not nuance_items(context)


def test_parent_rejects_in_context_but_not_popup_for_stir_detail(graph_service):
    context = build_intervention_context(graph_service, DETAIL_3B)
    assert any(
        item["scope"] == "parent" and item["relation"] == "REJECTS"
        for item in context["items"]
    )
    assert not popup_guidance_items(context)
    decision = _decision(
        "SUPPORTS",
        probability=0.67,
        probabilities={
            "SUPPORTS": 0.67,
            "PARTIALLY_SUPPORTS": 0.21,
            "DOES_NOT_SUPPORT": 0.11,
            "UNCERTAIN": 0.01,
        },
    )
    result = decide_intervention(decision, context)
    assert result["type"] == "SILENCE"


def test_response_local_context_includes_containing_sentence(response_record):
    text = response_record["text"]
    start_char = text.index("record the starting temperature")
    end_char = start_char + len("record the starting temperature")
    local = build_response_local_context_for_span(
        response_record,
        start_char=start_char,
        end_char=end_char,
    )
    assert local["containing_segment"]["text"] == "Use a thermometer to record the starting temperature."
    assert local["containing_sentence"] == "Use a thermometer to record the starting temperature."
    assert "context only" in local["note"]


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


def test_expansion_candidates_include_containing_sentence(response_record):
    text = response_record["text"]
    interpretive = build_response_local_context_for_span(
        response_record,
        start_char=42,
        end_char=86,
    )
    candidates = _expansion_candidates(
        response_record,
        start_char=42,
        end_char=86,
        interpretive_context=interpretive,
    )
    assert candidates
    assert candidates[0]["expansion"] == "containing_sentence"
    assert candidates[0]["start_char"] < 42
    assert "measuring cylinder" in candidates[0]["text"]
    assert text[42:86] in candidates[0]["text"]


def test_expansion_candidates_prefers_following_first(response_record):
    interpretive = build_response_local_context_for_span(
        response_record,
        start_char=212,
        end_char=333,
    )
    candidates = _expansion_candidates(
        response_record,
        start_char=212,
        end_char=333,
        interpretive_context=interpretive,
    )
    assert candidates
    assert candidates[0]["expansion"] == "following"
    assert "Repeat using fresh water" in candidates[0]["text"]


def test_search_additional_evidence_finds_minimal_following_span(
    graph_service, response_record
):
    interpretive = build_response_local_context_for_span(
        response_record,
        start_char=212,
        end_char=333,
    )
    graph_context = build_intervention_context(graph_service, POINT_5)
    suggested, jev = _search_additional_evidence(
        FakeClassifier("DOES_NOT_SUPPORT"),
        record=response_record,
        criterion=graph_context["criterion"],
        jev_context_base={
            "evidence_id": "span-212-333",
            "start_char": 212,
            "end_char": 333,
            "context_node_ids": graph_context["context_node_ids"],
            "parent_criterion": graph_context["parent_criterion"],
            "guidance": graph_context["guidance"],
            "question": graph_context["question"],
        },
        start_char=212,
        end_char=333,
        interpretive_context=interpretive,
    )
    assert suggested is not None
    assert suggested["expansion"] == "following"
    assert jev["relation"] == "SUPPORTS"
    assert "Repeat using fresh water" in suggested["text"]
    assert "Record the highest temperature" in suggested["text"]


def test_ai_check_supported_with_additional_evidence(client, session, response_record):
    text = response_record["text"]
    span = {
        "start_char": 212,
        "end_char": 333,
        "text": text[212:333],
    }
    coding = _create_coding(client, session, span, criterion_id=POINT_5)
    api._evidence_classifier_instance = FakeClassifier("DOES_NOT_SUPPORT")
    payload = client.post(
        f"{_prefix(session['marking_session_id'])}/judgement/codings/{coding['id']}/ai-check",
        json={"last_action": "link_evidence"},
    ).json()
    assert payload["jev_direct"]["relation"] == "DOES_NOT_SUPPORT"
    assert payload["jev_additional"]["relation"] == "SUPPORTS"
    assert payload["additional_evidence"]["searched"] is True
    assert payload["additional_evidence"]["found"] is True
    assert payload["additional_evidence"]["expansion"] == "following"
    assert payload["interpretive_context"]["following_segment"]["text"].startswith("Repeat using")
    assert payload["suggested_evidence_span"]["expansion"] == "following"
    assert payload["intervention"]["type"] == "SUPPORTED_WITH_ADDITIONAL_EVIDENCE"


def test_ai_check_borderline_supports_finds_containing_sentence(client, session, response_record):
    text = response_record["text"]
    span = {
        "start_char": 42,
        "end_char": 86,
        "text": text[42:86],
    }
    coding = _create_coding(client, session, span, criterion_id=DETAIL_1A)
    api._evidence_classifier_instance = FakeClassifier("SUPPORTS", needs_review=True)
    payload = client.post(
        f"{_prefix(session['marking_session_id'])}/judgement/codings/{coding['id']}/ai-check",
        json={"last_action": "link_evidence"},
    ).json()
    assert payload["jev_direct"]["relation"] == "SUPPORTS"
    assert payload["additional_evidence"]["searched"] is True
    assert payload["additional_evidence"]["found"] is True
    assert payload["additional_evidence"]["expansion"] == "containing_sentence"
    assert "measuring cylinder" in payload["suggested_evidence_span"]["text"]
    assert payload["intervention"]["type"] == "SUPPORTED_WITH_ADDITIONAL_EVIDENCE"


def test_ai_check_strong_direct_skips_additional_search(client, session, sample_span):
    coding = _create_coding(client, session, sample_span, criterion_id=POINT_5)
    api._evidence_classifier_instance = FakeClassifier("SUPPORTS")
    payload = client.post(
        f"{_prefix(session['marking_session_id'])}/judgement/codings/{coding['id']}/ai-check",
        json={"last_action": "link_evidence"},
    ).json()
    assert payload["jev_direct"]["relation"] == "SUPPORTS"
    assert payload["additional_evidence"]["searched"] is False
    assert payload["jev_additional"] is None
    assert payload["status"] == "silent"


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
