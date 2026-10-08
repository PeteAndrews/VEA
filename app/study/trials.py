"""Trial progression within a selected question."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.assessment_runtime import get_version_record
from app.judgement import JudgementStore
from app.study.store import StudyStore


def _maximum_mark(data_dir: str, assessment_id: str, artifact_version: str) -> int:
    if artifact_version == "legacy":
        from app.views import load_stage1

        stage1 = load_stage1(data_dir, assessment_id)
        return int(stage1["metadata"]["maximum_mark"])
    version = get_version_record(data_dir, assessment_id, artifact_version)
    return int(version["metadata"]["maximum_mark"])


def _responses_for_version(data_dir: str, assessment_id: str, artifact_version: str) -> list[dict[str, Any]]:
    if artifact_version == "legacy":
        from app.views import _candidate_aliases_for_assessment, _list_response_ids_for_assessment

        responses_dir = Path(data_dir) / "responses"
        response_ids = _list_response_ids_for_assessment(responses_dir, assessment_id)
        aliases = _candidate_aliases_for_assessment(data_dir, assessment_id, response_ids)
        return [
            {
                "response_id": response_id,
                "candidate_id": aliases[response_id],
                "response_order": index,
            }
            for index, response_id in enumerate(sorted(response_ids), start=1)
        ]

    version = get_version_record(data_dir, assessment_id, artifact_version)
    return sorted(version.get("responses", []), key=lambda item: item["response_order"])


def question_progress(
    store: StudyStore,
    data_dir: str,
    participant_id: str,
    assessment_id: str,
    artifact_version: str,
) -> dict[str, Any]:
    responses = _responses_for_version(data_dir, assessment_id, artifact_version)
    trials = store.list_trials_for_question(participant_id, assessment_id)
    trials_by_response = {trial["response_id"]: trial for trial in trials}
    response_items: list[dict[str, Any]] = []
    completed = 0
    for item in responses:
        trial = trials_by_response.get(item["response_id"])
        if trial and (trial.get("submitted_at") or trial.get("status") == "submitted"):
            status = "submitted"
            completed += 1
        elif trial and trial.get("status") == "open":
            status = "in_progress"
        else:
            status = "pending"
        response_items.append(
            {
                "candidate_id": item["candidate_id"],
                "candidate_label": f"Candidate {item['candidate_id']}",
                "response_order": item["response_order"],
                "status": status,
            }
        )

    total = len(responses)
    return {
        "assessment_id": assessment_id,
        "artifact_version": artifact_version,
        "total_responses": total,
        "completed_responses": completed,
        "complete": total > 0 and completed >= total,
        "has_open_trial": any(trial["status"] == "open" for trial in trials),
        "responses": response_items,
    }


def next_or_resume_trial(
    store: StudyStore,
    judgement_store: JudgementStore,
    data_dir: str,
    participant_id: str,
    assessment_id: str,
    artifact_version: str,
) -> dict[str, Any]:
    open_trial = store.get_open_trial(participant_id, assessment_id)
    if open_trial is not None:
        return {"trial": open_trial, "created": False}

    responses = _responses_for_version(data_dir, assessment_id, artifact_version)
    trials = store.list_trials_for_question(participant_id, assessment_id)
    started_ids = {trial["response_id"] for trial in trials}
    submitted_ids = {trial["response_id"] for trial in trials if trial.get("submitted_at")}

    next_response = None
    for item in responses:
        if item["response_id"] not in submitted_ids:
            next_response = item
            break

    if next_response is None:
        raise ValueError("Question complete")

    if next_response["response_id"] in started_ids:
        for trial in trials:
            if trial["response_id"] == next_response["response_id"] and trial["status"] == "open":
                return {"trial": trial, "created": False}

    marking_session = judgement_store.create_session(participant_id, label="study-trial")
    trial = store.create_trial(
        participant_id=participant_id,
        assessment_id=assessment_id,
        artifact_version=artifact_version,
        response_id=next_response["response_id"],
        candidate_id=next_response["candidate_id"],
        response_order=next_response["response_order"],
        marking_session_id=marking_session["marking_session_id"],
    )
    return {"trial": trial, "created": True}


def submit_trial_mark(
    store: StudyStore,
    data_dir: str,
    participant_id: str,
    trial_id: str,
    final_mark: int,
) -> dict[str, Any]:
    trial = store.get_trial(trial_id)
    if trial is None:
        raise KeyError(trial_id)
    if trial["participant_id"] != participant_id:
        raise PermissionError("Trial does not belong to participant")

    maximum_mark = _maximum_mark(data_dir, trial["assessment_id"], trial["artifact_version"])
    if final_mark < 0 or final_mark > maximum_mark:
        raise ValueError(f"Mark must be between 0 and {maximum_mark}")

    store.submit_trial(trial_id, final_mark)

    responses = _responses_for_version(data_dir, trial["assessment_id"], trial["artifact_version"])
    trials = store.list_trials_for_question(participant_id, trial["assessment_id"])
    submitted_ids = {item["response_id"] for item in trials if item.get("submitted_at") or item["status"] == "submitted"}

    remaining = [item for item in responses if item["response_id"] not in submitted_ids]
    if remaining:
        return {
            "destination": "next_trial",
            "assessment_id": trial["assessment_id"],
            "artifact_version": trial["artifact_version"],
            "question_complete": False,
        }

    return {
        "destination": "question_selection",
        "assessment_id": trial["assessment_id"],
        "question_complete": True,
    }
