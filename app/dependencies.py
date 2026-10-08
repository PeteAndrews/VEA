"""Shared FastAPI dependencies."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import HTTPException, Request

from app.judgement import JudgementStore
from app.study.service import StudyService
from app.study.store import StudyStore

STUDY_SESSION_COOKIE = "vea_study_session"

DATA_DIR = os.getenv("VEA_DATA_DIR", "data")
JUDGEMENTS_DIR = Path(os.getenv("VEA_JUDGEMENTS_DIR", str(Path(DATA_DIR) / "judgements")))
STUDY_DB_PATH = os.getenv("VEA_STUDY_DB", str(Path(DATA_DIR) / "study.db"))


def judgement_store() -> JudgementStore:
    path = Path(os.getenv("VEA_JUDGEMENTS_DIR", str(Path(DATA_DIR) / "judgements")))
    return JudgementStore(path)


def study_store() -> StudyStore:
    path = os.getenv("VEA_STUDY_DB", str(Path(DATA_DIR) / "study.db"))
    return StudyStore(path)


def study_service() -> StudyService:
    return StudyService(
        store=study_store(),
        judgement_store=judgement_store(),
        data_dir=DATA_DIR,
    )


def get_study_session_id(request: Request) -> str | None:
    return request.cookies.get(STUDY_SESSION_COOKIE)


def require_study_session(request: Request) -> tuple[str, dict]:
    session_id = get_study_session_id(request)
    if not session_id:
        raise HTTPException(status_code=401, detail="Study session required")
    try:
        payload = study_service().restore_session(session_id)
    except KeyError:
        raise HTTPException(status_code=401, detail="Invalid study session") from None
    return session_id, payload


def require_trial_access(request: Request, trial_id: str) -> dict:
    _, session = require_study_session(request)
    participant_id = session["participant"]["participant_id"]
    try:
        return study_service().get_trial(participant_id, trial_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Trial not found: {trial_id}") from None
