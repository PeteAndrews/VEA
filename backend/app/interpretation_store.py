"""Persistence for evidence- and level-scoped AI interpretations."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AIInterpretationStore:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    def _path(self, marking_session_id: str, response_id: str) -> Path:
        return self.base_dir / marking_session_id / f"{response_id}.json"

    def load(self, marking_session_id: str, response_id: str) -> dict[str, Any]:
        path = self._path(marking_session_id, response_id)
        if not path.is_file():
            return self._empty_payload(marking_session_id, response_id)
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        payload.setdefault("interpretations", [])
        payload.setdefault("level_interpretations", [])
        return payload

    def save(self, payload: dict[str, Any]) -> None:
        path = self._path(payload["marking_session_id"], payload["response_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        payload["schema_version"] = SCHEMA_VERSION
        payload["updated_at"] = _utc_now()
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        os.replace(tmp_path, path)

    def _empty_payload(self, marking_session_id: str, response_id: str) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "marking_session_id": marking_session_id,
            "response_id": response_id,
            "interpretations": [],
            "level_interpretations": [],
        }

    def add_evidence(self, payload: dict[str, Any], interpretation: dict[str, Any]) -> dict[str, Any]:
        now = _utc_now()
        for existing in payload["interpretations"]:
            if existing.get("coding_id") == interpretation["coding_id"] and existing.get("status") != "superseded":
                existing["status"] = "superseded"
                existing["superseded_by"] = interpretation["id"]
                existing["updated_at"] = now
        payload["interpretations"].append(interpretation)
        return interpretation

    def add_level(self, payload: dict[str, Any], interpretation: dict[str, Any]) -> dict[str, Any]:
        now = _utc_now()
        for existing in payload.get("level_interpretations", []):
            if existing.get("status") == "superseded":
                continue
            if existing.get("level") != interpretation.get("level"):
                continue
            existing["status"] = "superseded"
            existing["superseded_by"] = interpretation["id"]
            existing["updated_at"] = now
        payload.setdefault("level_interpretations", []).append(interpretation)
        return interpretation

    def find_evidence(self, payload: dict[str, Any], ai_id: str) -> dict[str, Any]:
        for interpretation in payload.get("interpretations", []):
            if interpretation["id"] == ai_id:
                return interpretation
        raise KeyError(ai_id)

    def find_level(self, payload: dict[str, Any], ai_id: str) -> dict[str, Any]:
        for interpretation in payload.get("level_interpretations", []):
            if interpretation["id"] == ai_id:
                return interpretation
        raise KeyError(ai_id)

    def add(self, payload: dict[str, Any], interpretation: dict[str, Any]) -> dict[str, Any]:
        return self.add_evidence(payload, interpretation)

    def find(self, payload: dict[str, Any], ai_id: str) -> dict[str, Any]:
        return self.find_evidence(payload, ai_id)


def _coding_matches(interpretation: dict[str, Any], relation: dict[str, Any], span: dict[str, Any]) -> bool:
    return (
        interpretation["criterion_id"] == relation["target"]
        and interpretation["start_char"] == span["start_char"]
        and interpretation["end_char"] == span["end_char"]
    )


def active_interpretations(
    payload: dict[str, Any],
    judgement_state: dict[str, Any],
) -> list[dict[str, Any]]:
    spans = {span["id"]: span for span in judgement_state.get("evidence_spans", [])}
    relations = {relation["id"]: relation for relation in judgement_state.get("relations", [])}
    active: list[dict[str, Any]] = []
    for interpretation in payload.get("interpretations", []):
        if interpretation.get("status") == "superseded":
            continue
        relation = relations.get(interpretation.get("coding_id"))
        if relation is None:
            continue
        span = spans.get(relation["source"])
        if span is None or not _coding_matches(interpretation, relation, span):
            continue
        active.append(interpretation)
    return active


def active_level_interpretation(
    payload: dict[str, Any],
    judgement_state: dict[str, Any],
) -> dict[str, Any] | None:
    tentative = judgement_state.get("tentative_level")
    if tentative is None:
        return None
    fingerprint = judgement_fingerprint(judgement_state)
    matches: list[dict[str, Any]] = []
    for interpretation in payload.get("level_interpretations", []):
        if interpretation.get("status") in {"superseded", "error"}:
            continue
        if interpretation.get("level") != tentative.get("level"):
            continue
        if interpretation.get("judgement_fingerprint") != fingerprint:
            continue
        matches.append(interpretation)
    if not matches:
        return None
    matches.sort(key=lambda item: item.get("updated_at") or item.get("created_at") or "")
    return matches[-1]


def judgement_fingerprint(judgement_state: dict[str, Any]) -> str:
    tentative = judgement_state.get("tentative_level") or {}
    relations = sorted(
        (
            relation["id"],
            relation["target"],
            relation["source"],
        )
        for relation in judgement_state.get("relations", [])
    )
    spans = sorted(
        (
            span["id"],
            span["start_char"],
            span["end_char"],
        )
        for span in judgement_state.get("evidence_spans", [])
    )
    payload = {
        "level": tentative.get("level"),
        "level_node_id": tentative.get("level_node_id"),
        "relations": relations,
        "spans": spans,
    }
    return json.dumps(payload, sort_keys=True)


_CLIENT_HIDDEN_KEYS = frozenset(
    {
        "response_id",
        "jev",
        "jev_direct",
        "jev_additional",
    }
)

_PUBLIC_RELATION_CHECK_KEYS = (
    "relation",
    "probability",
    "confidence",
    "probabilities",
    "needs_review",
    "status",
)


def _public_relation_check(interpretation: dict[str, Any]) -> dict[str, Any] | None:
    check = interpretation.get("jev_direct") or interpretation.get("jev")
    if not check:
        return None
    return {key: check[key] for key in _PUBLIC_RELATION_CHECK_KEYS if key in check}


def _sanitize_intervention_message(message: str) -> str:
    if not message:
        return message
    replacements = (
        (
            "Jev could not reliably decide whether this evidence supports",
            "The evidence check could not reliably decide whether this supports",
        ),
        ("Jev reads this evidence as", "This evidence reads as"),
        ("Jev agrees this supports", "This evidence appears to support"),
    )
    updated = message
    for old, new in replacements:
        updated = updated.replace(old, new)
    return updated


def _public_intervention(intervention: dict[str, Any] | None) -> dict[str, Any] | None:
    if not intervention:
        return intervention
    payload = dict(intervention)
    message = payload.get("message")
    if isinstance(message, str):
        payload["message"] = _sanitize_intervention_message(message)
    reasons = payload.get("reasons")
    if isinstance(reasons, list):
        payload["reasons"] = [
            "classifier_disagrees" if reason == "jev_disagrees" else reason
            for reason in reasons
        ]
        payload["reasons"] = [
            "uncertain_relation" if reason == "jev_uncertain" else reason
            for reason in payload["reasons"]
        ]
    return payload


def public_interpretation(interpretation: dict[str, Any]) -> dict[str, Any]:
    payload = {
        key: value
        for key, value in interpretation.items()
        if key not in _CLIENT_HIDDEN_KEYS
    }
    relation_check = _public_relation_check(interpretation)
    if relation_check is not None:
        payload["relation_check"] = relation_check
    if "intervention" in payload:
        payload["intervention"] = _public_intervention(payload.get("intervention"))
    return payload
