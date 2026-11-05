"""Env-gated capture of AI outputs the marking UI renders.

Enable with VEA_RECORD_INTERACTIONS=1. Files land in VEA_RECORD_INTERACTIONS_DIR
(default: data/recordings) as recording_001.json, recording_002.json, and so on.
One walkthrough step may produce several files; numbering is call order only.

Each file keeps the request plus the fields the frontend displays: intervention
type and message, nuance items, suggested evidence, level-review summary, and
new chat messages with citations. Graph context, prior history, and tool traces
are left out.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_RECORDING_NAME = re.compile(r"^recording_(\d+)\.json$")
_write_lock = threading.Lock()


def recording_enabled() -> bool:
    return os.getenv("VEA_RECORD_INTERACTIONS", "").strip().lower() in _TRUTHY


def _recordings_dir() -> Path:
    from app.paths import DATA_DIR

    raw = os.getenv("VEA_RECORD_INTERACTIONS_DIR", "").strip()
    if raw:
        return Path(raw)
    return DATA_DIR / "recordings"


def _next_number(directory: Path) -> int:
    highest = 0
    if directory.is_dir():
        for path in directory.glob("recording_*.json"):
            match = _RECORDING_NAME.match(path.name)
            if match:
                highest = max(highest, int(match.group(1)))
    return highest + 1


def _pick(source: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: source[key] for key in keys if key in source}


def _slim_intervention(intervention: Any) -> Any:
    if not isinstance(intervention, dict):
        return intervention
    slim = _pick(intervention, ("type", "message", "nuance_items"))
    items = slim.get("nuance_items")
    if isinstance(items, list):
        slim["nuance_items"] = [
            _pick(item, ("node_id", "relation", "text"))
            for item in items
            if isinstance(item, dict)
        ]
    return slim


def _slim_span(span: Any) -> dict[str, Any] | None:
    if not isinstance(span, dict):
        return None
    return _pick(span, ("start_char", "end_char", "text"))


def _slim_summary(summary: Any) -> dict[str, Any] | None:
    if not isinstance(summary, dict):
        return None
    slim = _pick(
        summary,
        (
            "level",
            "descriptor_text",
            "ai_check_label",
            "alignment",
            "evidence_mapped",
            "needs_attention",
            "key_guidance",
            "mapped_evidence_detail",
        ),
    )
    return slim or None


def _slim_interpretation(response: dict[str, Any]) -> dict[str, Any]:
    """Fields the evidence and level UI read back from an AI check."""
    slim = _pick(response, ("id", "coding_id", "status", "error"))
    if "intervention" in response:
        slim["intervention"] = _slim_intervention(response.get("intervention"))
    span = _slim_span(response.get("suggested_evidence_span") or response.get("suggested_span"))
    if span:
        slim["suggested_evidence_span"] = span
    relation = response.get("relation_check")
    if isinstance(relation, dict) and relation.get("relation"):
        slim["relation_check"] = {"relation": relation["relation"]}
    verdict = response.get("verdict")
    if isinstance(verdict, dict):
        alignment = verdict.get("alignment") or verdict.get("outcome")
        slim["verdict"] = {"alignment": alignment} if alignment else {}
    summary = _slim_summary(response.get("summary"))
    if summary:
        slim["summary"] = summary
    return slim


def _slim_citation(citation: dict[str, Any]) -> dict[str, Any]:
    return _pick(citation, ("type", "text", "criterion_id", "start_char", "end_char", "segment_id"))


def _slim_message(message: dict[str, Any]) -> dict[str, Any]:
    slim = _pick(message, ("id", "role", "content", "context_id", "created_at"))
    citations = message.get("citations")
    if isinstance(citations, list) and citations:
        slim["citations"] = [
            _slim_citation(item) for item in citations if isinstance(item, dict)
        ]
    return slim


def _slim_conversation_context(context: Any) -> dict[str, Any] | None:
    if not isinstance(context, dict):
        return None
    slim = _pick(context, ("context_id", "source", "coding_id", "level"))
    criterion = context.get("criterion")
    if isinstance(criterion, dict) and criterion.get("text"):
        slim["criterion"] = {"text": criterion["text"]}
    return slim or None


def _slim_conversation(
    response: dict[str, Any],
    new_message_ids: list[str],
) -> dict[str, Any]:
    """New turn only: tab identity plus messages and citations the panel renders."""
    wanted = set(new_message_ids)
    messages = [
        _slim_message(message)
        for message in response.get("messages") or []
        if isinstance(message, dict) and message.get("id") in wanted
    ]
    active = _slim_conversation_context(response.get("active_context"))
    slim: dict[str, Any] = {
        "active_context_id": response.get("active_context_id"),
        "messages": messages,
    }
    if active is not None:
        slim["active_context"] = active
        slim["contexts"] = [active]
    return slim


def playback_response(
    kind: str,
    response: dict[str, Any],
    new_message_ids: list[str] | None = None,
) -> dict[str, Any]:
    if kind in {"evidence_check", "level_check"}:
        return _slim_interpretation(response)
    if kind in {"conversation_launch", "conversation_message"}:
        return _slim_conversation(response, new_message_ids or [])
    return response


def message_delta(
    prior_messages: list[Any],
    response: dict[str, Any],
) -> tuple[list[str], list[Any]]:
    """Ids and citations for messages present in the response but not before the call."""
    prior_ids = {
        message.get("id")
        for message in prior_messages
        if isinstance(message, dict) and message.get("id")
    }
    new_ids: list[str] = []
    citations: list[Any] = []
    for message in response.get("messages", []):
        if not isinstance(message, dict):
            continue
        message_id = message.get("id")
        if message_id in prior_ids:
            continue
        if message_id:
            new_ids.append(message_id)
        extra = message.get("citations") or []
        if isinstance(extra, list):
            citations.extend(extra)
    return new_ids, citations


def record_interaction(
    kind: str,
    *,
    endpoint: str,
    request: dict[str, Any],
    response: dict[str, Any],
    context: dict[str, Any],
    new_message_ids: list[str] | None = None,
) -> Path | None:
    """Write the next recording_NNN.json. Returns None when recording is off or the write fails."""
    if not recording_enabled():
        return None
    try:
        stored = playback_response(kind, response, new_message_ids)
        out_dir = _recordings_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        with _write_lock:
            number = _next_number(out_dir)
            artifact: dict[str, Any] = {
                "recording": number,
                "kind": kind,
                "endpoint": endpoint,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "context": context,
                "request": request,
                "response": stored,
            }
            path = out_dir / f"recording_{number:03d}.json"
            with path.open("w", encoding="utf-8") as handle:
                json.dump(artifact, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
        return path
    except Exception:
        logger.warning("failed to save interaction recording", exc_info=True)
        return None
