from __future__ import annotations

from pathlib import Path

import pytest

from app.assessment import assess_evidence_link
from app.classifier import RELATIONS, EvidenceRelationClassifier, RelationDecision
from app.graph_service import GraphService
from app.intervention import decide_intervention
from app.responses import load_response
from app.views import resolve_response_id

ASSESSMENT_ID = "C-JUN25-8464C1H-02_3"
CANDIDATE_ID = "A"
DETAIL_1A = "ms_02_3-detail-1a"


class FakeClassifier(EvidenceRelationClassifier):
    name = "fake"

    def classify(self, evidence_text: str, criterion: dict, context: dict) -> RelationDecision:
        relation = "SUPPORTS" if "measuring cylinder" in evidence_text else "PARTIALLY_SUPPORTS"
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


@pytest.fixture
def graph_service():
    return GraphService.from_data_dir(data_dir="data", assessment_id=ASSESSMENT_ID)


@pytest.fixture
def response_record():
    response_id = resolve_response_id("data", ASSESSMENT_ID, CANDIDATE_ID)
    return load_response(response_id, responses_dir=Path("data/responses"))


def test_assess_evidence_link_without_intervention_policy(graph_service, response_record):
    text = response_record["text"]
    assessment = assess_evidence_link(
        classifier=FakeClassifier(),
        graph_service=graph_service,
        record=response_record,
        criterion_id=DETAIL_1A,
        start_char=42,
        end_char=86,
        text=text[42:86],
    )
    assert assessment["jev_direct"]["relation"] == "PARTIALLY_SUPPORTS"
    assert "intervention" not in assessment
    intervention = decide_intervention(assessment["jev_direct"], assessment["graph_context"])
    assert intervention["type"] in {"REVIEW", "NUANCE", "SILENCE", "CHALLENGE", "REANCHOR"}


def test_assess_evidence_link_finds_sentence_expansion(graph_service, response_record):
    text = response_record["text"]
    assessment = assess_evidence_link(
        classifier=FakeClassifier(),
        graph_service=graph_service,
        record=response_record,
        criterion_id=DETAIL_1A,
        start_char=42,
        end_char=86,
        text=text[42:86],
        search_additional=True,
    )
    assert assessment["additional_evidence"]["searched"] is True
    assert assessment["additional_evidence"]["found"] is True
    assert "measuring cylinder" in assessment["suggested_evidence_span"]["text"]
