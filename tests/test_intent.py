from __future__ import annotations

from app.intent import (
    FakeIntentClassifier,
    build_intent_conversation_context,
    build_intent_state,
)


def test_build_intent_state_excludes_resolution_fields():
    state = build_intent_state(
        "Does the response hold evidence for point 1?",
        build_intent_conversation_context(
            {
                "source": "general",
                "evidence": {"text": "stale span"},
                "criterion": {"id": "point-5", "text": "repeat masses"},
                "resolved_references": {"response_span": {"text": "stale"}},
            }
        ),
    )
    assert "stale" not in str(state)
    assert state["conversation_context"]["has_active_span"] is True
    assert state["conversation_context"]["has_active_criterion"] is True


def test_fake_intent_classifier_marks_ambiguous_cases():
    classifier = FakeIntentClassifier()
    context = {"source": "general", "has_active_span": False, "has_active_criterion": False}
    decision = classifier.classify("This is ambiguous intent.", context)
    assert decision.needs_clarification is True
