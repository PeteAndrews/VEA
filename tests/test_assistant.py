from __future__ import annotations

from pathlib import Path

from app.assistant import process_assistant_turn
from app.classifier import RELATIONS, EvidenceRelationClassifier, RelationDecision
from app.conversation import FakeConversationLLM, PromptLoader
from app.graph_service import GraphService
from app.intent import FakeIntentClassifier, IntentClassifier
from app.responses import load_response
from app.views import resolve_response_id

ASSESSMENT_ID = "C-JUN25-8464C1H-02_3"
POINT_1 = "ms_02_3-point-1"
POINT_5 = "ms_02_3-point-5"
REPEAT_SENTENCE = "Repeat using fresh water with 2 g, 3 g, 4 g and 5 g of calcium oxide."
VOLUME_SENTENCE = "Use 50 cm³ of water each time and make sure it starts at the same temperature."


class FakeClassifier(EvidenceRelationClassifier):
    name = "fake"

    def classify(self, evidence_text: str, criterion: dict, context: dict) -> RelationDecision:
        if REPEAT_SENTENCE in evidence_text or "2 g, 3 g, 4 g and 5 g" in evidence_text:
            relation = "SUPPORTS" if criterion["id"] == POINT_5 else "PARTIALLY_SUPPORTS"
        elif "50 cm" in evidence_text and "each time" in evidence_text:
            relation = "SUPPORTS" if criterion["id"] == POINT_1 else "PARTIALLY_SUPPORTS"
        elif "measuring cylinder" in evidence_text:
            relation = "SUPPORTS"
        else:
            relation = "PARTIALLY_SUPPORTS"
        probabilities = {item: 0.0 for item in RELATIONS}
        probabilities[relation] = 0.9
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


class FakeRetrievalService:
    def __init__(self, record: dict) -> None:
        self.record = record
        self.segments = {
            segment["id"]: {
                "segment_id": segment["id"],
                "text": segment["text"],
                "start_char": segment["start_char"],
                "end_char": segment["end_char"],
            }
            for segment in record.get("segments", [])
        }

    def search_response(self, response_id: str, query: str, top_k: int = 5) -> dict:
        lower = query.lower()
        if "repeat" in lower or "mass" in lower:
            segment = self.segments[f"{self.record['response_id']}-seg-5"]
        elif "volume" in lower or "measure" in lower:
            segment = self.segments[f"{self.record['response_id']}-seg-6"]
        else:
            segment = next(iter(self.segments.values()))
        return {"query": query, "response_id": response_id, "matches": [segment]}

    def similar_text(self, text: str, top_k: int = 5, scope: str = "criteria") -> dict:
        return {"matches": []}


class RecordingLLM(FakeConversationLLM):
    def __init__(self, response: str = "Turn explanation.") -> None:
        super().__init__(response)
        self.last_turn_context: dict | None = None
        self.last_messages: list[dict[str, Any]] | None = None

    def respond(self, *, system_prompt, launch_prompt, active_context, messages):
        self.last_turn_context = active_context
        self.last_messages = list(messages)
        return super().respond(
            system_prompt=system_prompt,
            launch_prompt=launch_prompt,
            active_context=active_context,
            messages=messages,
        )


def _run_turn(
    *,
    content: str,
    active_context: dict,
    response_record: dict,
    graph_service: GraphService,
    llm,
    retrieval_service=None,
    history=None,
):
    return process_assistant_turn(
        content=content,
        active_context=active_context,
        graph_service=graph_service,
        record=response_record,
        judgement_state={"relations": [], "evidence_spans": [], "events": []},
        classifier=FakeClassifier(),
        intent_classifier=FakeIntentClassifier(),
        retrieval_service=retrieval_service,
        llm=llm,
        prompt_loader=PromptLoader(prompts_dir=Path("prompts")),
        history=history or [],
    )


def test_intent_classifier_routes_assessment_locate_and_find_support():
    classifier = FakeIntentClassifier()
    context = {"source": "general", "has_active_span": False, "has_active_criterion": False}
    assert classifier.classify("Would that be enough for point 4?", context).intent == "ASSESS_LINK"
    assert (
        classifier.classify(
            "Does the student response support the marking point 'repeat with different masses'?",
            context,
        ).intent
        == "FIND_SUPPORT"
    )
    assert (
        classifier.classify("Where does the student mention controlling the water?", context).intent
        == "LOCATE_EVIDENCE"
    )
    assert classifier.classify("What does point 4 mean?", context).intent == "DISCUSS"
    assert (
        classifier.classify(
            "Does the response hold evidence for the indicative content point 'measure volume of water'?",
            context,
        ).intent
        == "FIND_SUPPORT"
    )


def test_ambiguous_intent_asks_for_clarification():
    graph_service = GraphService.from_data_dir(data_dir="data", assessment_id=ASSESSMENT_ID)
    response_record = load_response(
        resolve_response_id("data", ASSESSMENT_ID, "A"),
        responses_dir=Path("data/responses"),
    )
    turn = _run_turn(
        content="This is an ambiguous intent question.",
        active_context={"context_id": "ctx-test", "source": "general", "resolved_references": {}},
        response_record=response_record,
        graph_service=graph_service,
        llm=FakeConversationLLM(),
    )
    assert turn["clarification_needed"] is True
    assert "specific part of the response" in turn["content"]


def test_find_support_repeat_masses_resolves_repeat_sentence_not_stale_temperature_span():
    graph_service = GraphService.from_data_dir(data_dir="data", assessment_id=ASSESSMENT_ID)
    response_record = load_response(
        resolve_response_id("data", ASSESSMENT_ID, "A"),
        responses_dir=Path("data/responses"),
    )
    text = response_record["text"]
    stale_evidence = text[212:333]
    llm = RecordingLLM("Yes, that sentence supports repeating with different masses.")
    active_context = {
        "context_id": "ctx-test",
        "source": "explore",
        "evidence": {
            "text": stale_evidence,
            "start_char": 212,
            "end_char": 333,
        },
        "criterion": {
            "id": POINT_5,
            "text": "• repeat with different masses of calcium oxide",
        },
        "interpretive_context": {
            "following_segment": {
                "text": REPEAT_SENTENCE,
                "start_char": 335,
                "end_char": 404,
            }
        },
        "resolved_references": {},
    }

    turn = _run_turn(
        content="Does the student response support the marking point 'repeat with different masses of calcium oxide'?",
        active_context=active_context,
        response_record=response_record,
        graph_service=graph_service,
        llm=llm,
        retrieval_service=FakeRetrievalService(response_record),
    )

    assert turn["intent"] == "FIND_SUPPORT"
    assert turn["trace"]["resolved_criterion_id"] == POINT_5
    assert turn["trace"]["resolved_span"]["start_char"] == 335
    assert turn["trace"]["resolved_span"]["end_char"] == 404
    assert "2 g, 3 g, 4 g and 5 g" in turn["trace"]["resolved_span"]["text"]
    assert turn["trace"]["jev_relation"] == "SUPPORTS"
    assert turn["resolved_references"]["response_span"]["text"] == REPEAT_SENTENCE
    assert "temperature rise" not in turn["resolved_references"]["response_span"]["text"]
    assert "interpretive_context" not in active_context

    turn_context = llm.last_turn_context
    assert turn_context["intent"] == "FIND_SUPPORT"
    assert turn_context["evidence"]["text"] == REPEAT_SENTENCE
    assert turn_context["criterion"]["id"] == POINT_5
    assert turn_context["assessment"]["relation"] == "SUPPORTS"
    assert stale_evidence not in str(turn_context)


def test_consecutive_find_support_turns_do_not_reuse_previous_span():
    graph_service = GraphService.from_data_dir(data_dir="data", assessment_id=ASSESSMENT_ID)
    response_record = load_response(
        resolve_response_id("data", ASSESSMENT_ID, "A"),
        responses_dir=Path("data/responses"),
    )
    retrieval = FakeRetrievalService(response_record)
    llm = RecordingLLM("Turn explanation.")
    active_context = {
        "context_id": "ctx-test",
        "source": "general",
        "resolved_references": {},
    }

    first = _run_turn(
        content="Does the student response support the marking point 'repeat with different masses of calcium oxide'?",
        active_context=active_context,
        response_record=response_record,
        graph_service=graph_service,
        llm=llm,
        retrieval_service=retrieval,
    )
    assert first["intent"] == "FIND_SUPPORT"
    assert first["resolved_references"]["response_span"]["text"] == REPEAT_SENTENCE

    history = [
        {"role": "user", "content": first["content"] if "content" in first else ""},
        {"role": "assistant", "content": "Yes, the response repeats with 2 g, 3 g, 4 g and 5 g."},
    ]
    second = _run_turn(
        content="Does the response hold evidence for the indicative content point 'measure volume of water'?",
        active_context=active_context,
        response_record=response_record,
        graph_service=graph_service,
        llm=llm,
        retrieval_service=retrieval,
        history=history,
    )

    assert second["intent"] == "FIND_SUPPORT"
    assert second["trace"]["resolved_criterion_id"] == POINT_1
    assert second["trace"]["resolved_span"]["text"] == VOLUME_SENTENCE
    assert "2 g, 3 g, 4 g and 5 g" not in second["resolved_references"]["response_span"]["text"]
    assert second["trace"]["jev_relation"] == "SUPPORTS"
    assert any(citation["type"] == "response_span" for citation in second["citations"])

    turn_context = llm.last_turn_context
    assert turn_context["criterion"]["id"] == POINT_1
    assert turn_context["evidence"]["text"] == VOLUME_SENTENCE
    assert "2 g, 3 g, 4 g and 5 g" not in str(turn_context)
    assert llm.last_messages == [
        {
            "role": "user",
            "content": "Does the response hold evidence for the indicative content point 'measure volume of water'?",
        }
    ]


def test_assessment_explain_omits_prior_assistant_history():
    graph_service = GraphService.from_data_dir(data_dir="data", assessment_id=ASSESSMENT_ID)
    response_record = load_response(
        resolve_response_id("data", ASSESSMENT_ID, "A"),
        responses_dir=Path("data/responses"),
    )
    llm = RecordingLLM("Assessment explanation.")
    history = [
        {
            "role": "user",
            "content": "Does the student response contain evidence for repeat with different masses?",
        },
        {
            "role": "assistant",
            "content": "Yes, Repeat using fresh water with 2 g, 3 g, 4 g and 5 g supports that point.",
        },
    ]
    question = "Does the response hold evidence for the indicative content point 'measure volume of water'?"
    turn = _run_turn(
        content=question,
        active_context={"context_id": "ctx-test", "source": "general", "resolved_references": {}},
        response_record=response_record,
        graph_service=graph_service,
        llm=llm,
        retrieval_service=FakeRetrievalService(response_record),
        history=history,
    )
    assert turn["intent"] == "FIND_SUPPORT"
    assert llm.last_messages == [{"role": "user", "content": question}]
    assert not any(message.get("role") == "assistant" for message in llm.last_messages)


def test_assess_link_uses_assessment_not_intervention():
    graph_service = GraphService.from_data_dir(data_dir="data", assessment_id=ASSESSMENT_ID)
    response_record = load_response(
        resolve_response_id("data", ASSESSMENT_ID, "A"),
        responses_dir=Path("data/responses"),
    )
    turn = _run_turn(
        content="Does the response support using a measuring cylinder?",
        active_context={"context_id": "ctx-test", "source": "general", "resolved_references": {}},
        response_record=response_record,
        graph_service=graph_service,
        llm=FakeConversationLLM("Assessment explanation."),
        retrieval_service=FakeRetrievalService(response_record),
    )
    assert turn["intent"] == "FIND_SUPPORT"
    assert turn["tool_results"][0]["tool"] == "assess_evidence_link"
    assert "intervention" not in turn["tool_results"][0]["result"]
    assert turn["content"].startswith("Assessment explanation.")
