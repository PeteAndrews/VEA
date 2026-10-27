"""Follow-up conversation turns for level Explore/Verify contexts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

LEVEL_SOURCES = frozenset({"explore_level", "verify_level"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_level_conversation_context(active_context: dict[str, Any]) -> bool:
    if active_context.get("kind") == "level":
        return True
    return active_context.get("source") in LEVEL_SOURCES


def compact_level_context_for_llm(context: dict[str, Any]) -> dict[str, Any]:
    judgement_context = context.get("context") or {}
    verdict = context.get("verdict") or {}
    compact_verdict = {
        key: verdict[key]
        for key in (
            "selected_level",
            "best_fit_level",
            "alignment",
            "reason",
            "dimension_coverage",
            "unresolved",
        )
        if key in verdict
    }
    intervention = context.get("intervention") or {}
    compact_intervention = None
    if intervention:
        compact_intervention = {
            "type": intervention.get("type"),
            "message": intervention.get("message"),
        }

    coded_support = [
        {
            "criterion_id": item.get("criterion_id"),
            "criterion_text": item.get("criterion_text"),
            "jev_relation": item.get("jev_relation"),
        }
        for item in judgement_context.get("coded_support", [])
    ]

    return {
        "kind": "level",
        "source": context.get("source"),
        "level": context.get("level"),
        "tentative_level": context.get("tentative_level"),
        "summary": context.get("summary"),
        "verdict": compact_verdict,
        "intervention": compact_intervention,
        "judgement_context": {
            "level_descriptor": judgement_context.get("level_descriptor"),
            "all_level_descriptors": judgement_context.get("all_level_descriptors"),
            "rule_coverage": judgement_context.get("rule_coverage"),
            "key_guidance": judgement_context.get("key_guidance"),
            "coded_support": coded_support,
        },
        "note": (
            "Continue the level discussion. Mapped evidence and rule coverage are fixed inputs; "
            "the examiner's tentative level is authoritative unless they change it."
        ),
    }


def process_level_conversation_turn(
    *,
    active_context: dict[str, Any],
    llm,
    prompt_loader,
    messages: list[dict[str, Any]],
    context_id: str,
) -> dict[str, Any]:
    system_prompt = prompt_loader.load_system()
    turn_prompt = prompt_loader.load("level_conversation.txt")
    compact_context = compact_level_context_for_llm(active_context)
    active_context["updated_at"] = _utc_now()

    from app.conversation import _conversation_history_for_llm

    assistant_text = llm.respond(
        system_prompt=system_prompt,
        launch_prompt=turn_prompt,
        active_context=compact_context,
        messages=_conversation_history_for_llm(messages, context_id=context_id),
    )
    return {
        "content": assistant_text,
        "intent": "DISCUSS",
        "tool_results": [],
        "citations": [],
        "resolved_references": {},
        "clarification_needed": False,
        "active_context": active_context,
        "trace": {"mode": "level_conversation"},
    }
