"""Study session and assignment orchestration."""

from __future__ import annotations

from typing import Any

from app.assessment_runtime import get_version_record
from app.judgement import JudgementStore
from app.marking_materials import load_baseline_materials
from app.study.assignments import build_assignments_for_condition_lists, build_question_assignments
from app.study.config import (
    experience_for_condition,
    find_participant_by_token,
    load_participants_config,
    load_study_config,
    subject_assessment_order,
)
from app.study.instruments import (
    FORM_VERSION,
    POST_CONDITION_KEYS,
    background_definition,
    nasa_tlx_definition,
    preference_definition,
    score_answers,
    sus_definition,
    ueq_definition,
    validate_answers,
)
from app.study.practice import practice_condition_config, practice_config_for_subject
from app.study.store import StudyStore, hash_token
from app.study.trials import next_or_resume_trial, question_progress, submit_trial_mark

WALKTHROUGH_CONDITION_VEA = "vea"
WALKTHROUGH_CONDITION_BASELINE = "baseline"


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
        self._refresh_assignments_from_config(participant)
        participant = self.store.get_participant(participant["participant_id"]) or participant
        session = self.store.create_study_session(participant["participant_id"])
        self._ensure_interface_labels(participant)
        return {
            "session_id": session["session_id"],
            "participant": self._public_participant(participant),
            "walkthrough": self.walkthrough_status(participant),
            "progress": self.study_progress(participant),
        }

    def restore_session(self, session_id: str) -> dict[str, Any]:
        session = self.store.touch_study_session(session_id)
        if session is None:
            raise KeyError(session_id)
        participant = self.store.get_participant(session["participant_id"])
        if participant is None:
            raise KeyError(session["participant_id"])
        self._refresh_assignments_from_config(participant)
        self._ensure_interface_labels(participant)
        return {
            "session_id": session_id,
            "participant": self._public_participant(participant),
            "walkthrough": self.walkthrough_status(participant),
            "progress": self.study_progress(participant),
        }

    def list_questions(self, participant_id: str) -> dict[str, Any]:
        participant = self.store.get_participant(participant_id)
        if participant is None:
            raise KeyError(participant_id)
        self._refresh_assignments_from_config(participant)
        entry = self._participant_config_entry(participant)
        questions = self._experimental_questions(
            participant, self.store.list_participant_questions(participant_id)
        )
        condition_order = (entry or {}).get("condition_order")
        if condition_order and len(condition_order) >= 2:
            return self._list_questions_within(participant, questions, condition_order, entry)
        return self._list_questions_single(participant, questions)

    def _question_list_item(
        self,
        participant_id: str,
        participant: dict[str, Any],
        question: dict[str, Any],
    ) -> dict[str, Any]:
        metadata = self._question_metadata(question["assessment_id"], question["artifact_version"])
        progress = question_progress(
            self.store,
            self.data_dir,
            participant_id,
            question["assessment_id"],
            question["artifact_version"],
            self._excluded_response_ids(participant),
        )
        return {
            "assessment_id": question["assessment_id"],
            "artifact_version": question["artifact_version"],
            "question_order": question["question_order"],
            "condition": question.get("condition", "vea"),
            "question_label": metadata.get("question_label"),
            "subject": metadata.get("subject"),
            "maximum_mark": metadata.get("maximum_mark"),
            "progress": progress,
            "responses": progress.get("responses", []),
        }

    def _list_questions_single(
        self,
        participant: dict[str, Any],
        questions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        all_complete = True
        for question in questions:
            item = self._question_list_item(participant["participant_id"], participant, question)
            all_complete = all_complete and item["progress"]["complete"]
            items.append(item)
        missing = not items and self._practice_assessment_id(participant) is not None
        payload: dict[str, Any] = {
            "subject": participant["subject"],
            "condition": participant["condition"],
            "experience": participant["experience"],
            "layout": "single",
            "questions": items,
            "study_complete": bool(items) and all_complete,
            "missing_experimental_config": missing,
        }
        vea_tour = self.walkthrough_status(participant, WALKTHROUGH_CONDITION_VEA)
        if vea_tour["required"]:
            payload["walkthrough"] = vea_tour
        baseline_tour = self.walkthrough_status(participant, WALKTHROUGH_CONDITION_BASELINE)
        if baseline_tour["required"]:
            payload["baseline_walkthrough"] = baseline_tour
        progress = self.study_progress(participant)
        payload["progress"] = progress
        payload["study_complete"] = progress["study_complete"]
        return payload

    def _list_questions_within(
        self,
        participant: dict[str, Any],
        questions: list[dict[str, Any]],
        condition_order: list[str],
        entry: dict[str, Any] | None,
    ) -> dict[str, Any]:
        grouped: dict[str, list[dict[str, Any]]] = {key: [] for key in condition_order}
        for question in questions:
            cond = question.get("condition") or condition_order[0]
            if cond not in grouped:
                grouped[cond] = []
            grouped[cond].append(self._question_list_item(participant["participant_id"], participant, question))

        locks = self._condition_locks(participant["participant_id"], condition_order, grouped)
        conditions: list[dict[str, Any]] = []
        all_complete = True
        for cond in condition_order:
            items = grouped.get(cond, [])
            marking_done = bool(items) and all(item["progress"]["complete"] for item in items)
            complete = marking_done and self._questionnaires_complete(participant, cond)
            all_complete = all_complete and complete
            label = "VEA marking" if cond == "vea" else "Baseline marking"
            unlocked = not locks.get(cond, False)
            block: dict[str, Any] = {
                "condition": cond,
                "label": label,
                "locked": locks.get(cond, False),
                "complete": complete,
                "questions": items,
                "missing_experimental_config": not items,
            }
            if cond == WALKTHROUGH_CONDITION_VEA:
                block["walkthrough"] = self.walkthrough_status(
                    participant, WALKTHROUGH_CONDITION_VEA, condition_unlocked=unlocked
                )
            elif cond == WALKTHROUGH_CONDITION_BASELINE:
                block["baseline_walkthrough"] = self.walkthrough_status(
                    participant, WALKTHROUGH_CONDITION_BASELINE, condition_unlocked=unlocked
                )
            conditions.append(block)

        missing_any = any(block["missing_experimental_config"] for block in conditions)
        progress = self.study_progress(participant)
        return {
            "subject": participant["subject"],
            "condition": participant["condition"],
            "experience": participant["experience"],
            "layout": "within",
            "condition_order": list(condition_order),
            "conditions": conditions,
            "questions": [item for block in conditions for item in block["questions"]],
            "study_complete": progress["study_complete"],
            "missing_experimental_config": missing_any,
            "progress": progress,
        }

    def _condition_locks(
        self,
        participant_id: str,
        condition_order: list[str],
        grouped: dict[str, list[dict[str, Any]]],
    ) -> dict[str, bool]:
        if len(condition_order) < 2:
            return {cond: False for cond in condition_order}
        first, second = condition_order[0], condition_order[1]
        first_items = grouped.get(first, [])
        participant = self.store.get_participant(participant_id)
        marking_done = bool(first_items) and all(item["progress"]["complete"] for item in first_items)
        first_complete = bool(participant) and marking_done and self._questionnaires_complete(participant, first)
        locks = {first: False, second: not first_complete}
        for cond in condition_order[2:]:
            locks[cond] = not first_complete
        return locks

    def start_question(self, participant_id: str, assessment_id: str) -> dict[str, Any]:
        participant = self.store.get_participant(participant_id)
        if participant is None:
            raise KeyError(participant_id)
        assigned = {
            item["assessment_id"]: item
            for item in self.store.list_participant_questions(participant_id)
        }
        if assessment_id not in assigned:
            practice_id = self._practice_assessment_id(participant)
            if practice_id and assessment_id == practice_id:
                raise PermissionError("This question is practice-only")
            raise PermissionError("Question not assigned")
        question = assigned[assessment_id]
        cond = question.get("condition", "vea")
        self._require_background(participant)
        self._require_condition_unlocked(participant, cond)
        self._require_walkthrough_for_condition(participant, cond)
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
        return self._trial_destination(participant, trial, question.get("condition"))

    def get_trial(self, participant_id: str, trial_id: str) -> dict[str, Any]:
        participant = self.store.get_participant(participant_id)
        if participant is None:
            raise KeyError(participant_id)
        trial = self.store.get_trial(trial_id)
        if trial is None or trial["participant_id"] != participant_id:
            raise KeyError(trial_id)
        question_condition = self._condition_for_assessment(participant_id, trial["assessment_id"])
        self._require_background(participant)
        self._require_condition_unlocked(participant, question_condition)
        metadata = self._question_metadata(trial["assessment_id"], trial["artifact_version"])
        submission = self.store.get_submission(trial_id)
        payload: dict[str, Any] = {
            **self._trial_destination(participant, trial, question_condition),
            "maximum_mark": metadata["maximum_mark"],
            "submitted": submission is not None,
            "final_mark": submission["final_mark"] if submission else None,
        }
        experience = self._experience_for_condition(question_condition, participant)
        if experience == "control_placeholder":
            from app.views import candidate_detail_view

            try:
                payload["baseline_materials"] = load_baseline_materials(
                    self.data_dir,
                    trial["assessment_id"],
                )
            except FileNotFoundError as exc:
                raise ValueError(str(exc)) from exc
            payload["response"] = candidate_detail_view(
                self.data_dir,
                trial["assessment_id"],
                trial["candidate_id"],
            )
        return payload

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
        progress = questions.get("progress") or self.study_progress(participant)
        destination = outcome["destination"]
        response = {
            "final_mark": final_mark,
            "destination": destination,
            "question_complete": outcome["question_complete"],
            "study_complete": progress["study_complete"],
            "progress": progress,
        }
        nxt = progress.get("next") or {}
        if destination != "next_trial" and nxt.get("stage") == "questionnaire":
            response["destination"] = "questionnaire"
            response["route"] = nxt["route"]
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
            next_condition = self._condition_for_assessment(
                participant_id, next_result["trial"]["assessment_id"]
            )
            response["next_trial"] = self._trial_destination(
                participant, next_result["trial"], next_condition
            )
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
        for field in ("participant_id", "subject"):
            if not entry.get(field):
                raise ValueError(f"Invalid participant entry: missing {field}")
        if not entry.get("condition") and not entry.get("condition_order"):
            raise ValueError("Invalid participant entry: missing condition or condition_order")

        self._provision_from_entry(study_id, entry, cleaned)
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
        walkthrough_required: bool = False,
    ) -> dict[str, Any]:
        study_config = load_study_config(study_id, self.project_root)
        experience = experience_for_condition(condition, study_config)
        order = assessment_ids or subject_assessment_order(study_config, subject)
        order = self._filter_practice_ids(study_id, subject, list(order or []), walkthrough_required)
        questions = (
            build_question_assignments(
                self.data_dir,
                subject,
                assessment_order=order,
            )
            if order
            else []
        )
        for item in questions:
            item.setdefault("condition", condition if condition in ("vea", "control", "baseline") else "vea")

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

    def _assignments_from_entry(self, study_id: str, entry: dict[str, Any]) -> list[dict[str, Any]] | None:
        subject = str(entry["subject"])
        condition_order = entry.get("condition_order")
        questions_map = entry.get("questions")
        if not (condition_order and questions_map is not None):
            return None
        flagged = bool(entry.get("walkthrough_required"))
        return build_assignments_for_condition_lists(
            self.data_dir,
            subject,
            condition_order=[str(item) for item in condition_order],
            questions_by_condition={
                str(key): self._filter_practice_ids(
                    study_id,
                    subject,
                    [str(aid) for aid in (value or [])],
                    flagged,
                )
                for key, value in questions_map.items()
            },
        )

    def _refresh_assignments_from_config(self, participant: dict[str, Any]) -> None:
        entry = self._participant_config_entry(participant)
        if not entry:
            return
        questions = self._assignments_from_entry(participant["study_id"], entry)
        if questions is not None:
            self.store.replace_participant_questions(participant["participant_id"], questions)

    def _provision_from_entry(self, study_id: str, entry: dict[str, Any], token: str) -> dict[str, Any]:
        participant_id = str(entry["participant_id"])
        subject = str(entry["subject"])
        condition_order = entry.get("condition_order")
        questions_map = entry.get("questions")
        if condition_order and questions_map is not None:
            questions = self._assignments_from_entry(study_id, entry) or []
            self.store.upsert_participant(
                participant_id=participant_id,
                study_id=study_id,
                token_digest=hash_token(token),
                condition="within",
                subject=subject,
                experience="within_subjects",
            )
            self.store.replace_participant_questions(participant_id, questions)
            return {
                "participant_id": participant_id,
                "study_id": study_id,
                "condition": "within",
                "subject": subject,
                "experience": "within_subjects",
                "questions": questions,
            }
        condition = str(entry["condition"])
        return self.provision_participant(
            study_id=study_id,
            participant_id=participant_id,
            token=token,
            condition=condition,
            subject=subject,
            walkthrough_required=bool(entry.get("walkthrough_required")),
        )

    def import_participants_file(self, study_id: str) -> dict[str, Any]:
        payload = load_participants_config(study_id, self.project_root)
        results: list[dict[str, Any]] = []
        for entry in payload.get("participants", []):
            participant_id = entry.get("participant_id")
            token = entry.get("token")
            condition = entry.get("condition")
            subject = entry.get("subject")
            if not all([participant_id, token, subject]):
                raise ValueError(f"Invalid participant entry: {entry}")
            if not condition and not entry.get("condition_order"):
                raise ValueError(f"Invalid participant entry: {entry}")
            result = self._provision_from_entry(study_id, entry, str(token))
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

    def study_progress(self, participant: dict[str, Any]) -> dict[str, Any]:
        order = self._condition_order(participant)
        labels = self.store.get_interface_labels(participant["participant_id"]) or {}
        background = self._questionnaire_is_submitted(participant, "background", "study")
        condition_rows: list[dict[str, Any]] = []
        next_step: dict[str, Any] | None = None
        if not background:
            next_step = self._questionnaire_destination("background", "study")
        for cond in order:
            marking_done = self._marking_complete(participant, cond)
            submitted = {
                key: self._questionnaire_is_submitted(participant, key, cond) for key in POST_CONDITION_KEYS
            }
            questionnaires_done = all(submitted.values())
            complete = marking_done and questionnaires_done
            condition_rows.append(
                {
                    "condition": cond,
                    "marking_complete": marking_done,
                    "questionnaires": submitted,
                    "questionnaires_complete": questionnaires_done,
                    "complete": complete,
                }
            )
            if background and next_step is None and not complete:
                if not marking_done:
                    next_step = {"stage": "marking", "condition": cond, "route": "/questions"}
                else:
                    for key in POST_CONDITION_KEYS:
                        if not submitted[key]:
                            next_step = self._questionnaire_destination(key, cond)
                            break
        all_conditions_complete = bool(order) and all(row["complete"] for row in condition_rows)
        preference_done = self._questionnaire_is_submitted(participant, "preference", "study")
        if next_step is None and len(order) >= 2 and all_conditions_complete and not preference_done:
            next_step = self._questionnaire_destination("preference", "study")
        if next_step is None:
            next_step = {"stage": "done", "route": "/questions"}
        return {
            "background_complete": background,
            "conditions": condition_rows,
            "preference_complete": preference_done,
            "study_complete": all_conditions_complete and (len(order) < 2 or preference_done),
            "next": next_step,
            "interface_labels": labels,
        }

    def get_questionnaire(self, participant_id: str, key: str, scope: str) -> dict[str, Any]:
        participant = self._participant_or_raise(participant_id)
        self._require_questionnaire_open(participant, key, scope)
        form = self._form_definition(participant, key, scope)
        saved = self.store.get_questionnaire_response(participant_id, key, scope)
        return {
            "form": form,
            "answers": (saved or {}).get("answers") or {},
            "status": (saved or {}).get("status") or "new",
            "updated_at": (saved or {}).get("updated_at"),
            "scope": scope,
        }

    def save_questionnaire_draft(
        self,
        participant_id: str,
        key: str,
        scope: str,
        answers: dict[str, Any],
        expected_updated_at: str | None,
    ) -> dict[str, Any]:
        participant = self._participant_or_raise(participant_id)
        self._require_questionnaire_open(participant, key, scope)
        form = self._form_definition(participant, key, scope)
        errors = validate_answers(form, answers, complete=False)
        if errors:
            raise ValueError("; ".join(errors))
        saved = self.store.save_questionnaire_response(
            participant_id=participant_id,
            questionnaire_key=key,
            scope=scope,
            version=FORM_VERSION,
            answers=answers,
            context=self._questionnaire_context(participant),
            status="draft",
            expected_updated_at=expected_updated_at,
        )
        return {"status": saved.get("status"), "updated_at": saved.get("updated_at"), "answers": saved.get("answers")}

    def submit_questionnaire(
        self,
        participant_id: str,
        key: str,
        scope: str,
        answers: dict[str, Any],
        expected_updated_at: str | None,
    ) -> dict[str, Any]:
        participant = self._participant_or_raise(participant_id)
        saved = self.store.get_questionnaire_response(participant_id, key, scope)
        if not (saved and saved.get("status") == "submitted"):
            self._require_questionnaire_open(participant, key, scope)
        form = self._form_definition(participant, key, scope)
        errors = validate_answers(form, answers, complete=True)
        if errors:
            raise ValueError("; ".join(errors))
        saved = self.store.save_questionnaire_response(
            participant_id=participant_id,
            questionnaire_key=key,
            scope=scope,
            version=FORM_VERSION,
            answers=answers,
            context=self._questionnaire_context(participant),
            status="submitted",
            expected_updated_at=expected_updated_at if not (saved and saved.get("status") == "submitted") else saved.get("updated_at"),
        )
        progress = self.study_progress(participant)
        return {"submitted": True, "progress": progress}

    def assert_trial_marking_open(self, marking_session_id: str) -> None:
        trial = self.store.get_trial_by_marking_session(marking_session_id)
        if trial is None:
            return
        participant = self.store.get_participant(trial["participant_id"])
        if participant is None:
            return
        if trial.get("status") == "submitted":
            raise PermissionError("Marking is closed for this response")
        condition = self._condition_for_assessment(participant["participant_id"], trial["assessment_id"])
        self._require_background(participant)
        self._require_condition_unlocked(participant, condition)

    def export_questionnaire_rows(self, *, submitted_only: bool = True) -> list[dict[str, Any]]:
        rows = []
        for item in self.store.list_questionnaire_responses(submitted_only=submitted_only):
            participant = self.store.get_participant(item["participant_id"]) or {}
            labels = {}
            if participant:
                labels = self.store.get_interface_labels(participant["participant_id"]) or {}
            score = None
            if item["status"] == "submitted":
                score = score_answers(item["questionnaire_key"], item["answers"])
            rows.append(
                {
                    "participant_id": item["participant_id"],
                    "subject": participant.get("subject"),
                    "questionnaire_key": item["questionnaire_key"],
                    "scope": item["scope"],
                    "version": item["version"],
                    "status": item["status"],
                    "interface_labels": labels,
                    "answers": item["answers"],
                    "score": score,
                    "started_at": item["started_at"],
                    "updated_at": item["updated_at"],
                    "submitted_at": item["submitted_at"],
                }
            )
        return rows

    def _participant_or_raise(self, participant_id: str) -> dict[str, Any]:
        participant = self.store.get_participant(participant_id)
        if participant is None:
            raise KeyError(participant_id)
        return participant

    def _condition_order(self, participant: dict[str, Any]) -> list[str]:
        entry = self._participant_config_entry(participant) or {}
        order = entry.get("condition_order") or []
        return [str(item) for item in order]

    def _ensure_interface_labels(self, participant: dict[str, Any]) -> dict[str, str] | None:
        order = self._condition_order(participant)
        if len(order) < 2:
            return self.store.get_interface_labels(participant["participant_id"])
        return self.store.set_interface_labels_if_empty(
            participant["participant_id"],
            {"A": order[0], "B": order[1]},
        )

    def _questionnaire_is_submitted(self, participant: dict[str, Any], key: str, scope: str) -> bool:
        saved = self.store.get_questionnaire_response(participant["participant_id"], key, scope)
        return bool(saved and saved.get("status") == "submitted")

    def _questionnaires_complete(self, participant: dict[str, Any], condition: str) -> bool:
        return all(
            self._questionnaire_is_submitted(participant, key, condition) for key in POST_CONDITION_KEYS
        )

    def _marking_complete(self, participant: dict[str, Any], condition: str) -> bool:
        items = [
            question
            for question in self._experimental_questions(
                participant, self.store.list_participant_questions(participant["participant_id"])
            )
            if question.get("condition") == condition
        ]
        if not items:
            return False
        return all(
            question_progress(
                self.store,
                self.data_dir,
                participant["participant_id"],
                item["assessment_id"],
                item["artifact_version"],
                self._excluded_response_ids(participant),
            )["complete"]
            for item in items
        )

    def _require_background(self, participant: dict[str, Any]) -> None:
        if not self._questionnaire_is_submitted(participant, "background", "study"):
            raise PermissionError("Background questionnaire required")

    def _questionnaire_destination(self, key: str, scope: str) -> dict[str, str]:
        return {
            "stage": "questionnaire",
            "key": key,
            "scope": scope,
            "route": f"/study/questionnaire/{key}/{scope}",
        }

    def _require_questionnaire_open(self, participant: dict[str, Any], key: str, scope: str) -> None:
        progress = self.study_progress(participant)
        nxt = progress.get("next") or {}
        if nxt.get("stage") == "questionnaire" and nxt.get("key") == key and nxt.get("scope") == scope:
            return
        raise PermissionError("This questionnaire is not available yet")

    def _interface_letter(self, participant: dict[str, Any], condition: str) -> str:
        labels = self.store.get_interface_labels(participant["participant_id"]) or {}
        for letter, stored in labels.items():
            if stored == condition:
                return letter
        return "A"

    def _condition_name(self, condition: str) -> str:
        if condition == "vea":
            return "VEA"
        if condition == "baseline":
            return "baseline"
        return condition

    def _form_definition(self, participant: dict[str, Any], key: str, scope: str) -> dict[str, Any]:
        if key == "background" and scope == "study":
            return background_definition()
        if key == "preference" and scope == "study":
            labels = self.store.get_interface_labels(participant["participant_id"]) or {}
            return preference_definition(
                label_a=self._condition_name(labels.get("A", "")),
                label_b=self._condition_name(labels.get("B", "")),
            )
        if key == "nasa_tlx_raw" and scope in ("vea", "baseline"):
            return nasa_tlx_definition()
        if key == "sus" and scope in ("vea", "baseline"):
            return sus_definition(interface_label=self._interface_letter(participant, scope))
        if key == "ueq" and scope in ("vea", "baseline"):
            return ueq_definition(interface_label=self._interface_letter(participant, scope))
        raise PermissionError("Unknown questionnaire")

    def _questionnaire_context(self, participant: dict[str, Any]) -> dict[str, Any]:
        return {
            "interface_labels": self.store.get_interface_labels(participant["participant_id"]) or {},
            "condition_order": self._condition_order(participant),
        }

    def walkthrough_status(
        self,
        participant: dict[str, Any],
        condition: str = WALKTHROUGH_CONDITION_VEA,
        *,
        condition_unlocked: bool | None = None,
    ) -> dict[str, Any]:
        config = self._practice_for_condition(participant, condition)
        entry = self._participant_config_entry(participant)
        flagged = bool(entry and entry.get("walkthrough_required"))
        applies = self._walkthrough_applies_to_participant(participant, condition)
        required = flagged and config is not None and applies
        completed = (
            self.store.get_walkthrough_completion(participant["participant_id"], condition) is not None
        )
        if condition_unlocked is None:
            condition_unlocked = self._is_condition_unlocked(participant, condition)
        accessible = required and condition_unlocked
        return {
            "required": required,
            "completed": completed,
            "accessible": accessible,
            "condition": condition,
        }

    def start_walkthrough(self, participant_id: str) -> dict[str, Any]:
        return self._start_condition_walkthrough(participant_id, WALKTHROUGH_CONDITION_VEA)

    def complete_walkthrough(
        self,
        participant_id: str,
        marking_session_id: str,
        final_mark: int,
    ) -> dict[str, Any]:
        return self._complete_condition_walkthrough(
            participant_id,
            marking_session_id,
            final_mark,
            WALKTHROUGH_CONDITION_VEA,
            session_label="walkthrough",
            validate_level_3=True,
        )

    def start_baseline_walkthrough(self, participant_id: str) -> dict[str, Any]:
        return self._start_condition_walkthrough(participant_id, WALKTHROUGH_CONDITION_BASELINE)

    def complete_baseline_walkthrough(
        self,
        participant_id: str,
        marking_session_id: str,
        final_mark: int,
    ) -> dict[str, Any]:
        return self._complete_condition_walkthrough(
            participant_id,
            marking_session_id,
            final_mark,
            WALKTHROUGH_CONDITION_BASELINE,
            session_label="walkthrough-baseline",
            validate_level_3=False,
        )

    def _start_condition_walkthrough(self, participant_id: str, condition: str) -> dict[str, Any]:
        participant = self.store.get_participant(participant_id)
        if participant is None:
            raise KeyError(participant_id)
        self._require_background(participant)
        status = self.walkthrough_status(participant, condition)
        if not status["required"]:
            raise PermissionError("Walkthrough is not available for this participant")
        if not self._is_condition_unlocked(participant, condition):
            raise PermissionError("This condition is not yet available")
        config = self._practice_for_condition(participant, condition)
        if config is None:
            raise PermissionError("Walkthrough is not available for this participant")
        label = "walkthrough" if condition == WALKTHROUGH_CONDITION_VEA else f"walkthrough-{condition}"
        session = self.judgement_store.create_session(participant_id, label=label)
        artifact_version = self._artifact_version(participant_id, config["assessment_id"])
        metadata = self._question_metadata(config["assessment_id"], artifact_version)
        from app.views import candidate_detail_view

        payload: dict[str, Any] = {
            "marking_session_id": session["marking_session_id"],
            "assessment_id": config["assessment_id"],
            "candidate_id": config["candidate_id"],
            "maximum_mark": metadata.get("maximum_mark"),
            "condition": condition,
        }
        if condition == WALKTHROUGH_CONDITION_BASELINE:
            payload["baseline_materials"] = load_baseline_materials(
                self.data_dir, config["assessment_id"]
            )
            payload["response"] = candidate_detail_view(
                self.data_dir,
                config["assessment_id"],
                config["candidate_id"],
            )
        return payload

    def _complete_condition_walkthrough(
        self,
        participant_id: str,
        marking_session_id: str,
        final_mark: int,
        condition: str,
        *,
        session_label: str,
        validate_level_3: bool,
    ) -> dict[str, Any]:
        participant = self.store.get_participant(participant_id)
        if participant is None:
            raise KeyError(participant_id)
        config = self._practice_for_condition(participant, condition)
        if config is None:
            raise PermissionError("Walkthrough is not available for this participant")
        try:
            session = self.judgement_store.get_session(marking_session_id)
        except KeyError:
            raise PermissionError("Walkthrough session not found") from None
        allowed_labels = {session_label}
        if condition == WALKTHROUGH_CONDITION_VEA:
            allowed_labels.add("walkthrough")
        if session.get("examiner_id") != participant_id or session.get("label") not in allowed_labels:
            raise PermissionError("Walkthrough session does not belong to this participant")
        artifact_version = self._artifact_version(participant_id, config["assessment_id"])
        maximum_mark = int(self._question_metadata(config["assessment_id"], artifact_version)["maximum_mark"])
        if final_mark < 0 or final_mark > maximum_mark:
            raise ValueError(f"Mark must be between 0 and {maximum_mark}")
        if validate_level_3:
            from app.graph_service import GraphService
            from app.views import levels_view

            graph_service = GraphService.from_data_dir(
                data_dir=self.data_dir,
                assessment_id=config["assessment_id"],
            )
            levels_payload = levels_view(graph_service, self.data_dir)
            level3 = next(
                (item for item in levels_payload.get("levels", []) if item.get("level") == 3),
                None,
            )
            mark_range = level3.get("mark_range") if level3 else None
            if mark_range and (final_mark < mark_range["min"] or final_mark > mark_range["max"]):
                raise ValueError(
                    f"Choose a mark in Level 3 ({mark_range['min']}–{mark_range['max']})."
                )
        completion = self.store.record_walkthrough_completion(
            participant_id,
            marking_session_id,
            final_mark,
            condition=condition,
        )
        return {
            "completed": True,
            "final_mark": completion["final_mark"],
            "marking_session_id": completion["marking_session_id"],
            "condition": condition,
        }

    def _walkthrough_condition_key(self, condition: str) -> str:
        if condition in ("control", WALKTHROUGH_CONDITION_BASELINE):
            return WALKTHROUGH_CONDITION_BASELINE
        return condition

    def _require_walkthrough_for_condition(self, participant: dict[str, Any], question_condition: str) -> None:
        status = self.walkthrough_status(
            participant, self._walkthrough_condition_key(question_condition)
        )
        if status["required"] and not status["completed"]:
            raise ValueError("Walkthrough required")

    def _require_condition_unlocked(self, participant: dict[str, Any], question_condition: str) -> None:
        entry = self._participant_config_entry(participant)
        order = (entry or {}).get("condition_order")
        if not order or len(order) < 2:
            return
        if question_condition == order[0]:
            return
        grouped: dict[str, list[dict[str, Any]]] = {}
        for question in self.store.list_participant_questions(participant["participant_id"]):
            cond = question.get("condition") or order[0]
            grouped.setdefault(cond, []).append(question)
        first_items = grouped.get(order[0], [])
        if not first_items:
            raise PermissionError("Complete the first study condition before continuing")
        for item in first_items:
            progress = question_progress(
                self.store,
                self.data_dir,
                participant["participant_id"],
                item["assessment_id"],
                item["artifact_version"],
                self._excluded_response_ids(participant),
            )
            if not progress["complete"]:
                raise PermissionError("Complete the first study condition before continuing")
        if not self._questionnaires_complete(participant, order[0]):
            raise PermissionError("Complete the first study condition before continuing")

    def _participant_has_vea_questions(self, participant: dict[str, Any]) -> bool:
        for question in self.store.list_participant_questions(participant["participant_id"]):
            if question.get("condition", "vea") == "vea":
                return True
        return False

    def _condition_for_assessment(self, participant_id: str, assessment_id: str) -> str:
        for question in self.store.list_participant_questions(participant_id):
            if question["assessment_id"] == assessment_id:
                return question.get("condition", "vea")
        return "vea"

    def _experience_for_condition(
        self,
        condition: str,
        participant: dict[str, Any],
    ) -> str:
        if participant.get("experience") != "within_subjects":
            return participant.get("experience", "vea_marking")
        study_config = load_study_config(participant["study_id"], self.project_root)
        return experience_for_condition(condition, study_config)

    def _study_practice_config(self, participant: dict[str, Any]) -> dict[str, Any] | None:
        study = load_study_config(participant["study_id"], self.project_root)
        return practice_config_for_subject(study, participant["subject"])

    def _practice_assessment_id(self, participant: dict[str, Any]) -> str | None:
        practice = self._study_practice_config(participant)
        if not practice:
            return None
        return str(practice["assessment_id"])

    def _walkthrough_required(self, participant: dict[str, Any]) -> bool:
        entry = self._participant_config_entry(participant)
        return bool(entry and entry.get("walkthrough_required"))

    def _practice_for_condition(
        self,
        participant: dict[str, Any],
        condition: str,
    ) -> dict[str, str] | None:
        practice = self._study_practice_config(participant)
        if not practice:
            return None
        return practice_condition_config(practice, condition, self.data_dir)

    def _experimental_questions(
        self,
        participant: dict[str, Any],
        questions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        practice_id = self._practice_assessment_id(participant)
        entry = self._participant_config_entry(participant)
        if not practice_id or not (entry and entry.get("walkthrough_required")):
            return questions
        return [item for item in questions if item["assessment_id"] != practice_id]

    def _filter_practice_ids(
        self,
        study_id: str,
        subject: str,
        assessment_ids: list[str],
        walkthrough_required: bool,
    ) -> list[str]:
        if not walkthrough_required:
            return assessment_ids
        study = load_study_config(study_id, self.project_root)
        practice = practice_config_for_subject(study, subject)
        if not practice:
            return assessment_ids
        practice_id = str(practice["assessment_id"])
        return [aid for aid in assessment_ids if aid != practice_id]

    def _is_condition_unlocked(self, participant: dict[str, Any], condition: str) -> bool:
        entry = self._participant_config_entry(participant)
        order = (entry or {}).get("condition_order")
        if not order:
            return True
        if condition not in order:
            return True
        index = order.index(condition)
        if index == 0:
            return True
        prior = order[index - 1]
        grouped: dict[str, list[dict[str, Any]]] = {}
        for question in self._experimental_questions(
            participant, self.store.list_participant_questions(participant["participant_id"])
        ):
            cond = question.get("condition") or order[0]
            grouped.setdefault(cond, []).append(question)
        prior_items = grouped.get(prior, [])
        if not prior_items:
            return False
        if not self._questionnaires_complete(participant, prior):
            return False
        return all(
            question_progress(
                self.store,
                self.data_dir,
                participant["participant_id"],
                item["assessment_id"],
                item["artifact_version"],
                self._excluded_response_ids(participant),
            )["complete"]
            for item in prior_items
        )

    def _walkthrough_applies_to_participant(self, participant: dict[str, Any], condition: str) -> bool:
        if participant.get("experience") == "vea_marking" and condition == WALKTHROUGH_CONDITION_VEA:
            return True
        if participant.get("experience") == "control_placeholder" and condition in (
            WALKTHROUGH_CONDITION_BASELINE,
            "control",
        ):
            return True
        if participant.get("experience") != "within_subjects":
            return False
        entry = self._participant_config_entry(participant) or {}
        order = entry.get("condition_order") or []
        return condition in order

    def _excluded_response_ids(self, participant: dict[str, Any]) -> set[str]:
        return set()

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

    def _trial_destination(
        self,
        participant: dict[str, Any],
        trial: dict[str, Any],
        question_condition: str | None = None,
    ) -> dict[str, Any]:
        condition = question_condition or self._condition_for_assessment(
            participant["participant_id"], trial["assessment_id"]
        )
        experience = self._experience_for_condition(condition, participant)
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
