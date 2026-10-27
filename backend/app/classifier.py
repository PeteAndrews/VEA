from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

RELATIONS = ("SUPPORTS", "PARTIALLY_SUPPORTS", "DOES_NOT_SUPPORT", "UNCERTAIN")

HOSTED_DECIDE_URL = "https://jevtypesafeai.com/api/v1/decide"
DEFAULT_MODEL = "jev-latest"

RELATION_CRITERIA: dict[str, str] = {
    "SUPPORTS": (
        "The selected evidence satisfies the criterion as written, including accepted equivalents. "
        "When the criterion lists alternatives (A or B), satisfying any one accepted branch is "
        "sufficient."
    ),
    "PARTIALLY_SUPPORTS": (
        "The evidence is clearly relevant and provides some required content, but something "
        "important is missing, incomplete, or ambiguous."
    ),
    "DOES_NOT_SUPPORT": (
        "The evidence is irrelevant, contradictory, or does not provide the criterion."
    ),
    "UNCERTAIN": (
        "The available evidence and context is insufficient to decide reliably."
    ),
}

NEEDS_REVIEW_PROBABILITY_THRESHOLD = 0.60
NEEDS_REVIEW_TOP_TWO_MARGIN = 0.15

CHOICE_INSTRUCTIONS = """Classify how the SELECTED EVIDENCE relates to the CRITERION.

The selected_evidence text is the only text to classify.
The containing sentence/segment and any neighbouring response segments are local context only —
use them to interpret pronouns, sequence, and references in the selected evidence, but do not
treat surrounding text as additional coded evidence.
This is evidence-criterion reasoning for assessment support, not semantic similarity.
Do not award marks or infer beyond what the selected evidence explicitly states.
Consider criterion guidance (ACCEPTS, REJECTS, CONSTRAINS, CLARIFIES, REQUIRES) when present.
When the criterion contains alternatives joined by "or", the selected evidence need only satisfy
one accepted branch (including accepted equivalents from guidance) to SUPPORT the criterion.
Do not require evidence for every branch.
Use SUPPORTS when the selected evidence satisfies the criterion as written, or any one accepted
alternative branch when alternatives are present.
Use PARTIALLY_SUPPORTS when relevant but incomplete or ambiguous.
Use DOES_NOT_SUPPORT when irrelevant, contradictory, or insufficient.
Use UNCERTAIN when the available evidence and context cannot support a reliable decision.
"""


def load_env_file(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def get_typesafe_api_key() -> str:
    load_env_file()
    api_key = (os.environ.get("TYPESAFE_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError(
            "TYPESAFE_API_KEY is not set. Add a jv_live_ key to .env or the environment."
        )
    if not api_key.startswith("jv_live_"):
        raise RuntimeError(
            "TYPESAFE_API_KEY must be a hosted jv_live_ key for vea-prototype."
        )
    return api_key


@dataclass
class RelationDecision:
    evidence_id: str
    criterion_id: str
    relation: str
    probability: float
    confidence: float
    probabilities: dict[str, float]
    classifier: str
    model: str
    evidence_text: str
    start_char: int | None = None
    end_char: int | None = None
    context_node_ids: list[str] = field(default_factory=list)
    status: str = "hypothesis"
    needs_review: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "criterion_id": self.criterion_id,
            "relation": self.relation,
            "probability": round(self.probability, 4),
            "confidence": round(self.confidence, 4),
            "probabilities": {k: round(v, 4) for k, v in self.probabilities.items()},
            "classifier": self.classifier,
            "model": self.model,
            "status": self.status,
            "needs_review": self.needs_review,
            "evidence_text": self.evidence_text,
            "start_char": self.start_char,
            "end_char": self.end_char,
            "context_node_ids": self.context_node_ids,
            "created_at": self.created_at,
        }


class EvidenceRelationClassifier(ABC):
    name: str

    @abstractmethod
    def classify(self, evidence_text: str, criterion: dict, context: dict) -> RelationDecision:
        ...


def _normalize_probabilities(raw: dict[str, float]) -> dict[str, float]:
    return {relation: float(raw.get(relation, 0.0)) for relation in RELATIONS}


def compute_needs_review(
    probability: float,
    confidence: float,
    probabilities: dict[str, float],
    *,
    probability_threshold: float = NEEDS_REVIEW_PROBABILITY_THRESHOLD,
    top_two_margin: float = NEEDS_REVIEW_TOP_TWO_MARGIN,
) -> bool:
    sorted_probs = sorted(probabilities.values(), reverse=True)
    top_two_close = (
        len(sorted_probs) >= 2 and (sorted_probs[0] - sorted_probs[1]) < top_two_margin
    )
    low_confidence = (
        probability < probability_threshold or confidence < probability_threshold
    )
    return low_confidence or top_two_close


def _parse_choice_answer(
    answer: dict[str, Any],
    *,
    model: str,
    evidence_id: str,
    criterion_id: str,
    evidence_text: str,
    start_char: int | None,
    end_char: int | None,
    context_node_ids: list[str],
    classifier: str,
) -> RelationDecision:
    raw_probs = {str(k): float(v) for k, v in dict(answer.get("probabilities", {})).items()}
    probabilities = _normalize_probabilities(raw_probs)
    relation = str(answer["choice"])
    probability = float(probabilities.get(relation, 0.0))
    confidence = float(answer.get("confidence", probability))
    needs_review = compute_needs_review(probability, confidence, probabilities)
    return RelationDecision(
        evidence_id=evidence_id,
        criterion_id=criterion_id,
        relation=relation,
        probability=probability,
        confidence=confidence,
        probabilities=probabilities,
        classifier=classifier,
        model=model,
        evidence_text=evidence_text,
        start_char=start_char,
        end_char=end_char,
        context_node_ids=context_node_ids,
        needs_review=needs_review,
    )


def build_jev_state(evidence_text: str, criterion: dict, context: dict) -> dict[str, Any]:
    check_mode = context.get("check_mode", "interpretive")
    response_context = context.get("response_context") or {}
    response_context_payload = {
        "containing_segment": response_context.get("containing_segment"),
        "containing_sentence": response_context.get("containing_sentence"),
        "preceding_segment": response_context.get("preceding_segment"),
        "following_segment": response_context.get("following_segment"),
        "note": response_context.get(
            "note",
            (
                "Containing and surrounding response text is interpretive context only. "
                "Use it to interpret the selected evidence, not as additional coded evidence."
            ),
        ),
    }
    return {
        "selected_evidence": {
            "text": evidence_text,
            "note": "This is the only text to classify.",
        },
        "response_context": response_context_payload,
        "check_mode": check_mode,
        "criterion_context": {
            "criterion": criterion,
            "parent_criterion": context.get("parent_criterion"),
            "guidance": context.get("guidance", []),
            "question": context.get("question"),
            **(
                {
                    "alternatives_note": (
                        "This criterion lists alternative branches. Satisfying any one accepted "
                        "branch is sufficient for SUPPORTS."
                    )
                }
                if criterion.get("alternatives")
                else {}
            ),
        },
        "note": (
            "Classify how the selected evidence relates to the criterion. "
            "This is a hypothesis, not a final mark."
        ),
    }


class JevEvidenceRelationClassifier(EvidenceRelationClassifier):
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

    def classify(self, evidence_text: str, criterion: dict, context: dict) -> RelationDecision:
        evidence_id = context.get("evidence_id", "")
        criterion_id = criterion["id"]
        start_char = context.get("start_char")
        end_char = context.get("end_char")
        context_node_ids = list(context.get("context_node_ids", []))

        state = build_jev_state(evidence_text, criterion, context)
        payload = {
            "model": self.model,
            "state": state,
            "questions": {
                "relation": {
                    "type": "choice",
                    "instructions": CHOICE_INSTRUCTIONS,
                    "criteria": RELATION_CRITERIA,
                }
            },
        }

        if self._client is not None:
            response = self._client.post(
                HOSTED_DECIDE_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        else:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    HOSTED_DECIDE_URL,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

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
        answer = data["answers"]["relation"]
        resolved_model = str(data.get("model") or self.model)
        return _parse_choice_answer(
            answer,
            model=resolved_model,
            evidence_id=evidence_id,
            criterion_id=criterion_id,
            evidence_text=evidence_text,
            start_char=start_char,
            end_char=end_char,
            context_node_ids=context_node_ids,
            classifier=self.name,
        )
