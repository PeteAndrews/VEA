"""Discover assessments and build question assignments for a subject."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.assessment_paths import source_jev_verification_path, source_relationships_path
from app.assessment_registry import AssessmentRegistry
from app.views import list_assessment_ids, load_stage1


def _is_complete_assessment(data_dir: str | Path, assessment_id: str) -> bool:
    data_dir = Path(data_dir)
    return (
        source_relationships_path(data_dir, assessment_id).is_file()
        and source_jev_verification_path(data_dir, assessment_id).is_file()
    )


def list_assessments_for_subject(
    data_dir: str | Path,
    subject: str,
    *,
    assessment_order: list[str] | None = None,
) -> list[str]:
    data_dir = Path(data_dir)
    subject_key = subject.strip().lower()
    discovered: list[tuple[str, str]] = []

    for assessment_id in list_assessment_ids(data_dir):
        if not _is_complete_assessment(data_dir, assessment_id):
            continue
        stage1 = load_stage1(data_dir, assessment_id)
        metadata = stage1.get("metadata") or {}
        item_subject = str(metadata.get("subject") or "").strip().lower()
        if item_subject != subject_key:
            continue
        question_id = str(stage1.get("question_id") or assessment_id)
        discovered.append((question_id, assessment_id))

    if assessment_order:
        order_index = {assessment_id: index for index, assessment_id in enumerate(assessment_order)}
        filtered = [assessment_id for _, assessment_id in discovered if assessment_id in order_index]
        filtered.sort(key=lambda assessment_id: order_index[assessment_id])
        missing = [assessment_id for assessment_id in assessment_order if assessment_id not in filtered]
        if missing:
            raise ValueError(f"Configured assessments not available for subject {subject}: {missing}")
        return filtered

    discovered.sort(key=lambda item: item[0])
    return [assessment_id for _, assessment_id in discovered]


def build_question_assignments(
    data_dir: str | Path,
    subject: str,
    *,
    assessment_order: list[str] | None = None,
) -> list[dict[str, Any]]:
    registry = AssessmentRegistry(data_dir).load()
    registry_store = AssessmentRegistry(data_dir)
    assessment_ids = list_assessments_for_subject(
        data_dir,
        subject,
        assessment_order=assessment_order,
    )
    if not assessment_ids:
        raise ValueError(f"No assessments found for subject: {subject}")

    questions: list[dict[str, Any]] = []
    for order, assessment_id in enumerate(assessment_ids, start=1):
        version = registry_store.latest_ready(registry, assessment_id)
        if version is None:
            stage1 = load_stage1(data_dir, assessment_id)
            metadata = stage1.get("metadata") or {}
            if str(metadata.get("subject") or "").strip().lower() != subject.strip().lower():
                raise ValueError(f"Assessment {assessment_id} subject mismatch")
            questions.append(
                {
                    "assessment_id": assessment_id,
                    "artifact_version": "legacy",
                    "question_order": order,
                }
            )
            continue
        metadata = version.get("metadata") or {}
        if str(metadata.get("subject") or "").strip().lower() != subject.strip().lower():
            raise ValueError(f"Assessment {assessment_id} subject mismatch")
        questions.append(
            {
                "assessment_id": assessment_id,
                "artifact_version": version["artifact_version"],
                "question_order": order,
            }
        )
    return questions
