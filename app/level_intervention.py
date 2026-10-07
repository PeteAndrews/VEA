"""Intervention policy for tentative-level AI checks."""

from __future__ import annotations

from typing import Any

ANCHOR_KEYWORDS = ("must", "only", "not", "reject", "require", "cannot", "do not")
SNIPPET_LENGTH = 160


def _snippet(text: str, limit: int = SNIPPET_LENGTH) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def _alignment(decision: dict[str, Any]) -> str:
    return str(decision.get("alignment") or decision.get("outcome") or "UNCERTAIN")


def level_needs_review(decision: dict[str, Any]) -> bool:
    alignment = _alignment(decision)
    if alignment == "UNCERTAIN":
        return True
    return bool(decision.get("needs_review"))


def _review_reasons(decision: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if _alignment(decision) == "UNCERTAIN":
        reasons.append("uncertain_alignment")
    if decision.get("needs_review"):
        reasons.append("borderline")
    return reasons or ["borderline"]


def _unsatisfied_rules(rule_coverage: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in rule_coverage if not item.get("satisfied")]


def _material_guidance(level_guidance: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in level_guidance:
        lowered = item.get("text", "").lower()
        if any(keyword in lowered for keyword in ANCHOR_KEYWORDS):
            items.append(item)
    return items


def decide_level_intervention(
    decision: dict[str, Any],
    *,
    rule_coverage: list[dict[str, Any]],
    level_guidance: list[dict[str, Any]],
    level_label: str,
) -> dict[str, Any]:
    unsatisfied = _unsatisfied_rules(rule_coverage)
    if unsatisfied:
        missing = ", ".join(_snippet(item["criterion_text"], 60) for item in unsatisfied[:2])
        return {
            "type": "CHALLENGE",
            "reasons": ["required_criterion_missing"],
            "message": (
                f"Level {level_label} requires linked evidence not yet coded ({missing}). "
                "Check required criteria before confirming this level."
            ),
            "nuance_items": [],
        }

    alignment = _alignment(decision)

    if level_needs_review(decision):
        return {
            "type": "REVIEW",
            "reasons": _review_reasons(decision),
            "message": (
                f"The level check could not reliably decide whether coded evidence supports "
                f"Level {level_label}. Worth a second look."
            ),
            "nuance_items": [],
        }

    anchors = _material_guidance(level_guidance)

    if alignment == "DOES_NOT_ALIGN" and anchors:
        return {
            "type": "REANCHOR",
            "reasons": ["disagreement_with_level_guidance"],
            "message": (
                f"Mark-scheme guidance for Level {level_label} may conflict with the coded evidence. "
                "Review the level descriptor and commentary."
            ),
            "nuance_items": [
                {
                    "node_id": item.get("node_id", ""),
                    "text": _snippet(item["text"]),
                }
                for item in anchors[:2]
            ],
        }

    if alignment in {"DOES_NOT_ALIGN", "PARTIALLY_ALIGNS"}:
        reading = "partially supporting" if alignment == "PARTIALLY_ALIGNS" else "not supporting"
        reason = decision.get("reason")
        message = (
            f"The coded evidence appears {reading} Level {level_label}. "
            "Check descriptor fit and required criteria."
        )
        if reason:
            message = f"{reason} Check descriptor fit before confirming Level {level_label}."
        return {
            "type": "CHALLENGE",
            "reasons": ["level_misalignment"],
            "message": message,
            "nuance_items": [],
        }

    if anchors:
        return {
            "type": "NUANCE",
            "reasons": ["aligned_with_material_guidance"],
            "message": (
                f"Level {level_label} looks plausible, but mark-scheme guidance affects how it applies."
            ),
            "nuance_items": [
                {
                    "node_id": item.get("node_id", ""),
                    "text": _snippet(item["text"]),
                }
                for item in anchors[:2]
            ],
        }

    return {
        "type": "SILENCE",
        "reasons": ["aligned_no_material_guidance"],
        "message": "",
        "nuance_items": [],
    }
