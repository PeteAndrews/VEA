"""Level judgement classifiers — LLM for holistic checks, Jev retained for tests."""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.classifier import (
    DEFAULT_MODEL,
    HOSTED_DECIDE_URL,
    compute_needs_review,
    get_typesafe_api_key,
    load_env_file,
)

LEVEL_OUTCOMES = ("ALIGNS", "PARTIALLY_ALIGNS", "DOES_NOT_ALIGN", "UNCERTAIN")
DEFAULT_PROMPTS_DIR = Path(os.getenv("VEA_PROMPTS_DIR", "prompts"))
OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"

LEVEL_CRITERIA = {
    "ALIGNS": (
        "Coded evidence and mark-scheme guidance support the examiner's tentative level. "
        "Required criteria are met and the response quality fits the descriptor."
    ),
    "PARTIALLY_ALIGNS": (
        "Some support exists but gaps remain — missing required links, weak support on key "
        "criteria, or descriptor fit is incomplete."
    ),
    "DOES_NOT_ALIGN": (
        "Coded evidence or explicit rules do not support the tentative level."
    ),
    "UNCERTAIN": (
        "Insufficient clarity to judge alignment confidently."
    ),
}

JEV_CHOICE_INSTRUCTIONS = (
    "You are evaluating whether the examiner's TENTATIVE level is supported. "
    "Do not assign an independent mark or level. "
    "Use rule_coverage as fixed deterministic facts — do not override unsatisfied REQUIRES. "
    "Only coded_support counts as evidence; full_response is interpretive context only."
)


@dataclass
class LevelJudgementDecision:
    selected_level: int
    alignment: str
    reason: str
    classifier: str
    model: str
    best_fit_level: int | None = None
    dimension_coverage: dict[str, str] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)
    probability: float = 1.0
    confidence: float = 1.0
    probabilities: dict[str, float] = field(default_factory=dict)
    needs_review: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def outcome(self) -> str:
        return self.alignment

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_level": self.selected_level,
            "best_fit_level": self.best_fit_level,
            "alignment": self.alignment,
            "outcome": self.alignment,
            "dimension_coverage": dict(self.dimension_coverage),
            "unresolved": list(self.unresolved),
            "reason": self.reason,
            "probability": round(self.probability, 4),
            "confidence": round(self.confidence, 4),
            "probabilities": {k: round(v, 4) for k, v in self.probabilities.items()},
            "classifier": self.classifier,
            "model": self.model,
            "needs_review": self.needs_review,
            "created_at": self.created_at,
        }


class LevelJudgementClassifier(ABC):
    name: str

    @abstractmethod
    def classify(self, context: dict[str, Any]) -> LevelJudgementDecision:
        ...


def cap_alignment_for_rules(alignment: str, rule_coverage: list[dict[str, Any]]) -> str:
    unsatisfied = [item for item in rule_coverage if not item.get("satisfied")]
    if not unsatisfied:
        return alignment
    if alignment == "ALIGNS":
        return "PARTIALLY_ALIGNS"
    return alignment


def _normalize_probabilities(raw: dict[str, float]) -> dict[str, float]:
    return {outcome: float(raw.get(outcome, 0.0)) for outcome in LEVEL_OUTCOMES}


def _selected_level(context: dict[str, Any]) -> int:
    tentative = context.get("tentative_level") or {}
    return int(tentative["level"])


def _load_level_judgement_prompt() -> str:
    path = DEFAULT_PROMPTS_DIR / "level_judgement.txt"
    if not path.is_file():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def _parse_llm_decision(raw: dict[str, Any], context: dict[str, Any], *, classifier: str, model: str) -> LevelJudgementDecision:
    alignment = str(raw.get("alignment") or "UNCERTAIN").upper()
    if alignment not in LEVEL_OUTCOMES:
        alignment = "UNCERTAIN"
    alignment = cap_alignment_for_rules(alignment, context.get("rule_coverage", []))
    selected = int(raw.get("selected_level") or _selected_level(context))
    best_fit = raw.get("best_fit_level")
    best_fit_level = int(best_fit) if best_fit is not None else None
    dimension_coverage = {
        str(key): str(value)
        for key, value in dict(raw.get("dimension_coverage") or {}).items()
    }
    unresolved = [str(item) for item in list(raw.get("unresolved") or [])]
    reason = str(raw.get("reason") or "").strip()
    needs_review = alignment == "UNCERTAIN"
    probabilities = {item: 0.0 for item in LEVEL_OUTCOMES}
    probabilities[alignment] = 1.0
    return LevelJudgementDecision(
        selected_level=selected,
        best_fit_level=best_fit_level,
        alignment=alignment,
        dimension_coverage=dimension_coverage,
        unresolved=unresolved,
        reason=reason,
        classifier=classifier,
        model=model,
        probability=1.0,
        confidence=1.0,
        probabilities=probabilities,
        needs_review=needs_review,
    )


def build_llm_payload(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "tentative_level": context.get("tentative_level"),
        "all_level_descriptors": context.get("all_level_descriptors"),
        "rule_coverage": context.get("rule_coverage"),
        "key_guidance": context.get("key_guidance"),
        "coded_support": context.get("coded_support"),
        "evidence_interpretations": context.get("evidence_interpretations"),
        "full_response": context.get("full_response"),
        "response_note": context.get("response_note"),
        "question": context.get("question"),
    }


class FakeLevelJudgementClassifier(LevelJudgementClassifier):
    name = "fake"

    def __init__(
        self,
        alignment: str = "ALIGNS",
        *,
        needs_review: bool = False,
        reason: str = "Fake level check.",
        best_fit_level: int | None = None,
        unresolved: list[str] | None = None,
    ) -> None:
        self.alignment = alignment
        self.needs_review = needs_review
        self.reason = reason
        self.best_fit_level = best_fit_level
        self.unresolved = unresolved or []

    def classify(self, context: dict[str, Any]) -> LevelJudgementDecision:
        alignment = cap_alignment_for_rules(self.alignment, context.get("rule_coverage", []))
        probabilities = {item: 0.0 for item in LEVEL_OUTCOMES}
        probabilities[alignment] = 0.9 if not self.needs_review else 0.55
        return LevelJudgementDecision(
            selected_level=_selected_level(context),
            best_fit_level=self.best_fit_level,
            alignment=alignment,
            dimension_coverage={
                "validity": "Fake validity note.",
                "completeness": "Fake completeness note.",
                "logical_sequencing": "Fake sequencing note.",
            },
            unresolved=list(self.unresolved),
            reason=self.reason,
            classifier=self.name,
            model="fake",
            probability=probabilities[alignment],
            confidence=probabilities[alignment],
            probabilities=probabilities,
            needs_review=self.needs_review or alignment == "UNCERTAIN",
        )


class LLMLevelJudgementClassifier(LevelJudgementClassifier):
    name = "llm"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 90.0,
        client: httpx.Client | None = None,
        system_prompt: str | None = None,
    ) -> None:
        load_env_file()
        self.api_key = (api_key or os.environ.get("OPENAI_API_KEY") or "").strip()
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not set.")
        self.model = model or os.environ.get("LEVEL_LLM_MODEL") or os.environ.get("LLM_MODEL", DEFAULT_MODEL)
        self.timeout = timeout
        self._client = client
        self.system_prompt = system_prompt or _load_level_judgement_prompt()

    def classify(self, context: dict[str, Any]) -> LevelJudgementDecision:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(build_llm_payload(context), ensure_ascii=False),
                },
            ],
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self._client is not None:
            response = self._client.post(OPENAI_CHAT_URL, headers=headers, json=payload)
        else:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(OPENAI_CHAT_URL, headers=headers, json=payload)
        if response.status_code >= 400:
            raise RuntimeError(f"OpenAI API error {response.status_code}: {response.text[:500]}")
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        raw = json.loads(content)
        return _parse_llm_decision(raw, context, classifier=self.name, model=self.model)


class JevLevelJudgementClassifier(LevelJudgementClassifier):
    """Legacy Jev holistic check — retained for tests only."""

    name = "jev"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        timeout: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        load_env_file()
        self.api_key = api_key or get_typesafe_api_key()
        self.model = model
        self.timeout = timeout
        self._client = client

    def classify(self, context: dict[str, Any]) -> LevelJudgementDecision:
        state = {
            "tentative_level": context.get("tentative_level"),
            "level_descriptor": context.get("level_descriptor"),
            "rule_coverage": context.get("rule_coverage"),
            "level_guidance": context.get("level_guidance"),
            "coded_support": context.get("coded_support"),
            "full_response": context.get("full_response"),
            "response_note": context.get("response_note"),
            "question": context.get("question"),
        }
        payload = {
            "model": self.model,
            "state": state,
            "questions": {
                "alignment": {
                    "type": "choice",
                    "instructions": JEV_CHOICE_INSTRUCTIONS,
                    "criteria": LEVEL_CRITERIA,
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
        if response.status_code >= 400:
            raise RuntimeError(f"Jev API error {response.status_code}: {response.text[:500]}")
        answer = response.json()["answers"]["alignment"]
        raw_probs = {str(k): float(v) for k, v in dict(answer.get("probabilities", {})).items()}
        probabilities = _normalize_probabilities(raw_probs)
        alignment = cap_alignment_for_rules(str(answer["choice"]), context.get("rule_coverage", []))
        probability = float(probabilities.get(alignment, 0.0))
        confidence = float(answer.get("confidence", probability))
        needs_review = compute_needs_review(probability, confidence, probabilities)
        return LevelJudgementDecision(
            selected_level=_selected_level(context),
            best_fit_level=None,
            alignment=alignment,
            dimension_coverage={},
            unresolved=[],
            reason=str(answer.get("rationale") or ""),
            classifier=self.name,
            model=self.model,
            probability=probability,
            confidence=confidence,
            probabilities=probabilities,
            needs_review=needs_review,
        )


# Backward-compatible aliases
LevelDecision = LevelJudgementDecision
cap_outcome_for_rules = cap_alignment_for_rules
