"""Examiner assistant session context and turn orchestration."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.assistant_context import finalize_new_context
from app.assistant_tool_loop import run_assistant_turn
from app.graph_service import GraphService
from app.judgement import judgement_view
from app.stages import resolve_stage


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _judgement_summary(
    graph_service: GraphService,
    judgement_state: dict[str, Any],
    data_dir: str,
) -> dict[str, Any]:
    view = judgement_view(judgement_state, graph_service, data_dir)
    return {
        "codings": view.get("codings", []),
        "tentative_level": view.get("tentative_level"),
        "event_count": len(judgement_state.get("events", [])),
    }


def build_session_context(
    *,
    graph_service: GraphService,
    record: dict[str, Any],
    judgement_state: dict[str, Any],
    assessment_id: str,
    data_dir: str,
    source: str = "general",
    stage: str | None = None,
    stage_source: str | None = None,
    coding_id: str | None = None,
    interpretation: dict[str, Any] | None = None,
    resolved_references: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from app.conversation import build_conversation_context

    resolved_stage, resolved_stage_source = resolve_stage(judgement_state, stage, None)
    context: dict[str, Any] = {
        "context_id": _new_id("ctx"),
        "source": source,
        "stage": resolved_stage,
        "stage_source": stage_source or resolved_stage_source,
        "assessment_id": assessment_id,
        "response_id": record["response_id"],
        "response_segments": [
            {
                "segment_id": segment["id"],
                "order": segment["order"],
                "text": segment["text"],
                "start_char": segment["start_char"],
                "end_char": segment["end_char"],
            }
            for segment in record.get("segments", [])
        ],
        "assessment_overview": graph_service.assessment_overview(),
        "judgement": _judgement_summary(graph_service, judgement_state, data_dir),
        "tentative_level": judgement_state.get("tentative_level"),
        "coding_id": coding_id,
        "resolved_references": dict(resolved_references or {}),
        "prepared_at": _utc_now(),
    }
    if coding_id and interpretation:
        coding_context = build_conversation_context(
            graph_service=graph_service,
            record=record,
            judgement_state=judgement_state,
            coding_id=coding_id,
            source=source if source in {"explore", "verify"} else "verify",
            interpretation=interpretation,
            stage=stage,
            stage_source=stage_source,
        )
        context.update(
            {
                "evidence": coding_context.get("evidence") or (coding_context.get("anchor") or {}).get("evidence"),
                "criterion": coding_context.get("criterion") or (coding_context.get("anchor") or {}).get("criterion"),
                "parent_criterion": coding_context.get("parent_criterion"),
                "coding_id": coding_id,
            }
        )
        return coding_context
    return finalize_new_context(context)


def process_assistant_turn(
    *,
    content: str,
    active_context: dict[str, Any],
    graph_service: GraphService,
    record: dict[str, Any],
    judgement_state: dict[str, Any],
    classifier,
    retrieval_service,
    llm,
    prompt_loader,
    history: list[dict[str, Any]],
    data_dir: str = "data",
    intent_classifier=None,  # deprecated; ignored
) -> dict[str, Any]:
    return run_assistant_turn(
        content=content,
        active_context=active_context,
        graph_service=graph_service,
        record=record,
        judgement_state=judgement_state,
        classifier=classifier,
        retrieval_service=retrieval_service,
        llm=llm,
        prompt_loader=prompt_loader,
        history=history,
        data_dir=data_dir,
        launch=False,
    )
