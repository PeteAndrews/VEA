"""Orchestrate tentative-level AI checking."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.level_classifier import LevelJudgementClassifier
from app.level_context import (
    build_level_judgement_context,
    discover_uncoded_candidates,
    summarize_coded_evidence,
)
from app.level_intervention import decide_level_intervention

USER_STATUSES = frozenset({"dismissed", "explore"})
AI_CHECK_LABELS = {
    "ALIGNS": "Broadly aligns",
    "PARTIALLY_ALIGNS": "Needs review",
    "DOES_NOT_ALIGN": "Does not align",
    "UNCERTAIN": "Needs review",
}

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _alignment(decision: dict[str, Any] | None) -> str:
    if not decision:
        return "UNCERTAIN"
    return str(decision.get("alignment") or decision.get("outcome") or "UNCERTAIN")


def _needs_attention(
    decision: dict[str, Any],
    rule_coverage: list[dict[str, Any]],
) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()

    for item in rule_coverage:
        if not item.get("satisfied"):
            line = f"Missing requirement: {item['criterion_text']}"
            if line not in seen:
                items.append(line)
                seen.add(line)

    for entry in decision.get("unresolved") or []:
        line = str(entry).strip()
        if line and line not in seen:
            items.append(line)
            seen.add(line)

    for dimension, note in dict(decision.get("dimension_coverage") or {}).items():
        if not note:
            continue
        lowered = note.lower()
        if any(token in lowered for token in ("gap", "missing", "weak", "partial", "unclear", "issue", "lack")):
            label = dimension.replace("_", " ")
            line = f"{label}: {note}"
            if line not in seen:
                items.append(line)
                seen.add(line)
    return items


def build_level_review_summary(
    interpretation: dict[str, Any],
    *,
    context: dict[str, Any],
) -> dict[str, Any]:
    verdict = interpretation.get("verdict") or {}
    alignment = _alignment(verdict)
    evidence_mapped = summarize_coded_evidence(context.get("coded_support") or [])
    needs_attention = _needs_attention(verdict, context.get("rule_coverage") or [])

    return {
        "level": interpretation.get("level"),
        "descriptor_text": (context.get("level_descriptor") or {}).get("text"),
        "ai_check_label": AI_CHECK_LABELS.get(alignment, "Needs review"),
        "alignment": alignment,
        "reason": verdict.get("reason"),
        "evidence_mapped": evidence_mapped,
        "needs_attention": needs_attention,
        "key_guidance": context.get("key_guidance") or "",
        "mapped_evidence_detail": [
            {
                "criterion_id": item["criterion_id"],
                "label": item["label"],
                "spans": item["spans"],
            }
            for item in evidence_mapped
        ],
    }


def run_level_check(
    *,
    classifier: LevelJudgementClassifier,
    evidence_classifier,
    graph_service,
    record: dict[str, Any],
    judgement_state: dict[str, Any],
    ai_payload: dict[str, Any],
    data_dir: str,
    stage: str,
    stage_source: str,
    retrieval_service=None,
) -> dict[str, Any]:
    if judgement_state.get("tentative_level") is None:
        raise ValueError("Tentative level must be set before running a level check.")

    context = build_level_judgement_context(
        graph_service=graph_service,
        record=record,
        judgement_state=judgement_state,
        ai_payload=ai_payload,
        data_dir=data_dir,
        stage=stage,
        stage_source=stage_source,
    )
    now = _utc_now()
    tentative = judgement_state["tentative_level"]
    interpretation: dict[str, Any] = {
        "id": f"ai-{uuid.uuid4().hex[:8]}",
        "kind": "level",
        "response_id": record["response_id"],
        "level": tentative["level"],
        "level_node_id": tentative.get("level_node_id"),
        "judgement_fingerprint": context["judgement_fingerprint"],
        "context": context,
        "stage": stage,
        "stage_source": stage_source,
        "explore_context": None,
        "created_at": now,
        "updated_at": now,
    }

    try:
        decision = classifier.classify(context)
        interpretation["verdict"] = decision.to_dict()
    except Exception as exc:
        logger.exception("level check failed")
        interpretation["verdict"] = None
        interpretation["intervention"] = None
        interpretation["status"] = "error"
        interpretation["error"] = str(exc)
        return interpretation

    uncoded = discover_uncoded_candidates(
        classifier=evidence_classifier,
        graph_service=graph_service,
        record=record,
        judgement_state=judgement_state,
        context=context,
        retrieval_service=retrieval_service,
    )
    interpretation["uncoded_candidates"] = uncoded

    level_label = str(tentative["level"])
    intervention = decide_level_intervention(
        interpretation["verdict"],
        rule_coverage=context["rule_coverage"],
        level_guidance=context["level_guidance"],
        level_label=level_label,
    )
    interpretation["intervention"] = intervention
    interpretation["status"] = "silent" if intervention["type"] == "SILENCE" else "pending"
    interpretation["summary"] = build_level_review_summary(interpretation, context=context)
    return interpretation


def build_level_explore_context(
    interpretation: dict[str, Any],
    judgement_state: dict[str, Any],
) -> dict[str, Any]:
    return {
        "kind": "level",
        "level": interpretation.get("level"),
        "verdict": interpretation.get("verdict"),
        "intervention": interpretation.get("intervention"),
        "summary": interpretation.get("summary"),
        "context": interpretation.get("context"),
        "uncoded_candidates": interpretation.get("uncoded_candidates"),
        "tentative_level": judgement_state.get("tentative_level"),
        "stage": interpretation.get("stage"),
        "prepared_at": _utc_now(),
    }


def update_level_interpretation_status(
    payload: dict[str, Any],
    ai_id: str,
    status: str,
    judgement_state: dict[str, Any],
) -> dict[str, Any]:
    if status not in USER_STATUSES:
        raise ValueError(f"Unsupported status: {status}")
    interpretation = None
    for item in payload.get("level_interpretations", []):
        if item["id"] == ai_id:
            interpretation = item
            break
    if interpretation is None:
        raise KeyError(ai_id)
    if interpretation["status"] not in {"pending", "dismissed", "explore"}:
        raise ValueError(f"Interpretation is not actionable: {interpretation['status']}")
    interpretation["status"] = status
    interpretation["updated_at"] = _utc_now()
    if status == "explore":
        interpretation["explore_context"] = build_level_explore_context(
            interpretation,
            judgement_state,
        )
    return interpretation
