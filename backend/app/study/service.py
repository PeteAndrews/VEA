"""Study session and assignment orchestration."""

from __future__ import annotations

from typing import Any

from app.assessment_runtime import get_version_record
from app.judgement import JudgementStore
from app.study.assignments import build_question_assignments
from app.study.config import (
    experience_for_condition,
    find_participant_by_token,
    load_participants_config,
    load_study_config,
    subject_assessment_order,
)
from app.study.store import StudyStore, hash_token
from app.study.trials import next_or_resume_trial, question_progress, submit_trial_mark


class StudyService:
    def __init__(
        self,
        store: StudyStore,
        judgement_store: JudgementStore,
        data_dir: str = "data",
        project_root: str | None = None,
    ) -> None:
        self.store = store
        self.judgement_store = judgement_store
        self.data_dir = data_dir
        self.project_root = project_root

    def authenticate_token(self, token: str) -> dict[str, Any]:
        participant = self._resolve_participant_for_token(token)
        session = self.store.create_study_session(participant["participant_id"])
        return {
            "session_id": session["session_id"],
            "participant": self._public_participant(participant),
            "walkthrough": self.walkthrough_status(participant),
        }

    def restore_session(self, session_id: str) -> dict[str, Any]:
        session = self.store.touch_study_session(session_id)
        if session is None:
            raise KeyError(session_id)
        participant = self.store.get_participant(session["participant_id"])
        if participant is None:
            raise KeyError(session["participant_id"])
        return {
            "session_id": session_id,
            "participant": self._public_participant(participant),
            "walkthrough": self.walkthrough_status(participant),
        }

    def list_questions(self, participant_id: str) -> dict[str, Any]:
        participant = self.store.get_participant(participant_id)
        if participant is None:
            raise KeyError(participant_id)
        questions = self.store.list_participant_questions(participant_id)
        items: list[dict[str, Any]] = []
        all_complete = True
        for question in questions:
            metadata = self._question_metadata(question["assessment_id"], question["artifact_version"])
            progress = question_progress(
                self.store,
                self.data_dir,
                participant_id,
                question["assessment_id"],
                question["artifact_version"],
                self._excluded_response_ids(participant),
            )
            all_complete = all_complete and progress["complete"]
            items.append(
                {
                    "assessment_id": question["assessment_id"],
                    "artifact_version": question["artifact_version"],
                    "question_order": question["question_order"],
                    "question_label": metadata.get("question_label"),
                    "subject": metadata.get("subject"),
                    "maximum_mark": metadata.get("maximum_mark"),
                    "progress": progress,
                    "responses": progress.get("responses", []),
                }
            )
        return {
            "subject": participant["subject"],
            "condition": participant["condition"],
            "experience": participant["experience"],
            "questions": items,
            "study_complete": bool(items) and all_complete,
        }

    def start_question(self, participant_id: str, assessment_id: str) -> dict[str, Any]:
        participant = self.store.get_participant(participant_id)
        if participant is None:
            raise KeyError(participant_id)
        assigned = {
            item["assessment_id"]: item
            for item in self.store.list_participant_questions(participant_id)
        }
        if assessment_id not in assigned:
            raise PermissionError("Question not assigned")
        question = assigned[assessment_id]
        self._require_walkthrough_for_vea(participant)
        result = next_or_resume_trial(
            self.store,
            self.judgement_store,
            self.data_dir,
            participant_id,
            assessment_id,
            question["artifact_version"],
            self._excluded_response_ids(participant),
        )
        trial = result["trial"]
        return self._trial_destination(participant, trial)

    def get_trial(self, participant_id: str, trial_id: str) -> dict[str, Any]:
        participant = self.store.get_participant(participant_id)
        if participant is None:
            raise KeyError(participant_id)
        trial = self.store.get_trial(trial_id)
        if trial is None or trial["participant_id"] != participant_id:
            raise KeyError(trial_id)
        metadata = self._question_metadata(trial["assessment_id"], trial["artifact_version"])
        submission = self.store.get_submission(trial_id)
        return {
            **self._trial_destination(participant, trial),
            "maximum_mark": metadata["maximum_mark"],
            "submitted": submission is not None,
            "final_mark": submission["final_mark"] if submission else None,
        }

    def submit_final_mark(self, participant_id: str, trial_id: str, final_mark: int) -> dict[str, Any]:
        participant = self.store.get_participant(participant_id)
        if participant is None:
            raise KeyError(participant_id)
        outcome = submit_trial_mark(
            self.store,
            self.data_dir,
            participant_id,
            trial_id,
            final_mark,
            self._excluded_response_ids(participant),
        )
        questions = self.list_questions(participant_id)
        response = {
            "final_mark": final_mark,
            "destination": outcome["destination"],
            "question_complete": outcome["question_complete"],
            "study_complete": questions["study_complete"],
        }
        if outcome["destination"] == "next_trial":
            next_result = next_or_resume_trial(
                self.store,
                self.judgement_store,
                self.data_dir,
                participant_id,
                outcome["assessment_id"],
                outcome["artifact_version"],
                self._excluded_response_ids(participant),
            )
            response["next_trial"] = self._trial_destination(participant, next_result["trial"])
        return response

    def _resolve_participant_for_token(self, token: str) -> dict[str, Any]:
        cleaned = token.strip()
        if not cleaned:
            raise ValueError("Invalid study token")
        digest = hash_token(cleaned)
        participant = self.store.get_participant_by_token_digest(digest)
        if participant is not None:
            return participant

        match = find_participant_by_token(cleaned, self.project_root)
        if match is None:
            raise ValueError("Invalid study token")

        study_id, entry = match
        for field in ("participant_id", "condition", "subject"):
            if not entry.get(field):
                raise ValueError(f"Invalid participant entry: missing {field}")

        self.provision_participant(
            study_id=study_id,
            participant_id=str(entry["participant_id"]),
            token=cleaned,
            condition=str(entry["condition"]),
            subject=str(entry["subject"]),
        )
        participant = self.store.get_participant_by_token_digest(digest)
        if participant is None:
            raise ValueError("Invalid study token")
        return participant

    def provision_participant(
        self,
        *,
        study_id: str,
        participant_id: str,
        token: str,
        condition: str,
        subject: str,
        assessment_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        study_config = load_study_config(study_id, self.project_root)
        experience = experience_for_condition(condition, study_config)
        order = assessment_ids or subject_assessment_order(study_config, subject)
        questions = build_question_assignments(
            self.data_dir,
            subject,
            assessment_order=order,
        )

        self.store.upsert_participant(
            participant_id=participant_id,
            study_id=study_id,
            token_digest=hash_token(token),
            condition=condition,
            subject=subject,
            experience=experience,
        )
        self.store.replace_participant_questions(participant_id, questions)
        return {
            "participant_id": participant_id,
            "study_id": study_id,
            "condition": condition,
            "subject": subject,
            "experience": experience,
            "questions": questions,
        }

    def import_participants_file(self, study_id: str) -> dict[str, Any]:
        payload = load_participants_config(study_id, self.project_root)
        results: list[dict[str, Any]] = []
        for entry in payload.get("participants", []):
            participant_id = entry.get("participant_id")
            token = entry.get("token")
            condition = entry.get("condition")
            subject = entry.get("subject")
            if not all([participant_id, token, condition, subject]):
                raise ValueError(f"Invalid participant entry: {entry}")
            result = self.provision_participant(
                study_id=study_id,
                participant_id=str(participant_id),
                token=str(token),
                condition=str(condition),
                subject=str(subject),
            )
            results.append(
                {
                    "participant_id": result["participant_id"],
                    "subject": result["subject"],
                    "condition": result["condition"],
                    "question_count": len(result["questions"]),
                }
            )
        return {"study_id": study_id, "imported": len(results), "participants": results}

    def _question_metadata(self, assessment_id: str, artifact_version: str) -> dict[str, Any]:
        if artifact_version == "legacy":
            from app.views import load_stage1, question_label_from_id

            stage1 = load_stage1(self.data_dir, assessment_id)
            metadata = dict(stage1.get("metadata") or {})
            metadata.setdefault("question_label", question_label_from_id(stage1.get("question_id", "")))
            return metadata
        version = get_version_record(self.data_dir, assessment_id, artifact_version)
        return version.get("metadata") or {}

    def walkthrough_status(self, participant: dict[str, Any]) -> dict[str, bool]:
        config = self._walkthrough_config(participant)
        entry = self._participant_config_entry(participant)
        flagged = bool(entry and entry.get("walkthrough_required"))
        required = (
            participant.get("experience") == "vea_marking"
            and flagged
            and config is not None
        )
        completed = self.store.get_walkthrough_completion(participant["participant_id"]) is not None
        return {"required": required, "completed": completed}

    def start_walkthrough(self, participant_id: str) -> dict[str, Any]:
        participant = self.store.get_participant(participant_id)
        if participant is None:
            raise KeyError(participant_id)
        config = self._walkthrough_config(participant)
        if participant.get("experience") != "vea_marking" or config is None:
            raise PermissionError("Walkthrough is not available for this participant")
        session = self.judgement_store.create_session(participant_id, label="walkthrough")
        artifact_version = self._artifact_version(participant_id, config["assessment_id"])
        metadata = self._question_metadata(config["assessment_id"], artifact_version)
        return {
            "marking_session_id": session["marking_session_id"],
            "assessment_id": config["assessment_id"],
            "candidate_id": config["candidate_id"],
            "maximum_mark": metadata.get("maximum_mark"),
        }

    def complete_walkthrough(
        self,
        participant_id: str,
        marking_session_id: str,
        final_mark: int,
    ) -> dict[str, Any]:
        participant = self.store.get_participant(participant_id)
        if participant is None:
            raise KeyError(participant_id)
        config = self._walkthrough_config(participant)
        if config is None:
            raise PermissionError("Walkthrough is not available for this participant")
        try:
            session = self.judgement_store.get_session(marking_session_id)
        except KeyError:
            raise PermissionError("Walkthrough session not found") from None
        if session.get("examiner_id") != participant_id or session.get("label") != "walkthrough":
            raise PermissionError("Walkthrough session does not belong to this participant")
        artifact_version = self._artifact_version(participant_id, config["assessment_id"])
        maximum_mark = int(self._question_metadata(config["assessment_id"], artifact_version)["maximum_mark"])
        if final_mark < 0 or final_mark > maximum_mark:
            raise ValueError(f"Mark must be between 0 and {maximum_mark}")
        completion = self.store.record_walkthrough_completion(
            participant_id,
            marking_session_id,
            final_mark,
        )
        return {
            "completed": True,
            "final_mark": completion["final_mark"],
            "marking_session_id": completion["marking_session_id"],
        }

    def _require_walkthrough_for_vea(self, participant: dict[str, Any]) -> None:
        if participant.get("experience") != "vea_marking":
            return
        status = self.walkthrough_status(participant)
        if status["required"] and not status["completed"]:
            raise ValueError("Walkthrough required")

    def _walkthrough_config(self, participant: dict[str, Any]) -> dict[str, Any] | None:
        study = load_study_config(participant["study_id"], self.project_root)
        subjects = study.get("subjects") or {}
        entry = subjects.get(participant["subject"]) or subjects.get(str(participant["subject"]).strip().lower())
        walkthrough = (entry or {}).get("walkthrough") or {}
        assessment_id = walkthrough.get("assessment_id")
        response_id = walkthrough.get("response_id")
        candidate_id = walkthrough.get("candidate_id")
        if not assessment_id or not response_id or not candidate_id:
            return None
        return {
            "assessment_id": str(assessment_id),
            "response_id": str(response_id),
            "candidate_id": str(candidate_id),
        }

    def _excluded_response_ids(self, participant: dict[str, Any]) -> set[str]:
        config = self._walkthrough_config(participant)
        if config is None:
            return set()
        return {config["response_id"]}

    def _participant_config_entry(self, participant: dict[str, Any]) -> dict[str, Any] | None:
        try:
            payload = load_participants_config(participant["study_id"], self.project_root)
        except FileNotFoundError:
            return None
        for entry in payload.get("participants", []):
            if str(entry.get("participant_id")) == participant["participant_id"]:
                return entry
        return None

    def _artifact_version(self, participant_id: str, assessment_id: str) -> str:
        for question in self.store.list_participant_questions(participant_id):
            if question["assessment_id"] == assessment_id:
                return question["artifact_version"]
        return "legacy"

    def _public_participant(self, participant: dict[str, Any]) -> dict[str, Any]:
        return {
            "participant_id": participant["participant_id"],
            "study_id": participant["study_id"],
            "condition": participant["condition"],
            "subject": participant["subject"],
            "experience": participant["experience"],
        }

    def _trial_destination(self, participant: dict[str, Any], trial: dict[str, Any]) -> dict[str, Any]:
        experience = participant["experience"]
        route = "/study/trials/{trial_id}/mark" if experience == "vea_marking" else "/study/trials/{trial_id}/control"
        return {
            "trial_id": trial["trial_id"],
            "assessment_id": trial["assessment_id"],
            "artifact_version": trial["artifact_version"],
            "candidate_id": trial["candidate_id"],
            "marking_session_id": trial["marking_session_id"],
            "experience": experience,
            "route": route.format(trial_id=trial["trial_id"]),
            "status": trial["status"],
        }
