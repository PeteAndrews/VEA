"""Study configuration loading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

EXPERIENCE_BY_CONDITION = {
    "vea": "vea_marking",
    "control": "control_placeholder",
}


def config_root(project_root: str | Path | None = None) -> Path:
    root = Path(project_root or Path.cwd())
    return root / "config" / "studies"


def load_study_config(study_id: str, project_root: str | Path | None = None) -> dict[str, Any]:
    path = config_root(project_root) / f"{study_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Study config not found: {path}")
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def participants_path(study_id: str, project_root: str | Path | None = None) -> Path:
    return config_root(project_root) / f"{study_id}-participants.json"


def load_participants_config(study_id: str, project_root: str | Path | None = None) -> dict[str, Any]:
    path = participants_path(study_id, project_root)
    if not path.is_file():
        raise FileNotFoundError(f"Participants file not found: {path}")
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("study_id") and payload["study_id"] != study_id:
        raise ValueError(
            f"Participants file study_id mismatch: {payload['study_id']} != {study_id}"
        )
    return payload


def find_participant_by_token(
    token: str,
    project_root: str | Path | None = None,
) -> tuple[str, dict[str, Any]] | None:
    """Return (study_id, participant entry) from participants JSON files."""
    cleaned = token.strip()
    if not cleaned:
        return None
    for path in sorted(config_root(project_root).glob("*-participants.json")):
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        study_id = payload.get("study_id") or path.name.removesuffix("-participants.json")
        for entry in payload.get("participants", []):
            entry_token = str(entry.get("token") or "").strip()
            if entry_token == cleaned:
                return study_id, entry
    return None


def subject_assessment_order(
    study_config: dict[str, Any],
    subject: str,
) -> list[str] | None:
    subjects = study_config.get("subjects") or {}
    entry = subjects.get(subject) or subjects.get(subject.strip().lower())
    if not entry:
        return None
    order = entry.get("assessment_order")
    if order is None:
        return None
    return list(order)


def experience_for_condition(condition: str, study_config: dict[str, Any] | None = None) -> str:
    profiles = (study_config or {}).get("condition_profiles") or EXPERIENCE_BY_CONDITION
    experience = profiles.get(condition)
    if experience is None:
        raise ValueError(f"Unknown condition: {condition}")
    return experience
