from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.graph_service import GraphService
from app.views import _strip_display_text, levels_view

EVENT_TYPES = frozenset(
    {
        "EVIDENCE_CODED",
        "CODING_REVISED",
        "CODING_REMOVED",
        "TENTATIVE_LEVEL_SET",
        "TENTATIVE_LEVEL_CLEARED",
    }
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _span_id(start_char: int, end_char: int) -> str:
    return f"span-{start_char}-{end_char}"


def _new_relation_id() -> str:
    return f"rel-{uuid.uuid4().hex[:8]}"


def _new_session_id() -> str:
    return f"ms-{uuid.uuid4().hex[:8]}"


class JudgementStore:
    def __init__(self, judgements_dir: Path) -> None:
        self.judgements_dir = judgements_dir
        self.judgements_dir.mkdir(parents=True, exist_ok=True)

    def _session_path(self, marking_session_id: str) -> Path:
        return self.judgements_dir / marking_session_id / "session.json"

    def _judgement_path(self, marking_session_id: str, response_id: str) -> Path:
        return self.judgements_dir / marking_session_id / f"{response_id}.json"

    def _atomic_write(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        os.replace(tmp_path, path)

    def create_session(self, examiner_id: str, label: str | None = None) -> dict[str, Any]:
        marking_session_id = _new_session_id()
        now = _utc_now()
        session = {
            "marking_session_id": marking_session_id,
            "examiner_id": examiner_id,
            "label": label,
            "created_at": now,
        }
        self._atomic_write(self._session_path(marking_session_id), session)
        return session

    def get_session(self, marking_session_id: str) -> dict[str, Any]:
        path = self._session_path(marking_session_id)
        if not path.is_file():
            raise KeyError(marking_session_id)
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)

    def load(
        self,
        marking_session_id: str,
        assessment_id: str,
        response_id: str,
    ) -> dict[str, Any]:
        path = self._judgement_path(marking_session_id, response_id)
        if not path.is_file():
            return {
                "schema_version": 1,
                "marking_session_id": marking_session_id,
                "assessment_id": assessment_id,
                "response_id": response_id,
                "evidence_spans": [],
                "relations": [],
                "tentative_level": None,
                "events": [],
                "updated_at": None,
            }
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)

    def save(self, state: dict[str, Any]) -> None:
        state["updated_at"] = _utc_now()
        marking_session_id = state["marking_session_id"]
        response_id = state["response_id"]
        self._atomic_write(self._judgement_path(marking_session_id, response_id), state)


def _append_event(
    state: dict[str, Any],
    event_type: str,
    examiner_id: str,
    payload: dict[str, Any],
) -> None:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unknown event type: {event_type}")
    events = state.setdefault("events", [])
    seq = len(events) + 1
    events.append(
        {
            "seq": seq,
            "type": event_type,
            "at": _utc_now(),
            "examiner_id": examiner_id,
            "payload": payload,
        }
    )


def _validate_span(record: dict[str, Any], start_char: int, end_char: int, text: str) -> None:
    response_text = record["text"]
    if start_char < 0 or end_char <= start_char or end_char > len(response_text):
        raise ValueError("Invalid character offsets for response text")
    if response_text[start_char:end_char] != text:
        raise ValueError("Text does not match response slice at given offsets")


def _require_criterion(graph_service: GraphService, criterion_id: str) -> dict[str, Any]:
    try:
        node = graph_service.get_node(criterion_id)
    except KeyError as exc:
        raise KeyError(criterion_id) from exc
    if node.get("segment_type") != "indicative_point":
        raise ValueError(f"Node is not an indicative_point criterion: {criterion_id}")
    return node


def _find_span(state: dict[str, Any], start_char: int, end_char: int) -> dict[str, Any] | None:
    span_id = _span_id(start_char, end_char)
    for span in state["evidence_spans"]:
        if span["id"] == span_id:
            return span
    return None


def _ensure_span(
    state: dict[str, Any],
    record: dict[str, Any],
    start_char: int,
    end_char: int,
    text: str,
) -> dict[str, Any]:
    _validate_span(record, start_char, end_char, text)
    existing = _find_span(state, start_char, end_char)
    if existing is not None:
        return existing
    span = {
        "id": _span_id(start_char, end_char),
        "response_id": record["response_id"],
        "start_char": start_char,
        "end_char": end_char,
        "text": text,
        "created_at": _utc_now(),
    }
    state["evidence_spans"].append(span)
    return span


def _find_relation(state: dict[str, Any], span_id: str, criterion_id: str) -> dict[str, Any] | None:
    for relation in state["relations"]:
        if (
            relation["source"] == span_id
            and relation["target"] == criterion_id
            and relation["relation"] == "SUPPORTS"
            and relation.get("origin") == "examiner"
        ):
            return relation
    return None


def _find_relation_by_id(state: dict[str, Any], coding_id: str) -> dict[str, Any] | None:
    for relation in state["relations"]:
        if relation["id"] == coding_id:
            return relation
    return None


def _cleanup_orphan_span(state: dict[str, Any], span_id: str) -> None:
    if any(relation["source"] == span_id for relation in state["relations"]):
        return
    state["evidence_spans"] = [span for span in state["evidence_spans"] if span["id"] != span_id]


def _criterion_display(graph_service: GraphService, criterion_id: str) -> dict[str, Any]:
    node = graph_service.get_node(criterion_id)
    parent_id = node.get("parent_id")
    parent_text = None
    if parent_id:
        try:
            parent = graph_service.get_node(parent_id)
            if parent.get("segment_type") == "indicative_point":
                parent_text = _strip_display_text(parent["text"])
        except KeyError:
            parent_text = None
    return {
        "criterion_id": criterion_id,
        "criterion_text": _strip_display_text(node["text"]),
        "parent_key_step_id": parent_id if parent_text else None,
        "parent_key_step_text": parent_text,
    }


def create_coding(
    state: dict[str, Any],
    record: dict[str, Any],
    graph_service: GraphService,
    *,
    start_char: int,
    end_char: int,
    text: str,
    criterion_id: str,
    examiner_id: str,
) -> dict[str, Any]:
    _require_criterion(graph_service, criterion_id)
    span = _ensure_span(state, record, start_char, end_char, text)
    existing = _find_relation(state, span["id"], criterion_id)
    if existing is not None:
        return existing

    now = _utc_now()
    relation = {
        "id": _new_relation_id(),
        "source": span["id"],
        "target": criterion_id,
        "relation": "SUPPORTS",
        "origin": "examiner",
        "examiner_id": examiner_id,
        "created_at": now,
        "updated_at": now,
    }
    state["relations"].append(relation)
    _append_event(
        state,
        "EVIDENCE_CODED",
        examiner_id,
        {
            "coding_id": relation["id"],
            "span": {
                "start_char": start_char,
                "end_char": end_char,
                "text": text,
            },
            "criterion_id": criterion_id,
        },
    )
    return relation


def update_coding(
    state: dict[str, Any],
    record: dict[str, Any],
    graph_service: GraphService,
    coding_id: str,
    *,
    criterion_id: str | None = None,
    start_char: int | None = None,
    end_char: int | None = None,
    text: str | None = None,
    examiner_id: str,
) -> dict[str, Any]:
    relation = _find_relation_by_id(state, coding_id)
    if relation is None:
        raise KeyError(coding_id)

    before = {
        "coding_id": relation["id"],
        "span_id": relation["source"],
        "criterion_id": relation["target"],
    }
    old_span_id = relation["source"]

    if criterion_id is not None:
        _require_criterion(graph_service, criterion_id)
        duplicate = _find_relation(state, relation["source"], criterion_id)
        if duplicate is not None and duplicate["id"] != coding_id:
            raise ValueError("Coding already exists for this span and criterion")
        relation["target"] = criterion_id

    if start_char is not None or end_char is not None or text is not None:
        if start_char is None or end_char is None or text is None:
            raise ValueError("Provide start_char, end_char, and text together")
        span = _ensure_span(state, record, start_char, end_char, text)
        duplicate = _find_relation(state, span["id"], relation["target"])
        if duplicate is not None and duplicate["id"] != coding_id:
            raise ValueError("Coding already exists for this span and criterion")
        relation["source"] = span["id"]

    relation["updated_at"] = _utc_now()
    relation["examiner_id"] = examiner_id
    _cleanup_orphan_span(state, old_span_id)

    after = {
        "coding_id": relation["id"],
        "span_id": relation["source"],
        "criterion_id": relation["target"],
    }
    if before != after:
        _append_event(
            state,
            "CODING_REVISED",
            examiner_id,
            {"before": before, "after": after},
        )
    return relation


def remove_coding(
    state: dict[str, Any],
    coding_id: str,
    *,
    examiner_id: str,
) -> None:
    relation = _find_relation_by_id(state, coding_id)
    if relation is None:
        raise KeyError(coding_id)

    span_id = relation["source"]
    state["relations"] = [item for item in state["relations"] if item["id"] != coding_id]
    _cleanup_orphan_span(state, span_id)
    _append_event(
        state,
        "CODING_REMOVED",
        examiner_id,
        {
            "coding_id": coding_id,
            "span_id": span_id,
            "criterion_id": relation["target"],
        },
    )


def set_tentative_level(
    state: dict[str, Any],
    levels: list[dict[str, Any]],
    level: int | None,
    *,
    examiner_id: str,
) -> dict[str, Any] | None:
    previous = state.get("tentative_level")
    if level is None:
        if previous is not None:
            state["tentative_level"] = None
            _append_event(
                state,
                "TENTATIVE_LEVEL_CLEARED",
                examiner_id,
                {"previous_level": previous.get("level")},
            )
        return None

    entry = next((item for item in levels if item["level"] == level), None)
    if entry is None:
        raise ValueError(f"Unknown level: {level}")

    tentative = {
        "level": entry["level"],
        "level_node_id": entry.get("id"),
        "source": entry.get("source"),
        "examiner_id": examiner_id,
        "set_at": _utc_now(),
    }
    state["tentative_level"] = tentative
    _append_event(
        state,
        "TENTATIVE_LEVEL_SET",
        examiner_id,
        {
            "previous_level": previous.get("level") if previous else None,
            "level": tentative["level"],
            "level_node_id": tentative["level_node_id"],
        },
    )
    return tentative


def _span_by_id(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {span["id"]: span for span in state.get("evidence_spans", [])}


def judgement_view(
    state: dict[str, Any],
    graph_service: GraphService,
    data_dir: str | Path,
) -> dict[str, Any]:
    spans_by_id = _span_by_id(state)
    codings: list[dict[str, Any]] = []
    for relation in state.get("relations", []):
        span = spans_by_id.get(relation["source"])
        if span is None:
            continue
        criterion = _criterion_display(graph_service, relation["target"])
        codings.append(
            {
                "id": relation["id"],
                "relation": relation["relation"],
                "origin": relation.get("origin"),
                "start_char": span["start_char"],
                "end_char": span["end_char"],
                "text": span["text"],
                "created_at": relation.get("created_at"),
                "updated_at": relation.get("updated_at"),
                **criterion,
            }
        )

    tentative_level = state.get("tentative_level")
    level_context = None
    if tentative_level is not None:
        level_context = level_context_view(
            graph_service,
            data_dir,
            tentative_level["level"],
            state=state,
        )

    return {
        "marking_session_id": state["marking_session_id"],
        "assessment_id": state["assessment_id"],
        "spans": [
            {
                "id": span["id"],
                "start_char": span["start_char"],
                "end_char": span["end_char"],
                "text": span["text"],
            }
            for span in state.get("evidence_spans", [])
        ],
        "codings": codings,
        "tentative_level": tentative_level,
        "level_context": level_context,
    }


def level_context_view(
    graph_service: GraphService,
    data_dir: str | Path,
    level: int,
    *,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    levels_payload = levels_view(graph_service, data_dir)
    levels = levels_payload["levels"]
    entry = next((item for item in levels if item["level"] == level), None)
    if entry is None:
        raise ValueError(f"Unknown level: {level}")

    coding_ids_by_criterion: dict[str, list[str]] = {}
    if state is not None:
        spans_by_id = _span_by_id(state)
        for relation in state.get("relations", []):
            coding_ids_by_criterion.setdefault(relation["target"], []).append(relation["id"])

    required_criteria: list[dict[str, Any]] = []
    for node_id, node in graph_service.graph.nodes.items():
        if node["node_type"] != "level_rule" or node.get("level") != level:
            continue
        for edge in graph_service.graph.out_edges.get(node_id, []):
            if edge["kind"] != "assessment" or edge["relation"] != "REQUIRES":
                continue
            target_id = edge["target"]
            try:
                target = graph_service.get_node(target_id)
            except KeyError:
                continue
            required_criteria.append(
                {
                    "criterion_id": target_id,
                    "criterion_text": _strip_display_text(target["text"]),
                    "rule_id": node_id,
                    "rule_text": node["text"].strip(),
                    "coding_ids": coding_ids_by_criterion.get(target_id, []),
                }
            )

    return {
        "level": entry["level"],
        "label": entry["label"],
        "mark_range": entry.get("mark_range"),
        "text": entry.get("text"),
        "rules": entry.get("rules", []),
        "source": entry.get("source"),
        "provenance": entry.get("provenance"),
        "mark_range_source": entry.get("mark_range_source"),
        "required_criteria": required_criteria,
    }
