from __future__ import annotations

from pathlib import Path

from app.conversation import ConversationStore, PromptLoader, send_conversation_message
from app.level_conversation import (
    compact_level_context_for_llm,
    is_level_conversation_context,
    process_level_conversation_turn,
)
from app.assistant import process_assistant_turn
from app.graph_service import GraphService
from app.intent import FakeIntentClassifier
from app.responses import load_response
from tests.test_assistant import FakeClassifier, RecordingLLM
from app.views import resolve_response_id

ASSESSMENT_ID = "C-JUN25-8464C1H-02_3"


def _level_context() -> dict:
    return {
        "context_id": "ctx-level",
        "source": "explore_level",
        "kind": "level",
        "level": 3,
        "tentative_level": {"level": 3, "level_node_id": "ms_02_3-level-3"},
        "verdict": {
            "selected_level": 3,
            "best_fit_level": 2,
            "alignment": "ALIGNS",
            "reason": "Mapped evidence supports Level 3.",
            "dimension_coverage": {
                "validity": "Method is valid.",
                "completeness": "Key steps mapped.",
                "logical_sequencing": "Sequence is coherent.",
            },
            "unresolved": [],
        },
        "summary": {
            "level": 3,
            "ai_check_label": "Broadly aligns",
            "evidence_mapped": [
                {"criterion_id": "ms_02_3-point-1", "label": "Measuring water volume"},
            ],
            "needs_attention": [],
            "key_guidance": "Level 3 requires all key steps.",
        },
        "context": {
            "level_descriptor": {"level": 3, "text": "Level 3 descriptor."},
            "rule_coverage": [],
            "key_guidance": "Level 3 requires all key steps.",
            "coded_support": [
                {
                    "criterion_id": "ms_02_3-point-1",
                    "criterion_text": "Measuring water volume",
                    "jev_relation": "SUPPORTS",
                }
            ],
        },
        "intervention": {"type": "NUANCE", "message": "Guidance applies."},
    }


def test_is_level_conversation_context():
    assert is_level_conversation_context(_level_context())
    assert not is_level_conversation_context({"source": "general"})


def test_compact_level_context_for_llm_keeps_level_judgement():
    compact = compact_level_context_for_llm(_level_context())
    assert compact["kind"] == "level"
    assert compact["verdict"]["alignment"] == "ALIGNS"
    assert compact["summary"]["evidence_mapped"][0]["label"] == "Measuring water volume"
    assert compact["judgement_context"]["coded_support"]


def test_level_follow_up_bypasses_intent_clarification():
    llm = RecordingLLM("Level follow-up reply.")
    prompt_loader = PromptLoader(prompts_dir=Path("prompts"))
    active_context = _level_context()
    turn = process_level_conversation_turn(
        active_context=active_context,
        llm=llm,
        prompt_loader=prompt_loader,
        messages=[
            {"role": "assistant", "content": "Level 3 looks plausible.", "context_id": "ctx-level"},
            {
                "role": "user",
                "content": "I don't feel like the evidence I mapped satisfies level three",
                "context_id": "ctx-level",
            },
        ],
        context_id="ctx-level",
    )
    assert turn["clarification_needed"] is False
    assert "Level follow-up reply." in turn["content"]
    assert llm.last_turn_context["kind"] == "level"
    assert llm.last_turn_context["verdict"]["alignment"] == "ALIGNS"
    assert llm.last_messages[-1]["content"].startswith("I don't feel like")


def test_process_assistant_turn_delegates_level_context():
    graph_service = GraphService.from_data_dir(data_dir="data", assessment_id=ASSESSMENT_ID)
    response_record = load_response(
        resolve_response_id("data", ASSESSMENT_ID, "A"),
        responses_dir=Path("data/responses"),
    )
    llm = RecordingLLM("Delegated level reply.")
    turn = process_assistant_turn(
        content="I don't feel like the evidence I mapped satisfies level three",
        active_context=_level_context(),
        graph_service=graph_service,
        record=response_record,
        judgement_state={"relations": [], "evidence_spans": [], "events": []},
        classifier=FakeClassifier(),
        intent_classifier=FakeIntentClassifier(),
        retrieval_service=None,
        llm=llm,
        prompt_loader=PromptLoader(prompts_dir=Path("prompts")),
        history=[
            {"role": "assistant", "content": "Level 3 looks plausible.", "context_id": "ctx-level"},
        ],
    )
    assert turn["clarification_needed"] is False
    assert turn["content"] == "Delegated level reply."
    assert llm.last_turn_context["kind"] == "level"


def test_send_conversation_message_appends_level_reply(tmp_path):
    store = ConversationStore(tmp_path / "conversations")
    level_context = _level_context()
    payload = store.load("ms-test", "resp-test")
    payload["response_id"] = "resp-test"
    payload["marking_session_id"] = "ms-test"
    payload["contexts"] = [level_context]
    payload["active_context_id"] = level_context["context_id"]
    payload["messages"] = [
        {
            "id": "msg-1",
            "role": "assistant",
            "content": "Level 3 looks plausible.",
            "context_id": level_context["context_id"],
            "created_at": "2026-01-01T00:00:00+00:00",
        }
    ]
    store.save(payload)

    llm = RecordingLLM("Level follow-up saved.")
    result = send_conversation_message(
        conversation_store=store,
        llm=llm,
        prompt_loader=PromptLoader(prompts_dir=Path("prompts")),
        marking_session_id="ms-test",
        response_id="resp-test",
        content="I don't feel like the evidence I mapped satisfies level three",
    )
    roles = [message["role"] for message in result["messages"]]
    assert roles == ["assistant", "user", "assistant"]
    assert result["messages"][-1]["content"] == "Level follow-up saved."
