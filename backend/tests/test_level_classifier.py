from __future__ import annotations

import json

import httpx

from app.level_classifier import (
    FakeLevelJudgementClassifier,
    LLMLevelJudgementClassifier,
    cap_alignment_for_rules,
)


def test_cap_alignment_downgrades_aligns_when_rules_unsatisfied():
    rule_coverage = [{"criterion_id": "ms_02_3-point-6", "satisfied": False}]
    assert cap_alignment_for_rules("ALIGNS", rule_coverage) == "PARTIALLY_ALIGNS"
    assert cap_alignment_for_rules("PARTIALLY_ALIGNS", rule_coverage) == "PARTIALLY_ALIGNS"


def test_fake_classifier_applies_rule_cap():
    classifier = FakeLevelJudgementClassifier("ALIGNS")
    decision = classifier.classify(
        {
            "rule_coverage": [{"criterion_id": "ms_02_3-point-6", "satisfied": False}],
            "tentative_level": {"level": 3},
            "level_descriptor": {},
            "coded_support": [],
        }
    )
    assert decision.alignment == "PARTIALLY_ALIGNS"
    assert decision.outcome == "PARTIALLY_ALIGNS"


def test_llm_classifier_parses_structured_response():
    llm_json = {
        "selected_level": 3,
        "best_fit_level": 2,
        "alignment": "DOES_NOT_ALIGN",
        "dimension_coverage": {
            "validity": "Method is broadly valid.",
            "completeness": "Missing a required repeat step.",
            "logical_sequencing": "Steps are out of order.",
        },
        "unresolved": ["Repeat with fresh water not evidenced."],
        "reason": "Level 3 needs fuller method coverage.",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(llm_json)}},
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    classifier = LLMLevelJudgementClassifier(
        api_key="test-key",
        model="test-model",
        client=client,
        system_prompt="Return JSON.",
    )
    decision = classifier.classify(
        {
            "tentative_level": {"level": 3},
            "rule_coverage": [{"criterion_id": "ms_02_3-point-6", "satisfied": True}],
        }
    )
    assert decision.alignment == "DOES_NOT_ALIGN"
    assert decision.best_fit_level == 2
    assert decision.unresolved == ["Repeat with fresh water not evidenced."]
    assert "completeness" in decision.dimension_coverage
