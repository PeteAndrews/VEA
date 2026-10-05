from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app import api
from app.classifier import EvidenceRelationClassifier, RelationDecision
from app.conversation import (
    ConversationStore,
    FakeConversationLLM,
    OpenAIConversationLLM,
    PromptLoader,
    _conversation_history_for_llm,
    build_conversation_context,
    compact_context_for_llm,
    launch_conversation,
    send_conversation_message,
)
from app.graph_service import GraphService
from app.responses import load_response
from app.views import resolve_response_id

ASSESSMENT_ID = "C-JUN25-8464C1H-02_3"
CANDIDATE_ID = "A"
POINT_4 = "ms_02_3-point-4"
POINT_5 = "ms_02_3-point-5"


class FakeClassifier(EvidenceRelationClassifier):
    name = "fake"

    def __init__(self, relation: str = "PARTIALLY_SUPPORTS") -> None:
        self.relation = relation

    def classify(self, evidence_text: str, criterion: dict, context: dict) -> RelationDecision:
        from app.classifier import RELATIONS

        if "Repeat using fresh water" in evidence_text:
            relation = "SUPPORTS"
        else:
            relation = self.relation
        probabilities = {item: 0.0 for item in RELATIONS}
        probabilities[relation] = 0.9
        probabilities["UNCERTAIN"] = 0.1
        return RelationDecision(
            evidence_id=context.get("evidence_id", "evidence"),
            criterion_id=criterion["id"],
            relation=relation,
            probability=0.9,
            confidence=0.9,
            probabilities=probabilities,
            classifier=self.name,
            model="fake",
            evidence_text=evidence_text,
            start_char=context.get("start_char"),
            end_char=context.get("end_char"),
            context_node_ids=list(context.get("context_node_ids", [])),
            needs_review=False,
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
    api._conversation_llm_instance = FakeConversationLLM("Launch explanation.")
    api._prompt_loader_instance = PromptLoader(prompts_dir=Path("prompts"))
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


def _run_ai_check(client, session, coding_id, relation="PARTIALLY_SUPPORTS"):
    api._evidence_classifier_instance = FakeClassifier(relation)
    response = client.post(
        f"{_prefix(session['marking_session_id'])}/judgement/codings/{coding_id}/ai-check",
        json={"last_action": "link_evidence"},
    )
    assert response.status_code == 200
    return response.json()


def test_build_conversation_context_includes_jev_and_graph(
    graph_service,
    response_record,
    client,
    session,
    sample_span,
):
    coding = _create_coding(client, session, sample_span)
    judgement = client.get(f"{_prefix(session['marking_session_id'])}/judgement").json()
    interpretation = _run_ai_check(client, session, coding["id"])

    context = build_conversation_context(
        graph_service=graph_service,
        record=response_record,
        judgement_state=judgement,
        coding_id=coding["id"],
        source="verify",
        interpretation=interpretation,
    )

    assert context["source"] == "verify"
    assert context["evidence"]["text"]
    assert context["interpretive_context"]["containing_sentence"]
    assert context["criterion"]["id"] == POINT_4
    assert context["jev"]["relation"]
    assert context["graph_context"]["guidance"]
    assert context["examiner_judgement"]["relation"] == "SUPPORTS"
    assert context["interpretation_id"] == interpretation["id"]


def test_compact_context_strips_guidance_quotes(graph_service, response_record, client, session, sample_span):
    coding = _create_coding(client, session, sample_span)
    judgement = client.get(f"{_prefix(session['marking_session_id'])}/judgement").json()
    interpretation = _run_ai_check(client, session, coding["id"])
    context = build_conversation_context(
        graph_service=graph_service,
        record=response_record,
        judgement_state=judgement,
        coding_id=coding["id"],
        source="explore",
        interpretation=interpretation,
    )
    compact = compact_context_for_llm(context)
    assert compact["criterion"]["id"] == context["criterion"]["id"]
    assert compact["criterion"]["text"] == context["criterion"]["text"]
    assert "question" not in compact["graph_context"]
    if compact["graph_context"]["guidance"]:
        assert "text" not in compact["graph_context"]["guidance"][0]
    if compact.get("intervention"):
        assert "message" not in compact["intervention"]
    assert "containing_sentence" not in compact.get("interpretive_context", {})


def test_compact_context_flags_borderline_review(client, session, response_record):
    text = response_record["text"]
    coding = _create_coding(
        client,
        session,
        {"start_char": 42, "end_char": 86, "text": text[42:86]},
        criterion_id="ms_02_3-detail-1a",
    )
    interpretation = _run_ai_check(client, session, coding["id"], relation="SUPPORTS")
    if interpretation["intervention"]["type"] != "REVIEW":
        interpretation = {
            **interpretation,
            "intervention": {
                "type": "REVIEW",
                "reasons": ["low_probability"],
                "message": "Borderline.",
                "nuance_items": [],
            },
        }
    context = build_conversation_context(
        graph_service=GraphService.from_data_dir(data_dir="data", assessment_id=ASSESSMENT_ID),
        record=response_record,
        judgement_state=client.get(f"{_prefix(session['marking_session_id'])}/judgement").json(),
        coding_id=coding["id"],
        source="verify",
        interpretation=interpretation,
    )
    compact = compact_context_for_llm(context)
    assert compact["borderline_link"] is True
    assert compact["borderline_reasons"] == ["low_probability"]
    assert compact["evidence"]["text"] == text[42:86]
    assert "containing_sentence" not in compact["interpretive_context"]


def test_conversation_history_scoped_to_active_context():
    messages = [
        {"role": "assistant", "content": "Old explore reply.", "context_id": "ctx-old"},
        {"role": "user", "content": "Follow up.", "context_id": "ctx-new"},
        {"role": "assistant", "content": "New verify reply.", "context_id": "ctx-new"},
        {"role": "assistant", "content": "Another old reply.", "context_id": "ctx-old"},
    ]
    scoped = _conversation_history_for_llm(messages, context_id="ctx-new")
    assert [item["content"] for item in scoped] == ["Follow up.", "New verify reply."]


def test_prompt_loader_reads_runtime_files():
    loader = PromptLoader(prompts_dir=Path("prompts"))
    system = loader.load_system()
    explore = loader.load_launch("explore")
    verify = loader.load_launch("verify")
    assert "colleague marking alongside" in system.lower()
    assert "first person" in system.lower()
    assert "explore" in explore.lower()
    assert "verify" in verify.lower()


def test_launch_and_persist_one_conversation(client, session, sample_span, tmp_path, response_record):
    coding = _create_coding(client, session, sample_span)
    interpretation = _run_ai_check(client, session, coding["id"])

    explore = client.post(
        f"{_prefix(session['marking_session_id'])}/conversation/launch",
        json={
            "source": "explore",
            "coding_id": coding["id"],
            "interpretation_id": interpretation["id"],
        },
    )
    assert explore.status_code == 200
    explore_payload = explore.json()
    assert explore_payload["active_context"]["source"] == "explore"
    assert len(explore_payload["messages"]) == 1
    conversation_id = explore_payload["conversation_id"]

    verify = client.post(
        f"{_prefix(session['marking_session_id'])}/conversation/launch",
        json={"source": "verify", "coding_id": coding["id"]},
    )
    assert verify.status_code == 200
    verify_payload = verify.json()
    assert verify_payload["conversation_id"] == conversation_id
    assert len(verify_payload["contexts"]) == 2
    assert verify_payload["active_context"]["source"] == "verify"
    assert len(verify_payload["messages"]) == 2

    stored_path = (
        tmp_path
        / "conversations"
        / session["marking_session_id"]
        / f"{response_record['response_id']}.json"
    )
    assert stored_path.is_file()
    stored = json.loads(stored_path.read_text(encoding="utf-8"))
    assert stored["conversation_id"] == conversation_id
    assert len(stored["messages"]) == 2


def test_get_conversation_returns_saved_history(client, session, sample_span):
    coding = _create_coding(client, session, sample_span)
    interpretation = _run_ai_check(client, session, coding["id"])
    client.post(
        f"{_prefix(session['marking_session_id'])}/conversation/launch",
        json={
            "source": "explore",
            "coding_id": coding["id"],
            "interpretation_id": interpretation["id"],
        },
    )

    loaded = client.get(f"{_prefix(session['marking_session_id'])}/conversation")
    assert loaded.status_code == 200
    payload = loaded.json()
    assert payload["active_context"] is not None
    assert len(payload["messages"]) == 1


def test_send_message_appends_assistant_reply(client, session, sample_span):
    coding = _create_coding(client, session, sample_span)
    interpretation = _run_ai_check(client, session, coding["id"])
    client.post(
        f"{_prefix(session['marking_session_id'])}/conversation/launch",
        json={
            "source": "verify",
            "coding_id": coding["id"],
            "interpretation_id": interpretation["id"],
        },
    )

    api._conversation_llm_instance = FakeConversationLLM("Follow-up answer.")
    sent = client.post(
        f"{_prefix(session['marking_session_id'])}/conversation/messages",
        json={"content": "Why does this partially support?"},
    )
    assert sent.status_code == 200, sent.text
    payload = sent.json()
    assert len(payload["messages"]) == 3
    assert payload["messages"][-2]["role"] == "user"
    assert payload["messages"][-1]["role"] == "assistant"
    assert payload["messages"][-1]["content"] == "Follow-up answer."


def test_explore_launch_marks_interpretation_explored(client, session, sample_span):
    coding = _create_coding(client, session, sample_span)
    interpretation = _run_ai_check(client, session, coding["id"])
    assert interpretation["status"] == "pending"

    launched = client.post(
        f"{_prefix(session['marking_session_id'])}/conversation/launch",
        json={
            "source": "explore",
            "coding_id": coding["id"],
            "interpretation_id": interpretation["id"],
        },
    )
    assert launched.status_code == 200

    listed = client.get(f"{_prefix(session['marking_session_id'])}/ai-interpretations").json()
    updated = next(item for item in listed["interpretations"] if item["id"] == interpretation["id"])
    assert updated["status"] == "explore"


def test_general_launch_without_coding(client, session):
    launched = client.post(
        f"{_prefix(session['marking_session_id'])}/conversation/launch",
        json={"source": "general"},
    )
    assert launched.status_code == 200
    payload = launched.json()
    assert payload["active_context"]["source"] == "general"
    assert payload["active_context"]["assessment_overview"]


def test_verify_available_for_silent_interpretation(client, session, sample_span):
    coding = _create_coding(client, session, sample_span, criterion_id=POINT_5)
    interpretation = _run_ai_check(client, session, coding["id"], relation="SUPPORTS")
    assert interpretation["status"] == "silent"

    launched = client.post(
        f"{_prefix(session['marking_session_id'])}/conversation/launch",
        json={"source": "verify", "coding_id": coding["id"]},
    )
    assert launched.status_code == 200
    assert launched.json()["active_context"]["source"] == "verify"


def test_launch_rejects_missing_interpretation(client, session, sample_span):
    coding = _create_coding(client, session, sample_span)
    response = client.post(
        f"{_prefix(session['marking_session_id'])}/conversation/launch",
        json={"source": "verify", "coding_id": coding["id"]},
    )
    assert response.status_code == 422


def test_conversation_does_not_mutate_judgement(client, session, sample_span, tmp_path, response_record):
    coding = _create_coding(client, session, sample_span)
    interpretation = _run_ai_check(client, session, coding["id"])
    before = (
        tmp_path / "judgements" / session["marking_session_id"] / f"{response_record['response_id']}.json"
    ).read_bytes()

    client.post(
        f"{_prefix(session['marking_session_id'])}/conversation/launch",
        json={
            "source": "explore",
            "coding_id": coding["id"],
            "interpretation_id": interpretation["id"],
        },
    )
    client.post(
        f"{_prefix(session['marking_session_id'])}/conversation/messages",
        json={"content": "Should this be full marks?"},
    )

    after = (
        tmp_path / "judgements" / session["marking_session_id"] / f"{response_record['response_id']}.json"
    ).read_bytes()
    assert before == after


def test_openai_response_parsing_with_httpx_mock():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "output_text": "Parsed assistant output.",
    }
    client = MagicMock(spec=httpx.Client)
    client.post.return_value = mock_response

    llm = OpenAIConversationLLM(api_key="test-key", client=client)
    text = llm.respond(
        system_prompt="system",
        launch_prompt="launch",
        active_context={"source": "verify"},
        messages=[],
    )
    assert text == "Parsed assistant output."
    client.post.assert_called_once()


def test_fake_llm_records_calls(tmp_path, graph_service, response_record, client, session, sample_span):
    coding = _create_coding(client, session, sample_span)
    judgement = client.get(f"{_prefix(session['marking_session_id'])}/judgement").json()
    interpretation = _run_ai_check(client, session, coding["id"])
    store = ConversationStore(tmp_path / "conversations")
    llm = FakeConversationLLM("Unit test reply.")
    loader = PromptLoader(prompts_dir=Path("prompts"))

    launch_conversation(
        conversation_store=store,
        llm=llm,
        prompt_loader=loader,
        graph_service=graph_service,
        record=response_record,
        judgement_state=judgement,
        assessment_id=ASSESSMENT_ID,
        source="explore",
        coding_id=coding["id"],
        interpretation=interpretation,
    )
    assert llm.calls[0]["active_context"]["source"] == "explore"
    assert "colleague marking alongside" in llm.calls[0]["system_prompt"].lower()

    payload = store.load(session["marking_session_id"], response_record["response_id"])
    send_conversation_message(
        conversation_store=store,
        llm=llm,
        prompt_loader=loader,
        marking_session_id=session["marking_session_id"],
        response_id=response_record["response_id"],
        content="Explain the nuance.",
    )
    assert len(llm.calls) == 2
    assert llm.calls[1]["messages"][-1]["content"] == "Explain the nuance."


def test_follow_up_uses_only_active_context_history(
    tmp_path, graph_service, response_record, client, session, sample_span
):
    coding_a = _create_coding(client, session, sample_span, criterion_id=POINT_4)
    text = response_record["text"]
    coding_b = _create_coding(
        client,
        session,
        {"start_char": 212, "end_char": 333, "text": text[212:333]},
        criterion_id=POINT_5,
    )
    interpretation_a = _run_ai_check(client, session, coding_a["id"])
    interpretation_b = _run_ai_check(client, session, coding_b["id"])

    store = ConversationStore(tmp_path / "conversations")
    llm = FakeConversationLLM("Scoped follow-up.")
    loader = PromptLoader(prompts_dir=Path("prompts"))
    judgement = client.get(f"{_prefix(session['marking_session_id'])}/judgement").json()

    launch_conversation(
        conversation_store=store,
        llm=llm,
        prompt_loader=loader,
        graph_service=graph_service,
        record=response_record,
        judgement_state=judgement,
        assessment_id=ASSESSMENT_ID,
        source="explore",
        coding_id=coding_a["id"],
        interpretation=interpretation_a,
    )
    launch_conversation(
        conversation_store=store,
        llm=llm,
        prompt_loader=loader,
        graph_service=graph_service,
        record=response_record,
        judgement_state=judgement,
        assessment_id=ASSESSMENT_ID,
        source="verify",
        coding_id=coding_b["id"],
        interpretation=interpretation_b,
    )
    send_conversation_message(
        conversation_store=store,
        llm=llm,
        prompt_loader=loader,
        marking_session_id=session["marking_session_id"],
        response_id=response_record["response_id"],
        content="Does this hold up?",
    )
    history = llm.calls[-1]["messages"]
    assert all("Old explore" not in item["content"] for item in history)
    assert history[-1]["content"] == "Does this hold up?"
