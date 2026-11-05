from __future__ import annotations

import json
import os
import threading
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.classifier import load_env_file
from app.evidence import build_response_local_context_for_span
from app.intervention import build_intervention_context
from app.stages import resolve_stage

CONVERSATION_SOURCES = frozenset({"explore", "verify", "general", "explore_level", "verify_level"})
MESSAGE_ROLES = frozenset({"user", "assistant", "system"})
from app.paths import PROMPTS_DIR

DEFAULT_PROMPTS_DIR = PROMPTS_DIR
DEFAULT_LLM_PROVIDER = "openai"
DEFAULT_LLM_MODEL = "gpt-4.1-mini"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
_FILE_LOCKS: dict[str, threading.Lock] = {}


def _conversation_file_lock(path: Path) -> threading.Lock:
    key = str(path.resolve())
    lock = _FILE_LOCKS.get(key)
    if lock is None:
        lock = threading.Lock()
        _FILE_LOCKS[key] = lock
    return lock


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class PromptLoader:
    def __init__(self, prompts_dir: Path | None = None) -> None:
        self.prompts_dir = prompts_dir or DEFAULT_PROMPTS_DIR

    def load(self, name: str) -> str:
        path = self.prompts_dir / name
        if not path.is_file():
            raise FileNotFoundError(f"Prompt file not found: {path}")
        return path.read_text(encoding="utf-8").strip()

    def load_system(self) -> str:
        return self.load("system.txt")

    def load_launch(self, source: str) -> str:
        if source == "explore":
            return self.load("explore_intervention.txt")
        if source == "verify":
            return self.load("verify_evidence.txt")
        if source == "explore_level":
            return self.load("level_explore.txt")
        if source == "verify_level":
            return self.load("level_verify.txt")
        if source == "general":
            return self.load("general_launch.txt")
        raise ValueError(f"Unsupported conversation source: {source}")

    def load_level_conversation(self) -> str:
        return self.load("level_conversation.txt")


class ConversationStore:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    def _path(self, marking_session_id: str, response_id: str) -> Path:
        return self.base_dir / marking_session_id / f"{response_id}.json"

    def load(self, marking_session_id: str, response_id: str) -> dict[str, Any]:
        path = self._path(marking_session_id, response_id)
        if not path.is_file():
            return {
                "schema_version": 1,
                "conversation_id": _new_id("conv"),
                "marking_session_id": marking_session_id,
                "response_id": response_id,
                "active_context_id": None,
                "contexts": [],
                "messages": [],
                "created_at": _utc_now(),
                "updated_at": _utc_now(),
            }
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)

    def save(self, payload: dict[str, Any]) -> None:
        path = self._path(payload["marking_session_id"], payload["response_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        payload["updated_at"] = _utc_now()
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        os.replace(tmp_path, path)

    def merge_and_save(
        self,
        marking_session_id: str,
        response_id: str,
        mutator: Any,
    ) -> dict[str, Any]:
        path = self._path(marking_session_id, response_id)
        with _conversation_file_lock(path):
            payload = self.load(marking_session_id, response_id)
            mutator(payload)
            self.save(payload)
            return payload


def _find_coding(state: dict[str, Any], coding_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    relation = next(
        (item for item in state.get("relations", []) if item["id"] == coding_id),
        None,
    )
    if relation is not None:
        span = next(
            (item for item in state.get("evidence_spans", []) if item["id"] == relation["source"]),
            None,
        )
        if span is None:
            raise KeyError(relation["source"])
        return relation, span

    coding = next(
        (item for item in state.get("codings", []) if item["id"] == coding_id),
        None,
    )
    if coding is None:
        raise KeyError(coding_id)
    span = {
        "id": coding["id"],
        "start_char": coding["start_char"],
        "end_char": coding["end_char"],
        "text": coding["text"],
    }
    relation = {
        "id": coding["id"],
        "relation": coding["relation"],
        "origin": coding.get("origin"),
        "examiner_id": coding.get("examiner_id"),
        "source": coding["id"],
        "target": coding["criterion_id"],
    }
    return relation, span


def _find_interpretation_for_coding(
    ai_payload: dict[str, Any],
    coding_id: str,
) -> dict[str, Any] | None:
    matches = [
        item
        for item in ai_payload.get("interpretations", [])
        if item.get("coding_id") == coding_id and item.get("status") != "superseded"
    ]
    if not matches:
        return None
    matches.sort(key=lambda item: item.get("updated_at") or item.get("created_at") or "")
    return matches[-1]


def build_level_conversation_context(
    *,
    judgement_state: dict[str, Any],
    source: str,
    interpretation: dict[str, Any] | None,
    stage: str | None = None,
    stage_source: str | None = None,
) -> dict[str, Any]:
    if source not in {"explore_level", "verify_level"}:
        raise ValueError(f"Unsupported level conversation source: {source}")

    resolved_stage, resolved_stage_source = resolve_stage(judgement_state, stage, None)
    return {
        "context_id": _new_id("ctx"),
        "source": source,
        "stage": resolved_stage,
        "stage_source": stage_source or resolved_stage_source,
        "kind": "level",
        "level": interpretation.get("level") if interpretation else None,
        "verdict": interpretation.get("verdict") if interpretation else None,
        "intervention": interpretation.get("intervention") if interpretation else None,
        "summary": interpretation.get("summary") if interpretation else None,
        "context": interpretation.get("context") if interpretation else None,
        "uncoded_candidates": interpretation.get("uncoded_candidates") if interpretation else None,
        "interpretation_id": interpretation.get("id") if interpretation else None,
        "tentative_level": judgement_state.get("tentative_level"),
        "prepared_at": _utc_now(),
    }


def build_conversation_context(
    *,
    graph_service,
    record: dict[str, Any],
    judgement_state: dict[str, Any],
    coding_id: str,
    source: str,
    interpretation: dict[str, Any] | None,
    stage: str | None = None,
    stage_source: str | None = None,
) -> dict[str, Any]:
    from app.assistant_context import finalize_new_context

    if source not in CONVERSATION_SOURCES:
        raise ValueError(f"Unsupported conversation source: {source}")

    relation, span = _find_coding(judgement_state, coding_id)
    graph_context = build_intervention_context(graph_service, relation["target"])
    resolved_stage, resolved_stage_source = resolve_stage(judgement_state, stage, None)

    context: dict[str, Any] = {
        "context_id": _new_id("ctx"),
        "source": source,
        "stage": resolved_stage,
        "stage_source": stage_source or resolved_stage_source,
        "coding_id": coding_id,
        "evidence": {
            "evidence_id": span["id"],
            "text": span["text"],
            "start_char": span["start_char"],
            "end_char": span["end_char"],
        },
        "interpretive_context": (
            interpretation.get("interpretive_context")
            if interpretation and interpretation.get("interpretive_context")
            else build_response_local_context_for_span(
                record,
                start_char=span["start_char"],
                end_char=span["end_char"],
            )
        ),
        "criterion": graph_context["criterion"],
        "parent_criterion": graph_context["parent_criterion"],
        "examiner_judgement": {
            "relation": relation["relation"],
            "origin": relation.get("origin"),
            "examiner_id": relation.get("examiner_id"),
        },
        "kind": "link",
        "jev": interpretation.get("jev") if interpretation else None,
        "jev_direct": interpretation.get("jev_direct") if interpretation else None,
        "jev_additional": interpretation.get("jev_additional") if interpretation else None,
        "suggested_evidence_span": interpretation.get("suggested_evidence_span")
        if interpretation
        else None,
        "additional_evidence": interpretation.get("additional_evidence") if interpretation else None,
        "intervention": interpretation.get("intervention") if interpretation else None,
        "interpretation_id": interpretation.get("id") if interpretation else None,
        "graph_context": {
            "node_ids": graph_context["context_node_ids"],
            "guidance": graph_context["guidance"],
            "question": graph_context["question"],
        },
        "tentative_level": judgement_state.get("tentative_level"),
        "prepared_at": _utc_now(),
    }
    return finalize_new_context(context)


def public_conversation(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "conversation_id": payload["conversation_id"],
        "marking_session_id": payload["marking_session_id"],
        "assessment_id": payload.get("assessment_id"),
        "response_id": payload["response_id"],
        "active_context_id": payload.get("active_context_id"),
        "active_context": _active_context(payload),
        "contexts": payload.get("contexts", []),
        "messages": payload.get("messages", []),
        "updated_at": payload.get("updated_at"),
    }


def _active_context(payload: dict[str, Any]) -> dict[str, Any] | None:
    active_id = payload.get("active_context_id")
    if not active_id:
        return None
    for context in payload.get("contexts", []):
        if context["context_id"] == active_id:
            return context
    return None


def _compact_criterion(node: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(node, dict):
        return None
    payload = {key: node[key] for key in ("id", "text", "primary", "alternatives") if key in node}
    return payload or None


def _compact_interpretive_context(context: dict[str, Any]) -> dict[str, Any] | None:
    interpretive = context.get("interpretive_context")
    if not isinstance(interpretive, dict):
        return None
    compact = {
        key: interpretive[key]
        for key in ("preceding_segment", "following_segment")
        if key in interpretive
    }
    compact["note"] = (
        "Judge whether evidence.text supports the criterion. Neighbouring response text may help "
        "interpret wording in the coded span but does not count as linked evidence."
    )
    return compact


def compact_context_for_llm(context: dict[str, Any]) -> dict[str, Any]:
    """Strip quoted guidance and boilerplate before sending context to the LLM."""
    if context.get("anchor"):
        from app.assistant_context import compact_layers_for_llm, ensure_layers

        return compact_layers_for_llm(ensure_layers(context))
    compact = dict(context)
    graph = dict(compact.get("graph_context") or {})
    graph["guidance"] = [
        {"relation": item.get("relation"), "scope": item.get("scope")}
        for item in graph.get("guidance", [])
    ]
    graph.pop("question", None)
    compact["graph_context"] = graph

    intervention = compact.get("intervention")
    if isinstance(intervention, dict):
        compact["intervention"] = {
            "type": intervention.get("type"),
            "reasons": intervention.get("reasons"),
        }
        if intervention.get("type") == "REVIEW":
            compact["borderline_link"] = True
            compact["borderline_reasons"] = list(intervention.get("reasons") or [])

    compact["criterion"] = _compact_criterion(compact.get("criterion"))
    compact["parent_criterion"] = _compact_criterion(compact.get("parent_criterion"))
    compact["interpretive_context"] = _compact_interpretive_context(context)

    return compact


def _append_message(
    payload: dict[str, Any],
    *,
    role: str,
    content: str,
    context_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if role not in MESSAGE_ROLES:
        raise ValueError(f"Unsupported message role: {role}")
    message = {
        "id": _new_id("msg"),
        "role": role,
        "content": content,
        "context_id": context_id,
        "created_at": _utc_now(),
    }
    if metadata:
        message.update(metadata)
    payload.setdefault("messages", []).append(message)
    return message


class ConversationLLM(ABC):
    name: str

    @abstractmethod
    def respond(
        self,
        *,
        system_prompt: str,
        launch_prompt: str,
        active_context: dict[str, Any],
        messages: list[dict[str, Any]],
    ) -> str:
        ...

    @abstractmethod
    def respond_with_tools(
        self,
        *,
        instructions: str,
        input_items: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        ...


def _conversation_history_for_llm(
    messages: list[dict[str, Any]],
    *,
    context_id: str | None = None,
) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    for message in messages:
        if message["role"] not in {"user", "assistant"}:
            continue
        if context_id is not None and message.get("context_id") != context_id:
            continue
        history.append({"role": message["role"], "content": message["content"]})
    return history


class OpenAIConversationLLM(ConversationLLM):
    name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        load_env_file()
        self.api_key = (api_key or os.environ.get("OPENAI_API_KEY") or "").strip()
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not set.")
        self.model = model or os.environ.get("LLM_MODEL", DEFAULT_LLM_MODEL)
        self.timeout = timeout
        self._client = client

    def respond(
        self,
        *,
        system_prompt: str,
        launch_prompt: str,
        active_context: dict[str, Any],
        messages: list[dict[str, Any]],
    ) -> str:
        input_messages = [
            {
                "role": "system",
                "content": (
                    f"{system_prompt}\n\n"
                    f"Launch instructions:\n{launch_prompt}\n\n"
                    f"Active context JSON:\n{json.dumps(compact_context_for_llm(active_context), indent=2)}"
                ),
            },
            *_conversation_history_for_llm(
                messages,
                context_id=active_context.get("context_id"),
            ),
        ]
        payload = {
            "model": self.model,
            "input": input_messages,
        }
        if self._client is not None:
            response = self._client.post(
                OPENAI_RESPONSES_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        else:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    OPENAI_RESPONSES_URL,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        if response.status_code >= 400:
            raise RuntimeError(
                f"OpenAI API error {response.status_code}: {response.text[:500]}"
            )
        data = response.json()
        text = _extract_openai_text(data)
        if not text:
            raise RuntimeError("OpenAI API returned no assistant text.")
        return text

    def respond_with_tools(
        self,
        *,
        instructions: str,
        input_items: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "instructions": instructions,
            "input": input_items,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self._client is not None:
            response = self._client.post(OPENAI_RESPONSES_URL, headers=headers, json=payload)
        else:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(OPENAI_RESPONSES_URL, headers=headers, json=payload)
        if response.status_code >= 400:
            raise RuntimeError(
                f"OpenAI API error {response.status_code}: {response.text[:500]}"
            )
        return _parse_openai_tool_response(response.json())


def _function_call_input_item(item: dict[str, Any]) -> dict[str, Any]:
    """Build a Responses API input item that pairs with function_call_output."""
    raw_args = item.get("arguments") or "{}"
    if not isinstance(raw_args, str):
        raw_args = json.dumps(raw_args)
    payload: dict[str, Any] = {
        "type": "function_call",
        "call_id": item.get("call_id") or item.get("id"),
        "name": item.get("name"),
        "arguments": raw_args,
    }
    if item.get("id"):
        payload["id"] = item["id"]
    return payload


def _parse_openai_tool_response(data: dict[str, Any]) -> dict[str, Any]:
    calls: list[dict[str, Any]] = []
    for item in data.get("output", []):
        item_type = item.get("type")
        if item_type == "function_call":
            raw_args = item.get("arguments") or "{}"
            if isinstance(raw_args, str):
                try:
                    arguments = json.loads(raw_args)
                except json.JSONDecodeError:
                    arguments = {}
            else:
                arguments = dict(raw_args)
            call_id = item.get("call_id") or item.get("id")
            calls.append(
                {
                    "name": item.get("name"),
                    "arguments": arguments,
                    "call_id": call_id,
                    "input_call": _function_call_input_item(item),
                }
            )
        elif item_type == "message":
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"} and content.get("text"):
                    text = str(content["text"]).strip()
                    if text:
                        return {"type": "text", "text": text}
    if calls:
        return {"type": "tool_calls", "calls": calls}
    text = _extract_openai_text(data)
    if text:
        return {"type": "text", "text": text}
    return {"type": "text", "text": ""}


def _extract_openai_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str) and data["output_text"].strip():
        return data["output_text"].strip()
    chunks: list[str] = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                chunks.append(str(content["text"]))
            elif content.get("type") == "text" and content.get("text"):
                chunks.append(str(content["text"]))
    return "\n".join(part.strip() for part in chunks if part.strip()).strip()


class FakeConversationLLM(ConversationLLM):
    name = "fake"

    def __init__(self, response: str = "Assistant reply.") -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def respond(
        self,
        *,
        system_prompt: str,
        launch_prompt: str,
        active_context: dict[str, Any],
        messages: list[dict[str, Any]],
    ) -> str:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "launch_prompt": launch_prompt,
                "active_context": active_context,
                "messages": list(messages),
            }
        )
        if not messages:
            source = active_context.get("source") or active_context.get("intent") or "turn"
            return f"{self.response} [{source}]"
        return self.response

    def respond_with_tools(
        self,
        *,
        instructions: str,
        input_items: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "respond_with_tools": True,
                "instructions": instructions,
                "input_items": list(input_items),
                "tools": list(tools),
            }
        )
        return {"type": "text", "text": self.response}


class ScriptedToolLLM(FakeConversationLLM):
    """Test double that returns queued tool-call rounds then text."""

    def __init__(self, script: list[dict[str, Any]], final_text: str = "Done.") -> None:
        super().__init__(final_text)
        self.script = list(script)
        self.tool_calls: list[dict[str, Any]] = []

    def respond_with_tools(
        self,
        *,
        instructions: str,
        input_items: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        self.tool_calls.append({"instructions": instructions, "tools": tools})
        if self.script:
            step = self.script.pop(0)
            if step.get("calls"):
                calls = []
                for raw in step["calls"]:
                    call_id = raw.get("call_id") or "call-test"
                    name = raw.get("name", "")
                    args = raw.get("arguments") or {}
                    if isinstance(args, str):
                        arg_str = args
                        try:
                            parsed_args = json.loads(args)
                        except json.JSONDecodeError:
                            parsed_args = {}
                    else:
                        parsed_args = dict(args)
                        arg_str = json.dumps(args)
                    calls.append(
                        {
                            "name": name,
                            "arguments": parsed_args,
                            "call_id": call_id,
                            "input_call": {
                                "type": "function_call",
                                "call_id": call_id,
                                "name": name,
                                "arguments": arg_str,
                            },
                        }
                    )
                return {"type": "tool_calls", "calls": calls}
            return {"type": "text", "text": step.get("text") or self.response}
        return {"type": "text", "text": self.response}


def get_conversation_llm() -> ConversationLLM:
    load_env_file()
    provider = (os.environ.get("LLM_PROVIDER") or DEFAULT_LLM_PROVIDER).strip().lower()
    if provider == "openai":
        return OpenAIConversationLLM()
    raise RuntimeError(f"Unsupported LLM provider: {provider}")


def launch_conversation(
    *,
    conversation_store: ConversationStore,
    llm: ConversationLLM,
    prompt_loader: PromptLoader,
    graph_service,
    record: dict[str, Any],
    judgement_state: dict[str, Any],
    assessment_id: str,
    source: str,
    coding_id: str | None = None,
    interpretation: dict[str, Any] | None = None,
    stage: str | None = None,
    stage_source: str | None = None,
    data_dir: str = "data",
    classifier=None,
    retrieval_service=None,
) -> dict[str, Any]:
    from app.assistant import build_session_context

    if source in {"explore_level", "verify_level"}:
        active_context = build_level_conversation_context(
            judgement_state=judgement_state,
            source=source,
            interpretation=interpretation,
            stage=stage,
            stage_source=stage_source,
        )
    elif source == "general" or coding_id is None:
        active_context = build_session_context(
            graph_service=graph_service,
            record=record,
            judgement_state=judgement_state,
            assessment_id=assessment_id,
            data_dir=data_dir,
            source="general",
            stage=stage,
            stage_source=stage_source,
        )
    else:
        active_context = build_conversation_context(
            graph_service=graph_service,
            record=record,
            judgement_state=judgement_state,
            coding_id=coding_id,
            source=source,
            interpretation=interpretation,
            stage=stage,
            stage_source=stage_source,
        )
    context_id = active_context["context_id"]

    def _mutate(stored: dict[str, Any]) -> None:
        stored.setdefault("contexts", []).append(active_context)
        stored["active_context_id"] = context_id
        stored["assessment_id"] = assessment_id
        if source in {"explore_level", "verify_level"}:
            system_prompt = prompt_loader.load_system()
            launch_prompt = prompt_loader.load_launch(source)
            assistant_text = llm.respond(
                system_prompt=system_prompt,
                launch_prompt=launch_prompt,
                active_context=active_context,
                messages=[],
            )
            turn = {"content": assistant_text, "trace": {}}
        else:
            from app.assistant_tool_loop import run_assistant_turn

            if classifier is None:
                raise ValueError("classifier is required for link/general launch.")
            turn = run_assistant_turn(
                content=None,
                active_context=active_context,
                graph_service=graph_service,
                record=record,
                judgement_state=judgement_state,
                classifier=classifier,
                retrieval_service=retrieval_service,
                llm=llm,
                prompt_loader=prompt_loader,
                history=[],
                data_dir=data_dir,
                launch=True,
            )
            for index, ctx in enumerate(stored.get("contexts", [])):
                if ctx.get("context_id") == context_id:
                    stored["contexts"][index] = turn["active_context"]
                    break
        _append_message(
            stored,
            role="assistant",
            content=turn["content"],
            context_id=context_id,
            metadata={"trace": turn.get("trace"), "citations": turn.get("citations", [])},
        )

    payload = conversation_store.merge_and_save(
        judgement_state["marking_session_id"],
        record["response_id"],
        _mutate,
    )
    return public_conversation(payload)


def send_conversation_message(
    *,
    conversation_store: ConversationStore,
    llm: ConversationLLM,
    prompt_loader: PromptLoader,
    marking_session_id: str,
    response_id: str,
    content: str,
    graph_service=None,
    record: dict[str, Any] | None = None,
    judgement_state: dict[str, Any] | None = None,
    classifier=None,
    intent_classifier=None,
    retrieval_service=None,
    assessment_id: str | None = None,
    data_dir: str | None = None,
) -> dict[str, Any]:
    from app.assistant import build_session_context, process_assistant_turn
    from app.assistant_context import ensure_layers

    context_id_holder: dict[str, str] = {}

    def _mutate(payload: dict[str, Any]) -> None:
        active_context = _active_context(payload)
        if active_context is None:
            if not all([graph_service, record, judgement_state, assessment_id, data_dir]):
                raise ValueError("No active conversation context.")
            active_context = build_session_context(
                graph_service=graph_service,
                record=record,
                judgement_state=judgement_state,
                assessment_id=assessment_id,
                data_dir=data_dir,
                source="general",
            )
            payload.setdefault("contexts", []).append(active_context)
            payload["active_context_id"] = active_context["context_id"]
        ensure_layers(active_context)
        context_id = active_context["context_id"]
        context_id_holder["id"] = context_id

        _append_message(
            payload,
            role="user",
            content=content,
            context_id=context_id,
        )
        context_messages = [
            message
            for message in payload.get("messages", [])
            if message.get("context_id") == context_id
            and message["role"] in {"user", "assistant"}
        ]

        from app.level_conversation import is_level_conversation_context, process_level_conversation_turn

        if is_level_conversation_context(active_context):
            turn = process_level_conversation_turn(
                active_context=active_context,
                llm=llm,
                prompt_loader=prompt_loader,
                messages=context_messages,
                context_id=context_id,
            )
        elif graph_service and record and judgement_state and classifier:
            turn = process_assistant_turn(
                content=content,
                active_context=active_context,
                graph_service=graph_service,
                record=record,
                judgement_state=judgement_state,
                classifier=classifier,
                retrieval_service=retrieval_service,
                llm=llm,
                prompt_loader=prompt_loader,
                history=context_messages[:-1],
                data_dir=data_dir or "data",
            )
        else:
            turn = None

        if turn is not None:
            for index, ctx in enumerate(payload.get("contexts", [])):
                if ctx["context_id"] == context_id:
                    payload["contexts"][index] = turn["active_context"]
                    break
            _append_message(
                payload,
                role="assistant",
                content=turn["content"],
                context_id=context_id,
                metadata={
                    "intent": turn.get("intent"),
                    "citations": turn.get("citations"),
                    "tool_results": turn.get("tool_results"),
                    "clarification_needed": turn.get("clarification_needed"),
                    "trace": turn.get("trace"),
                },
            )
        elif turn is None:
            system_prompt = prompt_loader.load_system()
            launch_prompt = prompt_loader.load_launch(active_context["source"])
            assistant_text = llm.respond(
                system_prompt=system_prompt,
                launch_prompt=launch_prompt,
                active_context=active_context,
                messages=context_messages,
            )
            _append_message(
                payload,
                role="assistant",
                content=assistant_text,
                context_id=context_id,
            )

    payload = conversation_store.merge_and_save(marking_session_id, response_id, _mutate)
    return public_conversation(payload)


def activate_conversation_context(
    *,
    conversation_store: ConversationStore,
    marking_session_id: str,
    response_id: str,
    context_id: str,
    assessment_id: str | None = None,
) -> dict[str, Any]:
    payload = conversation_store.load(marking_session_id, response_id)
    if assessment_id:
        payload["assessment_id"] = assessment_id
    if not any(context["context_id"] == context_id for context in payload.get("contexts", [])):
        raise KeyError(f"Context not found: {context_id}")
    payload["active_context_id"] = context_id
    conversation_store.save(payload)
    return public_conversation(payload)


def open_general_conversation_context(
    *,
    conversation_store: ConversationStore,
    graph_service,
    record: dict[str, Any],
    judgement_state: dict[str, Any],
    assessment_id: str,
    stage: str | None = None,
    stage_source: str | None = None,
    data_dir: str = "data",
) -> dict[str, Any]:
    from app.assistant import build_session_context

    payload = conversation_store.load(
        judgement_state["marking_session_id"],
        record["response_id"],
    )
    payload["assessment_id"] = assessment_id
    active_context = build_session_context(
        graph_service=graph_service,
        record=record,
        judgement_state=judgement_state,
        assessment_id=assessment_id,
        data_dir=data_dir,
        source="general",
        stage=stage,
        stage_source=stage_source,
    )
    payload.setdefault("contexts", []).append(active_context)
    payload["active_context_id"] = active_context["context_id"]
    conversation_store.save(payload)
    return public_conversation(payload)


def delete_conversation_context(
    *,
    conversation_store: ConversationStore,
    marking_session_id: str,
    response_id: str,
    context_id: str,
    assessment_id: str | None = None,
) -> dict[str, Any]:
    payload = conversation_store.load(marking_session_id, response_id)
    if assessment_id:
        payload["assessment_id"] = assessment_id
    contexts = payload.get("contexts", [])
    if not any(context["context_id"] == context_id for context in contexts):
        raise KeyError(f"Context not found: {context_id}")

    payload["contexts"] = [context for context in contexts if context["context_id"] != context_id]
    payload["messages"] = [
        message
        for message in payload.get("messages", [])
        if message.get("context_id") != context_id
    ]

    if payload.get("active_context_id") == context_id:
        remaining = payload["contexts"]
        payload["active_context_id"] = remaining[-1]["context_id"] if remaining else None

    conversation_store.save(payload)
    return public_conversation(payload)
