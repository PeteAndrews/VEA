from __future__ import annotations

from app.assistant import classify_intent, process_assistant_turn
from app.classifier import RELATIONS, EvidenceRelationClassifier, RelationDecision
from app.graph_service import GraphService
from app.conversation import PromptLoader
from app.conversation import FakeConversationLLM
from pathlib import Path

ASSESSMENT_ID = "C-JUN25-8464C1H-02_3"


class FakeClassifier(EvidenceRelationClassifier):
    name = "fake"

    def classify(self, evidence_text: str, criterion: dict, context: dict) -> RelationDecision:
        relation = "SUPPORTS"
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


def test_classify_intent_routes_assessment_and_locate():
    assert classify_intent("Would that be enough for point 4?") == "ASSESS_LINK"
    assert classify_intent("Where does the student mention controlling the water?") == "LOCATE_EVIDENCE"
    assert classify_intent("What does point 4 mean?") == "DISCUSS"


def test_process_assistant_turn_assess_link_uses_assessment_not_intervention():
    from app.responses import load_response
    from app.views import resolve_response_id

    graph_service = GraphService.from_data_dir(data_dir="data", assessment_id=ASSESSMENT_ID)
    response_record = load_response(
        resolve_response_id("data", ASSESSMENT_ID, "A"),
        responses_dir=Path("data/responses"),
    )
    text = response_record["text"]
    active_context = {
        "context_id": "ctx-test",
        "source": "general",
        "evidence": {
            "text": text[0:86],
            "start_char": 0,
            "end_char": 86,
        },
        "criterion": {
            "id": "ms_02_3-detail-1a",
            "text": "o using a measuring cylinder",
        },
        "resolved_references": {},
    }
    turn = process_assistant_turn(
        content="Would that be enough for using a measuring cylinder?",
        active_context=active_context,
        graph_service=graph_service,
        record=response_record,
        judgement_state={"relations": [], "evidence_spans": [], "events": []},
        classifier=FakeClassifier(),
        retrieval_service=None,
        llm=FakeConversationLLM("Assessment explanation."),
        prompt_loader=PromptLoader(prompts_dir=Path("prompts")),
        history=[],
    )
    assert turn["intent"] == "ASSESS_LINK"
    assert turn["tool_results"][0]["tool"] == "assess_evidence_link"
    assert "intervention" not in turn["tool_results"][0]["result"]
    assert turn["content"].startswith("Assessment explanation.")
