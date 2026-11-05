"""Three-layer conversation context for the examiner assistant."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.graph import is_codable_criterion
from app.interpretation_store import _public_relation_check

WORKING_SEARCH_CAP = 12
WORKING_ASSESSMENT_CAP = 12
WORKING_CRITERIA_VIEWED_CAP = 20
PENDING_ACTION_MAX_STEPS = 5


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def anchor_hash(anchor: dict[str, Any]) -> str:
    payload = json.dumps(anchor, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _is_link_like(context: dict[str, Any]) -> bool:
    return context.get("kind") in {"link", None} and bool(context.get("coding_id") or context.get("anchor", {}).get("coding_id"))


def _default_state() -> dict[str, Any]:
    return {
        "focus": {},
        "pending_actions": [],
        "open_questions": [],
        "turn": 0,
    }


def _default_working() -> dict[str, Any]:
    return {
        "searches": [],
        "assessments": [],
        "criteria_viewed": [],
    }


def sync_flat_mirrors(context: dict[str, Any]) -> None:
    """Keep top-level keys the frontend expects aligned with anchor."""
    anchor = context.get("anchor") or {}
    if anchor.get("criterion") is not None:
        context["criterion"] = anchor["criterion"]
    if anchor.get("evidence") is not None:
        context["evidence"] = anchor["evidence"]
    if context.get("source"):
        pass  # source stays at top level


def build_anchor_from_flat_link(flat: dict[str, Any]) -> dict[str, Any]:
    interpretation_stub = {
        "jev": flat.get("jev"),
        "jev_direct": flat.get("jev_direct"),
    }
    relation_check = _public_relation_check(interpretation_stub) if interpretation_stub.get("jev") or interpretation_stub.get("jev_direct") else flat.get("relation_check")
    guidance = (flat.get("graph_context") or {}).get("guidance")
    anchor: dict[str, Any] = {
        "coding_id": flat.get("coding_id"),
        "evidence": flat.get("evidence"),
        "criterion": flat.get("criterion"),
        "parent_criterion": flat.get("parent_criterion"),
        "interpretive_context": flat.get("interpretive_context"),
        "examiner_judgement": flat.get("examiner_judgement"),
        "relation_check": relation_check,
        "jev": flat.get("jev") or flat.get("jev_direct"),
        "jev_direct": flat.get("jev_direct") or flat.get("jev"),
        "intervention": flat.get("intervention"),
        "interpretation_id": flat.get("interpretation_id"),
    }
    if guidance is not None:
        anchor["guidance"] = guidance
    return anchor


def build_anchor_from_flat_general(flat: dict[str, Any]) -> dict[str, Any]:
    return {
        "assessment_id": flat.get("assessment_id"),
        "response_id": flat.get("response_id"),
        "judgement": flat.get("judgement"),
        "assessment_overview": flat.get("assessment_overview"),
        "response_segments": flat.get("response_segments"),
        "tentative_level": flat.get("tentative_level"),
        "coding_id": flat.get("coding_id"),
    }


def finalize_new_context(flat: dict[str, Any]) -> dict[str, Any]:
    """Wrap a freshly built flat context in anchor/state/working layers."""
    kind = "link" if flat.get("coding_id") and flat.get("evidence") else "general"
    if flat.get("kind") == "level":
        return flat
    anchor = (
        build_anchor_from_flat_link(flat)
        if kind == "link"
        else build_anchor_from_flat_general(flat)
    )
    layered: dict[str, Any] = {
        "context_id": flat["context_id"],
        "source": flat["source"],
        "stage": flat.get("stage"),
        "stage_source": flat.get("stage_source"),
        "kind": kind,
        "anchor": anchor,
        "state": _default_state(),
        "working": _default_working(),
        "prepared_at": flat.get("prepared_at") or _utc_now(),
    }
    if kind == "link":
        layered["coding_id"] = flat.get("coding_id")
    if kind == "general":
        for key in ("assessment_id", "response_id", "judgement", "assessment_overview", "response_segments", "tentative_level"):
            if key in flat:
                layered[key] = flat[key]
    layered["anchor_hash"] = anchor_hash(anchor)
    layered["anchor_status"] = "active"
    sync_flat_mirrors(layered)
    return layered


def ensure_layers(context: dict[str, Any]) -> dict[str, Any]:
    if context.get("kind") == "level":
        return context
    if "anchor" in context and "state" in context and "working" in context:
        sync_flat_mirrors(context)
        if not context.get("anchor_hash") and context.get("anchor"):
            context["anchor_hash"] = anchor_hash(context["anchor"])
        return context
    return finalize_new_context(context)


def verify_anchor_unchanged(context: dict[str, Any]) -> None:
    anchor = context.get("anchor")
    expected = context.get("anchor_hash")
    if not anchor or not expected:
        return
    current = anchor_hash(anchor)
    if current != expected:
        raise ValueError("Conversation anchor was modified; only launch may set the anchor.")


def append_working_search(context: dict[str, Any], entry: dict[str, Any]) -> None:
    working = context.setdefault("working", _default_working())
    searches = working.setdefault("searches", [])
    searches.append({**entry, "at": _utc_now()})
    del searches[:-WORKING_SEARCH_CAP]


def append_working_assessment(context: dict[str, Any], entry: dict[str, Any]) -> None:
    working = context.setdefault("working", _default_working())
    assessments = working.setdefault("assessments", [])
    assessments.append({**entry, "at": _utc_now()})
    del assessments[:-WORKING_ASSESSMENT_CAP]


def note_criterion_viewed(context: dict[str, Any], criterion_id: str) -> None:
    working = context.setdefault("working", _default_working())
    viewed = working.setdefault("criteria_viewed", [])
    if criterion_id not in viewed:
        viewed.append(criterion_id)
    del viewed[:-WORKING_CRITERIA_VIEWED_CAP]


def increment_turn(context: dict[str, Any]) -> None:
    state = context.setdefault("state", _default_state())
    state["turn"] = int(state.get("turn") or 0) + 1


def expire_pending_actions(context: dict[str, Any]) -> None:
    state = context.setdefault("state", _default_state())
    turn = int(state.get("turn") or 0)
    for action in state.get("pending_actions") or []:
        if action.get("status") != "offered":
            continue
        offered = int(action.get("offered_turn") or 0)
        if turn - offered >= 2:
            action["status"] = "expired"


def _compact_node(node: dict[str, Any] | None, *, assessable: bool) -> dict[str, Any] | None:
    if not isinstance(node, dict):
        return None
    text = (node.get("text") or "")[:120]
    return {
        "id": node.get("id"),
        "text": text,
        "node_type": node.get("node_type"),
        "assessable": assessable,
    }


def node_catalogue(graph_service, limit: int = 40) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for node_id, node in graph_service.graph.nodes.items():
        if node.get("segment_type") == "response_segment":
            continue
        assessable = node.get("node_type") == "mark_point" and is_codable_criterion(node.get("segment_type"))
        compact = _compact_node(graph_service.get_node(node_id), assessable=assessable)
        if compact:
            items.append(compact)
    items.sort(key=lambda item: (not item["assessable"], item.get("text") or ""))
    return items[:limit]


def compact_layers_for_llm(context: dict[str, Any], graph_service=None) -> dict[str, Any]:
    from app.conversation import _compact_criterion, _compact_interpretive_context

    ensure_layers(context)
    anchor = copy.deepcopy(context.get("anchor") or {})
    if anchor.get("criterion"):
        anchor["criterion"] = _compact_criterion(anchor["criterion"])
    if anchor.get("parent_criterion"):
        anchor["parent_criterion"] = _compact_criterion(anchor["parent_criterion"])
    if anchor.get("interpretive_context"):
        wrapped = {"interpretive_context": anchor["interpretive_context"]}
        anchor["interpretive_context"] = _compact_interpretive_context(wrapped)
    guidance = anchor.get("guidance")
    if isinstance(guidance, list):
        anchor["guidance"] = [
            {"relation": item.get("relation"), "scope": item.get("scope")}
            for item in guidance
        ]
    intervention = anchor.get("intervention")
    if isinstance(intervention, dict):
        anchor["intervention"] = {
            "type": intervention.get("type"),
            "reasons": intervention.get("reasons"),
        }

    state = copy.deepcopy(context.get("state") or {})
    working = copy.deepcopy(context.get("working") or {})
    working["searches"] = (working.get("searches") or [])[-5:]
    working["assessments"] = (working.get("assessments") or [])[-5:]

    payload: dict[str, Any] = {
        "context_id": context.get("context_id"),
        "source": context.get("source"),
        "kind": context.get("kind"),
        "anchor": anchor,
        "anchor_status": context.get("anchor_status", "active"),
        "evidence": anchor.get("evidence"),
        "criterion": anchor.get("criterion"),
        "state": {
            "focus": state.get("focus"),
            "pending_actions": [
                {
                    "id": a.get("id"),
                    "label": a.get("label"),
                    "status": a.get("status"),
                    "goal": a.get("goal"),
                }
                for a in (state.get("pending_actions") or [])
            ],
            "turn": state.get("turn"),
        },
        "working": working,
    }
    if graph_service is not None:
        payload["assessment_nodes"] = node_catalogue(graph_service)
    if (anchor.get("intervention") or {}).get("type") == "REVIEW":
        payload["borderline_link"] = True
        payload["borderline_reasons"] = list((anchor.get("intervention") or {}).get("reasons") or [])
    return payload


def mark_anchor_coding_removed(context: dict[str, Any]) -> None:
    context["anchor_status"] = "coding_removed"
