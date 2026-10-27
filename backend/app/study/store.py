"""SQLite persistence for study assignments, sessions, and trials."""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


SCHEMA_VERSION = 1


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class StudyStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @classmethod
    def from_env(cls) -> StudyStore:
        path = os.getenv("VEA_STUDY_DB", "data/study.db")
        return cls(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            row = conn.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
            current = row["version"] or 0
            if current < SCHEMA_VERSION:
                self._apply_schema(conn)
                conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, _utc_now()),
                )

    def _apply_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS participants (
                participant_id TEXT PRIMARY KEY,
                study_id TEXT NOT NULL,
                token_digest TEXT NOT NULL UNIQUE,
                condition TEXT NOT NULL,
                subject TEXT NOT NULL,
                experience TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS participant_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                participant_id TEXT NOT NULL REFERENCES participants(participant_id),
                assessment_id TEXT NOT NULL,
                artifact_version TEXT NOT NULL,
                question_order INTEGER NOT NULL,
                UNIQUE(participant_id, assessment_id)
            );

            CREATE TABLE IF NOT EXISTS study_sessions (
                session_id TEXT PRIMARY KEY,
                participant_id TEXT NOT NULL REFERENCES participants(participant_id),
                created_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS trials (
                trial_id TEXT PRIMARY KEY,
                participant_id TEXT NOT NULL REFERENCES participants(participant_id),
                assessment_id TEXT NOT NULL,
                artifact_version TEXT NOT NULL,
                response_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                response_order INTEGER NOT NULL,
                marking_session_id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL,
                UNIQUE(participant_id, assessment_id, response_id)
            );

            CREATE TABLE IF NOT EXISTS trial_submissions (
                trial_id TEXT PRIMARY KEY REFERENCES trials(trial_id),
                final_mark INTEGER NOT NULL,
                submitted_at TEXT NOT NULL
            );
            """
        )

    def upsert_participant(
        self,
        *,
        participant_id: str,
        study_id: str,
        token_digest: str,
        condition: str,
        subject: str,
        experience: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO participants (
                    participant_id, study_id, token_digest, condition, subject, experience, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(participant_id) DO UPDATE SET
                    study_id=excluded.study_id,
                    token_digest=excluded.token_digest,
                    condition=excluded.condition,
                    subject=excluded.subject,
                    experience=excluded.experience
                """,
                (participant_id, study_id, token_digest, condition, subject, experience, _utc_now()),
            )

    def replace_participant_questions(
        self,
        participant_id: str,
        questions: list[dict[str, Any]],
    ) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM participant_questions WHERE participant_id = ?", (participant_id,))
            for item in questions:
                conn.execute(
                    """
                    INSERT INTO participant_questions (
                        participant_id, assessment_id, artifact_version, question_order
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        participant_id,
                        item["assessment_id"],
                        item["artifact_version"],
                        item["question_order"],
                    ),
                )

    def get_participant_by_token_digest(self, token_digest: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM participants WHERE token_digest = ?",
                (token_digest,),
            ).fetchone()
            return dict(row) if row else None

    def get_participant(self, participant_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM participants WHERE participant_id = ?",
                (participant_id,),
            ).fetchone()
            return dict(row) if row else None

    def list_participant_questions(self, participant_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT assessment_id, artifact_version, question_order
                FROM participant_questions
                WHERE participant_id = ?
                ORDER BY question_order ASC, assessment_id ASC
                """,
                (participant_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def create_study_session(self, participant_id: str) -> dict[str, Any]:
        session_id = _new_id("ss")
        now = _utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO study_sessions (session_id, participant_id, created_at, last_seen_at)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, participant_id, now, now),
            )
        return {"session_id": session_id, "participant_id": participant_id, "created_at": now}

    def touch_study_session(self, session_id: str) -> dict[str, Any] | None:
        now = _utc_now()
        with self.connect() as conn:
            conn.execute(
                "UPDATE study_sessions SET last_seen_at = ? WHERE session_id = ?",
                (now, session_id),
            )
            row = conn.execute(
                "SELECT * FROM study_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_study_session(self, session_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM study_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            return dict(row) if row else None

    def create_trial(
        self,
        *,
        participant_id: str,
        assessment_id: str,
        artifact_version: str,
        response_id: str,
        candidate_id: str,
        response_order: int,
        marking_session_id: str,
    ) -> dict[str, Any]:
        trial_id = _new_id("trial")
        now = _utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO trials (
                    trial_id, participant_id, assessment_id, artifact_version,
                    response_id, candidate_id, response_order, marking_session_id,
                    status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)
                """,
                (
                    trial_id,
                    participant_id,
                    assessment_id,
                    artifact_version,
                    response_id,
                    candidate_id,
                    response_order,
                    marking_session_id,
                    now,
                ),
            )
        return self.get_trial(trial_id) or {}

    def get_trial(self, trial_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM trials WHERE trial_id = ?", (trial_id,)).fetchone()
            return dict(row) if row else None

    def get_open_trial(self, participant_id: str, assessment_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM trials
                WHERE participant_id = ? AND assessment_id = ? AND status = 'open'
                ORDER BY response_order ASC
                LIMIT 1
                """,
                (participant_id, assessment_id),
            ).fetchone()
            return dict(row) if row else None

    def list_trials_for_question(self, participant_id: str, assessment_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT t.*, s.final_mark, s.submitted_at
                FROM trials t
                LEFT JOIN trial_submissions s ON s.trial_id = t.trial_id
                WHERE t.participant_id = ? AND t.assessment_id = ?
                ORDER BY t.response_order ASC
                """,
                (participant_id, assessment_id),
            ).fetchall()
            return [dict(row) for row in rows]

    def submit_trial(self, trial_id: str, final_mark: int) -> dict[str, Any]:
        now = _utc_now()
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT final_mark FROM trial_submissions WHERE trial_id = ?",
                (trial_id,),
            ).fetchone()
            if existing:
                if int(existing["final_mark"]) == final_mark:
                    row = conn.execute("SELECT * FROM trials WHERE trial_id = ?", (trial_id,)).fetchone()
                    return dict(row) if row else {}
                raise ValueError("Trial already submitted with a different mark")
            conn.execute(
                "INSERT INTO trial_submissions (trial_id, final_mark, submitted_at) VALUES (?, ?, ?)",
                (trial_id, final_mark, now),
            )
            conn.execute(
                "UPDATE trials SET status = 'submitted' WHERE trial_id = ?",
                (trial_id,),
            )
            row = conn.execute("SELECT * FROM trials WHERE trial_id = ?", (trial_id,)).fetchone()
            return dict(row) if row else {}

    def get_submission(self, trial_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM trial_submissions WHERE trial_id = ?",
                (trial_id,),
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def generate_token() -> str:
        return secrets.token_urlsafe(32)
