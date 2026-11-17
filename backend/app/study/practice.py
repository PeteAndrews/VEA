"""Study-level practice (walkthrough) question configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def practice_config_for_subject(
    study_config: dict[str, Any],
    subject: str,
) -> dict[str, Any] | None:
    subjects = study_config.get("subjects") or {}
    entry = subjects.get(subject) or subjects.get(str(subject).strip().lower())
    if not entry:
        return None
    practice = entry.get("practice")
    if isinstance(practice, dict) and practice.get("assessment_id"):
        return _normalize_practice(practice)
    walkthrough = entry.get("walkthrough") or {}
    if walkthrough.get("assessment_id") and walkthrough.get("response_id"):
        return {
            "assessment_id": str(walkthrough["assessment_id"]),
            "vea": {
                "response_id": str(walkthrough["response_id"]),
                "candidate_id": str(walkthrough.get("candidate_id") or ""),
            },
            "baseline": {},
        }
    return None


def _normalize_practice(practice: dict[str, Any]) -> dict[str, Any]:
    assessment_id = str(practice["assessment_id"])
    vea = dict(practice.get("vea") or {})
    baseline = dict(practice.get("baseline") or {})
    return {
        "assessment_id": assessment_id,
        "vea": vea,
        "baseline": baseline,
    }


def resolve_candidate_id(
    data_dir: str | Path,
    assessment_id: str,
    response_id: str,
) -> str:
    from app.views import _candidate_aliases_for_assessment, _list_response_ids_for_assessment

    responses_dir = Path(data_dir) / "responses"
    response_ids = _list_response_ids_for_assessment(responses_dir, assessment_id)
    if response_id not in response_ids:
        raise ValueError(f"Practice response not found: {response_id}")
    aliases = _candidate_aliases_for_assessment(data_dir, assessment_id, response_ids)
    candidate_id = aliases.get(response_id)
    if not candidate_id:
        raise ValueError(f"Could not resolve candidate for {response_id}")
    return str(candidate_id)


def practice_condition_config(
    practice: dict[str, Any],
    condition: str,
    data_dir: str | Path,
) -> dict[str, str] | None:
    block = practice.get(condition) or {}
    response_id = block.get("response_id")
    if not response_id:
        return None
    assessment_id = practice["assessment_id"]
    candidate_id = block.get("candidate_id") or ""
    if not candidate_id:
        candidate_id = resolve_candidate_id(data_dir, assessment_id, str(response_id))
    return {
        "assessment_id": str(assessment_id),
        "response_id": str(response_id),
        "candidate_id": str(candidate_id),
    }
