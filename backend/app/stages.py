from __future__ import annotations

from typing import Any

STAGES = ("ORIENTATION", "EVIDENCE_MAPPING", "LEVEL_JUDGEMENT", "DECISION")

ACTION_STAGE: dict[str, str] = {
    "select_evidence": "EVIDENCE_MAPPING",
    "link_evidence": "EVIDENCE_MAPPING",
    "revise_coding": "EVIDENCE_MAPPING",
    "unlink_evidence": "EVIDENCE_MAPPING",
    "set_tentative_level": "LEVEL_JUDGEMENT",
    "view_level_context": "LEVEL_JUDGEMENT",
    "final_mark": "DECISION",
    "submit": "DECISION",
}


def derive_stage(state: dict[str, Any] | None, last_action: str | None = None) -> str:
    if last_action in ACTION_STAGE:
        return ACTION_STAGE[last_action]
    state = state or {}
    has_codings = bool(state.get("relations"))
    has_level = state.get("tentative_level") is not None
    if not has_codings and not has_level:
        return "ORIENTATION"
    if has_level:
        return "LEVEL_JUDGEMENT"
    return "EVIDENCE_MAPPING"


def resolve_stage(
    state: dict[str, Any] | None,
    client_stage: str | None,
    last_action: str | None,
) -> tuple[str, str]:
    if client_stage in STAGES:
        return client_stage, "client"
    return derive_stage(state, last_action), "derived"
