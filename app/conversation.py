from __future__ import annotations

import json
import os
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

CONVERSATION_SOURCES = frozenset({"explore", "verify", "general"})
MESSAGE_ROLES = frozenset({"user", "assistant", "system"})
DEFAULT_PROMPTS_DIR = Path(os.getenv("VEA_PROMPTS_DIR", "prompts"))
DEFAULT_LLM_PROVIDER = "openai"
DEFAULT_LLM_MODEL = "gpt-4.1-mini"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


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
        if source == "general":
            return self.load("general_launch.txt")
        raise ValueError(f"Unsupported conversation source: {source}")


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
    return context


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
) -> dict[str, Any]:
    from app.assistant import build_session_context

    payload = conversation_store.load(
        judgement_state["marking_session_id"],
        record["response_id"],
    )
    payload["assessment_id"] = assessment_id
    if source == "general" or coding_id is None:
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
    payload.setdefault("contexts", []).append(active_context)
    payload["active_context_id"] = active_context["context_id"]

    system_prompt = prompt_loader.load_system()
    launch_prompt = prompt_loader.load_launch(source)
    assistant_text = llm.respond(
        system_prompt=system_prompt,
        launch_prompt=launch_prompt,
        active_context=active_context,
        messages=[],
    )
    _append_message(
        payload,
        role="assistant",
        content=assistant_text,
        context_id=active_context["context_id"],
    )
    conversation_store.save(payload)
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

    payload = conversation_store.load(marking_session_id, response_id)
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

    _append_message(
        payload,
        role="user",
        content=content,
        context_id=active_context["context_id"],
    )
    context_messages = [
        message
        for message in payload.get("messages", [])
        if message.get("context_id") == active_context["context_id"]
        and message["role"] in {"user", "assistant"}
    ]

    if graph_service and record and judgement_state and classifier and intent_classifier:
        turn = process_assistant_turn(
            content=content,
            active_context=active_context,
            graph_service=graph_service,
            record=record,
            judgement_state=judgement_state,
            classifier=classifier,
            intent_classifier=intent_classifier,
            retrieval_service=retrieval_service,
            llm=llm,
            prompt_loader=prompt_loader,
            history=context_messages[:-1],
        )
        for index, context in enumerate(payload.get("contexts", [])):
            if context["context_id"] == active_context["context_id"]:
                payload["contexts"][index] = turn["active_context"]
                break
        _append_message(
            payload,
            role="assistant",
            content=turn["content"],
            context_id=active_context["context_id"],
            metadata={
                "intent": turn["intent"],
                "citations": turn["citations"],
                "tool_results": turn["tool_results"],
                "clarification_needed": turn["clarification_needed"],
            },
        )
    else:
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
            context_id=active_context["context_id"],
        )
    conversation_store.save(payload)
    return public_conversation(payload)
