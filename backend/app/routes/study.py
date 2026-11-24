"""Study session, question selection, and trial endpoints."""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.dependencies import (
    STUDY_SESSION_COOKIE,
    require_study_session,
    study_service,
)

router = APIRouter(prefix="/study", tags=["study"])


class StudySessionRequest(BaseModel):
    token: str = Field(min_length=8)


class SubmitFinalMarkRequest(BaseModel):
    final_mark: int = Field(ge=0)


class CompleteWalkthroughRequest(BaseModel):
    marking_session_id: str = Field(min_length=1)
    final_mark: int = Field(ge=0)


class QuestionnaireWriteRequest(BaseModel):
    answers: dict
    updated_at: str | None = None


@router.post("/session")
def create_study_session(body: StudySessionRequest, response: Response) -> dict:
    try:
        payload = study_service().authenticate_token(body.token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from None
    cross_site = os.getenv("VEA_CROSS_SITE_COOKIES", "0") == "1"

    response.set_cookie(
        key=STUDY_SESSION_COOKIE,
        value=payload["session_id"],
        httponly=True,
        secure=cross_site,
        samesite="none" if cross_site else "lax",
        max_age=60 * 60 * 24 * 30,
    )
    return payload


@router.get("/session")
def get_study_session(request: Request) -> dict:
    _, payload = require_study_session(request)
    return payload


@router.get("/questions")
def list_study_questions(request: Request) -> dict:
    _, payload = require_study_session(request)
    participant_id = payload["participant"]["participant_id"]
    return study_service().list_questions(participant_id)


@router.post("/walkthrough/start")
def start_walkthrough(request: Request) -> dict:
    _, payload = require_study_session(request)
    participant_id = payload["participant"]["participant_id"]
    try:
        return study_service().start_walkthrough(participant_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Participant not found") from None
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post("/walkthrough/complete")
def complete_walkthrough(body: CompleteWalkthroughRequest, request: Request) -> dict:
    _, payload = require_study_session(request)
    participant_id = payload["participant"]["participant_id"]
    try:
        return study_service().complete_walkthrough(
            participant_id,
            body.marking_session_id,
            body.final_mark,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Participant not found") from None
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post("/baseline-walkthrough/start")
def start_baseline_walkthrough(request: Request) -> dict:
    _, payload = require_study_session(request)
    participant_id = payload["participant"]["participant_id"]
    try:
        return study_service().start_baseline_walkthrough(participant_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Participant not found") from None
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None


@router.post("/baseline-walkthrough/complete")
def complete_baseline_walkthrough(body: CompleteWalkthroughRequest, request: Request) -> dict:
    _, payload = require_study_session(request)
    participant_id = payload["participant"]["participant_id"]
    try:
        return study_service().complete_baseline_walkthrough(
            participant_id,
            body.marking_session_id,
            body.final_mark,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Participant not found") from None
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


def _questionnaire_error(exc: ValueError) -> HTTPException:
    message = str(exc)
    if "already submitted" in message or "updated elsewhere" in message:
        return HTTPException(status_code=409, detail=message)
    return HTTPException(status_code=422, detail=message)


@router.get("/questionnaires/{key}/{scope}")
def get_questionnaire(key: str, scope: str, request: Request) -> dict:
    _, payload = require_study_session(request)
    participant_id = payload["participant"]["participant_id"]
    try:
        return study_service().get_questionnaire(participant_id, key, scope)
    except KeyError:
        raise HTTPException(status_code=404, detail="Participant not found") from None
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None


@router.put("/questionnaires/{key}/{scope}")
def save_questionnaire(key: str, scope: str, body: QuestionnaireWriteRequest, request: Request) -> dict:
    _, payload = require_study_session(request)
    participant_id = payload["participant"]["participant_id"]
    try:
        return study_service().save_questionnaire_draft(
            participant_id, key, scope, body.answers, body.updated_at
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Participant not found") from None
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except ValueError as exc:
        raise _questionnaire_error(exc) from None


@router.post("/questionnaires/{key}/{scope}/submit")
def submit_questionnaire(key: str, scope: str, body: QuestionnaireWriteRequest, request: Request) -> dict:
    _, payload = require_study_session(request)
    participant_id = payload["participant"]["participant_id"]
    try:
        return study_service().submit_questionnaire(
            participant_id, key, scope, body.answers, body.updated_at
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Participant not found") from None
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except ValueError as exc:
        raise _questionnaire_error(exc) from None


@router.post("/questions/{assessment_id}/next-trial")
def start_question_trial(assessment_id: str, request: Request) -> dict:
    _, payload = require_study_session(request)
    participant_id = payload["participant"]["participant_id"]
    try:
        return study_service().start_question(participant_id, assessment_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.get("/trials/{trial_id}")
def get_trial(trial_id: str, request: Request) -> dict:
    _, payload = require_study_session(request)
    participant_id = payload["participant"]["participant_id"]
    try:
        return study_service().get_trial(participant_id, trial_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Trial not found: {trial_id}") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post("/trials/{trial_id}/submit")
def submit_trial(trial_id: str, body: SubmitFinalMarkRequest, request: Request) -> dict:
    _, payload = require_study_session(request)
    participant_id = payload["participant"]["participant_id"]
    try:
        return study_service().submit_final_mark(participant_id, trial_id, body.final_mark)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Trial not found: {trial_id}") from None
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
