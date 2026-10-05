"""Bounded conversational intent classification for the Examiner Assistant."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

import httpx

from app.classifier import (
    HOSTED_DECIDE_URL,
    DEFAULT_MODEL,
    compute_needs_review,
    get_typesafe_api_key,
)

Intent = Literal["DISCUSS", "LOCATE_EVIDENCE", "ASSESS_LINK", "FIND_SUPPORT"]

INTENTS: tuple[str, ...] = ("DISCUSS", "LOCATE_EVIDENCE", "ASSESS_LINK", "FIND_SUPPORT")

INTENT_CRITERIA: dict[str, str] = {
    "DISCUSS": (
        "The examiner wants mark-scheme or question explanation only — what a point means, "
        "how guidance applies, or general assessment context. No response evidence search or "
        "link judgement is requested."
    ),
    "LOCATE_EVIDENCE": (
        "The examiner wants to find where in the response something is mentioned — which part, "
        "sentence, or span contains particular wording or content."
    ),
    "ASSESS_LINK": (
        "The examiner asks whether a specific or referenced response span supports a criterion — "
        "for example 'that sentence', 'this evidence', 'would that be enough', or quoted response "
        "text. The question presumes a particular span is already in focus."
    ),
    "FIND_SUPPORT": (
        "The examiner asks whether the response anywhere contains evidence for a criterion or "
        "mark-scheme point — for example 'does the response support/hold/contain evidence for "
        "point X' without referencing a specific span."
    ),
}

INTENT_CHOICE_INSTRUCTIONS = """Classify the examiner's conversational intent for this marking assistant.

Choose exactly one intent. Do not resolve criteria, evidence spans, or assessment outcomes — only
classify what kind of help the examiner is asking for.

Use ASSESS_LINK when the examiner refers to a specific span (that/this sentence, that evidence,
would that be enough, quoted response text).
Use FIND_SUPPORT when the examiner asks whether the response contains or supports evidence for a
mark-scheme point without pointing at a specific span.
Use LOCATE_EVIDENCE when the examiner only wants to find where something appears in the response.
Use DISCUSS when the examiner wants explanation of the mark scheme or question without searching
or judging response evidence.
"""


@dataclass
class IntentDecision:
    intent: Intent
    probability: float
    confidence: float
    probabilities: dict[str, float]
    classifier: str
    model: str
    needs_clarification: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "probability": round(self.probability, 4),
            "confidence": round(self.confidence, 4),
            "probabilities": {k: round(v, 4) for k, v in self.probabilities.items()},
            "classifier": self.classifier,
            "model": self.model,
            "needs_clarification": self.needs_clarification,
            "created_at": self.created_at,
        }


def _normalize_probabilities(raw: dict[str, float]) -> dict[str, float]:
    return {intent: float(raw.get(intent, 0.0)) for intent in INTENTS}


def build_intent_conversation_context(active_context: dict[str, Any]) -> dict[str, Any]:
    refs = active_context.get("resolved_references") or {}
    return {
        "source": active_context.get("source", "general"),
        "has_active_span": bool(refs.get("response_span") or active_context.get("evidence")),
        "has_active_criterion": bool(refs.get("criterion") or active_context.get("criterion")),
        "last_intent": active_context.get("last_intent"),
    }


def build_intent_state(content: str, conversation_context: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_message": content,
        "conversation_context": conversation_context,
        "note": (
            "Classify intent only. Do not choose criteria, evidence spans, or assessment outcomes."
        ),
    }


def _parse_intent_answer(
    answer: dict[str, Any],
    *,
    model: str,
    classifier: str,
) -> IntentDecision:
    raw_probs = {str(k): float(v) for k, v in dict(answer.get("probabilities", {})).items()}
    probabilities = _normalize_probabilities(raw_probs)
    intent = str(answer["choice"])
    if intent not in INTENTS:
        intent = "DISCUSS"
    probability = float(probabilities.get(intent, 0.0))
    confidence = float(answer.get("confidence", probability))
    needs_clarification = compute_needs_review(probability, confidence, probabilities)
    return IntentDecision(
        intent=intent,  # type: ignore[arg-type]
        probability=probability,
        confidence=confidence,
        probabilities=probabilities,
        classifier=classifier,
        model=model,
        needs_clarification=needs_clarification,
    )


class IntentClassifier(ABC):
    name: str

    @abstractmethod
    def classify(self, content: str, conversation_context: dict[str, Any]) -> IntentDecision:
        ...


class JevIntentClassifier(IntentClassifier):
    name = "jev"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        timeout: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key or get_typesafe_api_key()
        self.model = model
        self.timeout = timeout
        self._client = client

    def classify(self, content: str, conversation_context: dict[str, Any]) -> IntentDecision:
        payload = {
            "model": self.model,
            "state": build_intent_state(content, conversation_context),
            "questions": {
                "intent": {
                    "type": "choice",
                    "instructions": INTENT_CHOICE_INSTRUCTIONS,
                    "criteria": INTENT_CRITERIA,
                }
            },
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self._client is not None:
            response = self._client.post(HOSTED_DECIDE_URL, headers=headers, json=payload)
        else:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(HOSTED_DECIDE_URL, headers=headers, json=payload)

        if response.status_code == 402:
            raise RuntimeError(
                "Jev hosted API returned insufficient credits. Top up the prepaid balance "
                "for this jv_live_ key, then retry."
            )
        if response.status_code >= 400:
            raise RuntimeError(
                f"Jev hosted API error {response.status_code}: {response.text[:500]}"
            )

        data = response.json()
        answer = data["answers"]["intent"]
        resolved_model = str(data.get("model") or self.model)
        return _parse_intent_answer(answer, model=resolved_model, classifier=self.name)


class FakeIntentClassifier(IntentClassifier):
    """Deterministic intent routing for tests."""

    name = "fake"

    def classify(self, content: str, conversation_context: dict[str, Any]) -> IntentDecision:
        lower = " ".join(content.lower().split())
        if "ambiguous intent" in lower:
            return self._decision("DISCUSS", probability=0.45, confidence=0.45, ambiguous=True)

        if any(
            token in lower
            for token in (
                "that sentence",
                "this sentence",
                "that evidence",
                "this evidence",
                "would that be enough",
                "does that support",
                "does this support",
                "is that sufficient",
            )
        ):
            intent = "ASSESS_LINK"
        elif any(
            token in lower
            for token in (
                "where does",
                "where do they",
                "where is",
                "which part",
                "which sentence",
                "show me where",
            )
        ):
            intent = "LOCATE_EVIDENCE"
        elif any(
            token in lower
            for token in (
                "hold evidence",
                "contain evidence",
                "evidence for",
                "does the response support",
                "does the student response support",
                "support the marking point",
            )
        ):
            intent = "FIND_SUPPORT"
        elif any(
            token in lower
            for token in (
                "what does",
                "what is",
                "explain",
                "mean",
                "full context",
                "full question",
            )
        ):
            intent = "DISCUSS"
        else:
            intent = "DISCUSS"

        return self._decision(intent)  # type: ignore[arg-type]

    def _decision(
        self,
        intent: Intent,
        *,
        probability: float = 0.9,
        confidence: float = 0.9,
        ambiguous: bool = False,
    ) -> IntentDecision:
        probabilities = {item: 0.0 for item in INTENTS}
        probabilities[intent] = probability
        return IntentDecision(
            intent=intent,
            probability=probability,
            confidence=confidence,
            probabilities=probabilities,
            classifier=self.name,
            model="fake",
            needs_clarification=ambiguous,
        )
