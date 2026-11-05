"""Bounded OpenAI tool loop for link and general assistant chats."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from app.assistant_context import (
    compact_layers_for_llm,
    ensure_layers,
    expire_pending_actions,
    increment_turn,
    sync_flat_mirrors,
    verify_anchor_unchanged,
)
from app.assistant_tools import ToolRuntime, tool_schemas

MAX_TOOL_ROUNDS = 4
MAX_TOOL_CALLS = 8


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _history_for_llm(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {"role": message["role"], "content": message["content"]}
        for message in messages
        if message.get("role") in {"user", "assistant"}
    ]


def run_assistant_turn(
    *,
    content: str | None,
    active_context: dict[str, Any],
    graph_service,
    record: dict[str, Any],
    judgement_state: dict[str, Any],
    classifier,
    retrieval_service,
    llm,
    prompt_loader,
    history: list[dict[str, Any]],
    data_dir: str,
    launch: bool = False,
) -> dict[str, Any]:
    from app.level_conversation import is_level_conversation_context, process_level_conversation_turn

    if is_level_conversation_context(active_context):
        context_id = active_context.get("context_id", "")
        user_content = content or ""
        history_messages = [
            *history,
            {"role": "user", "content": user_content, "context_id": context_id},
        ]
        return process_level_conversation_turn(
            active_context=active_context,
            llm=llm,
            prompt_loader=prompt_loader,
            messages=history_messages,
            context_id=context_id,
        )

    ensure_layers(active_context)
    expire_pending_actions(active_context)
    if not launch:
        increment_turn(active_context)

    citations: list[dict[str, Any]] = []
    tool_trace: list[dict[str, Any]] = []
    rounds = 0
    tool_calls = 0
    pending_created: list[str] = []
    pending_resolved: list[str] = []

    runtime = ToolRuntime(
        graph_service=graph_service,
        record=record,
        judgement_state=judgement_state,
        classifier=classifier,
        retrieval_service=retrieval_service,
        data_dir=data_dir,
        context=active_context,
        on_citations=lambda items: citations.extend(items),
    )

    system_prompt = prompt_loader.load_system()
    if launch:
        launch_prompt = prompt_loader.load_launch(active_context["source"])
        tools_prompt = prompt_loader.load("assistant_tools.txt")
        instructions = f"{system_prompt}\n\n{launch_prompt}\n\n{tools_prompt}"
        input_items: list[dict[str, Any]] = []
    else:
        tools_prompt = prompt_loader.load("assistant_tools.txt")
        instructions = f"{system_prompt}\n\n{tools_prompt}"
        input_items = _history_for_llm(history)
        if content:
            input_items.append({"role": "user", "content": content})

    context_payload = compact_layers_for_llm(active_context, graph_service)
    input_items = [
        {
            "role": "system",
            "content": f"Conversation context JSON:\n{json.dumps(context_payload, indent=2)}",
        },
        *input_items,
    ]

    tools = tool_schemas()
    assistant_text = ""
    while rounds < MAX_TOOL_ROUNDS and tool_calls < MAX_TOOL_CALLS:
        rounds += 1
        response = llm.respond_with_tools(
            instructions=instructions,
            input_items=input_items,
            tools=tools if tool_calls < MAX_TOOL_CALLS else [],
        )
        if response.get("type") == "text":
            assistant_text = response.get("text") or ""
            break
        calls = response.get("calls") or []
        if not calls:
            break
        for call in calls:
            if tool_calls >= MAX_TOOL_CALLS:
                break
            tool_calls += 1
            name = call["name"]
            args = call.get("arguments") or {}
            started = _utc_now()
            try:
                result = runtime.dispatch(name, args)
            except Exception as exc:  # noqa: BLE001
                result = {"error": str(exc)}
            tool_trace.append(
                {
                    "name": name,
                    "args": args,
                    "result": result,
                    "error": result.get("error") if isinstance(result, dict) else None,
                    "started_at": started,
                }
            )
            if name == "propose_action" and isinstance(result, dict) and result.get("action_id"):
                pending_created.append(result["action_id"])
            if name == "resolve_pending_action" and isinstance(result, dict) and result.get("action_id"):
                pending_resolved.append(result["action_id"])
            call_id = call.get("call_id") or f"call-{tool_calls}"
            input_call = call.get("input_call")
            if input_call is None:
                input_call = {
                    "type": "function_call",
                    "call_id": call_id,
                    "name": name,
                    "arguments": json.dumps(args),
                }
            input_items.append(input_call)
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(result),
                }
            )

    if not assistant_text:
        final = llm.respond_with_tools(
            instructions=instructions + "\n\nProvide a concise examiner-facing reply. Do not call tools.",
            input_items=input_items,
            tools=[],
        )
        assistant_text = final.get("text") or "I couldn't complete that request."

    sync_flat_mirrors(active_context)
    active_context["updated_at"] = _utc_now()
    verify_anchor_unchanged(active_context)

    trace = {
        "rounds": rounds,
        "tool_calls": tool_trace,
        "pending_created": pending_created,
        "pending_resolved": pending_resolved,
        "model": getattr(llm, "model", getattr(llm, "name", "unknown")),
    }
    active_context["last_trace"] = trace

    return {
        "content": assistant_text,
        "intent": "TOOLS",
        "tool_results": tool_trace,
        "citations": _dedupe_citations(citations),
        "resolved_references": {},
        "clarification_needed": False,
        "active_context": active_context,
        "trace": trace,
    }


def _dedupe_citations(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in citations:
        key = json.dumps(item, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique
