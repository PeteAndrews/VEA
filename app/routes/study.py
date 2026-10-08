"""Study session, question selection, and trial endpoints."""

from __future__ import annotations

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


@router.post("/session")
def create_study_session(body: StudySessionRequest, response: Response) -> dict:
    try:
        payload = study_service().authenticate_token(body.token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from None
    response.set_cookie(
        key=STUDY_SESSION_COOKIE,
        value=payload["session_id"],
        httponly=True,
        samesite="lax",
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
