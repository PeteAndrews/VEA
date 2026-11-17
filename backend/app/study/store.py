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


SCHEMA_VERSION = 5


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
                if current == 0:
                    self._apply_schema(conn)
                else:
                    self._migrate_schema(conn, current)
                conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, _utc_now()),
                )

    def _migrate_schema(self, conn: sqlite3.Connection, current: int) -> None:
        if current < 3:
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(participant_questions)").fetchall()
            }
            if "condition" not in columns:
                conn.execute(
                    "ALTER TABLE participant_questions ADD COLUMN condition TEXT NOT NULL DEFAULT 'vea'"
                )
        if current < 4:
            self._migrate_walkthrough_completions_v4(conn)
        if current < 5:
            self._migrate_questionnaires_v5(conn)

    def _migrate_walkthrough_completions_v4(self, conn: sqlite3.Connection) -> None:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='walkthrough_completions'"
        ).fetchone()
        if not table:
            conn.execute(
                """
                CREATE TABLE walkthrough_completions (
                    participant_id TEXT NOT NULL REFERENCES participants(participant_id),
                    condition TEXT NOT NULL,
                    marking_session_id TEXT NOT NULL,
                    final_mark INTEGER NOT NULL,
                    completed_at TEXT NOT NULL,
                    PRIMARY KEY (participant_id, condition)
                )
                """
            )
            return
        columns = {row[1] for row in conn.execute("PRAGMA table_info(walkthrough_completions)").fetchall()}
        if "condition" in columns:
            return
        conn.executescript(
            """
            CREATE TABLE walkthrough_completions_new (
                participant_id TEXT NOT NULL REFERENCES participants(participant_id),
                condition TEXT NOT NULL,
                marking_session_id TEXT NOT NULL,
                final_mark INTEGER NOT NULL,
                completed_at TEXT NOT NULL,
                PRIMARY KEY (participant_id, condition)
            );
            INSERT INTO walkthrough_completions_new (
                participant_id, condition, marking_session_id, final_mark, completed_at
            )
            SELECT participant_id, 'vea', marking_session_id, final_mark, completed_at
            FROM walkthrough_completions;
            DROP TABLE walkthrough_completions;
            ALTER TABLE walkthrough_completions_new RENAME TO walkthrough_completions;
            """
        )

    def _migrate_questionnaires_v5(self, conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(participants)").fetchall()}
        if "interface_labels" not in columns:
            conn.execute("ALTER TABLE participants ADD COLUMN interface_labels TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS questionnaire_responses (
                participant_id TEXT NOT NULL REFERENCES participants(participant_id),
                questionnaire_key TEXT NOT NULL,
                scope TEXT NOT NULL,
                version INTEGER NOT NULL,
                answers_json TEXT NOT NULL,
                context_json TEXT,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                submitted_at TEXT,
                PRIMARY KEY (participant_id, questionnaire_key, scope)
            )
            """
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
                interface_labels TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS participant_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                participant_id TEXT NOT NULL REFERENCES participants(participant_id),
                assessment_id TEXT NOT NULL,
                artifact_version TEXT NOT NULL,
                question_order INTEGER NOT NULL,
                condition TEXT NOT NULL DEFAULT 'vea',
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

            CREATE TABLE IF NOT EXISTS questionnaire_responses (
                participant_id TEXT NOT NULL REFERENCES participants(participant_id),
                questionnaire_key TEXT NOT NULL,
                scope TEXT NOT NULL,
                version INTEGER NOT NULL,
                answers_json TEXT NOT NULL,
                context_json TEXT,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                submitted_at TEXT,
                PRIMARY KEY (participant_id, questionnaire_key, scope)
            );

            CREATE TABLE IF NOT EXISTS walkthrough_completions (
                participant_id TEXT NOT NULL REFERENCES participants(participant_id),
                condition TEXT NOT NULL,
                marking_session_id TEXT NOT NULL,
                final_mark INTEGER NOT NULL,
                completed_at TEXT NOT NULL,
                PRIMARY KEY (participant_id, condition)
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
                        participant_id, assessment_id, artifact_version, question_order, condition
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        participant_id,
                        item["assessment_id"],
                        item["artifact_version"],
                        item["question_order"],
                        item.get("condition", "vea"),
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
                SELECT assessment_id, artifact_version, question_order, condition
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

    def get_walkthrough_completion(
        self,
        participant_id: str,
        condition: str = "vea",
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM walkthrough_completions
                WHERE participant_id = ? AND condition = ?
                """,
                (participant_id, condition),
            ).fetchone()
            return dict(row) if row else None

    def record_walkthrough_completion(
        self,
        participant_id: str,
        marking_session_id: str,
        final_mark: int,
        *,
        condition: str = "vea",
    ) -> dict[str, Any]:
        now = _utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO walkthrough_completions (
                    participant_id, condition, marking_session_id, final_mark, completed_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(participant_id, condition) DO UPDATE SET
                    marking_session_id=excluded.marking_session_id,
                    final_mark=excluded.final_mark,
                    completed_at=excluded.completed_at
                """,
                (participant_id, condition, marking_session_id, final_mark, now),
            )
            row = conn.execute(
                """
                SELECT * FROM walkthrough_completions
                WHERE participant_id = ? AND condition = ?
                """,
                (participant_id, condition),
            ).fetchone()
            return dict(row) if row else {}

    def get_submission(self, trial_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM trial_submissions WHERE trial_id = ?",
                (trial_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_interface_labels(self, participant_id: str) -> dict[str, str] | None:
        import json

        with self.connect() as conn:
            row = conn.execute(
                "SELECT interface_labels FROM participants WHERE participant_id = ?",
                (participant_id,),
            ).fetchone()
        if not row or not row["interface_labels"]:
            return None
        loaded = json.loads(row["interface_labels"])
        if not isinstance(loaded, dict) or not loaded.get("A") or not loaded.get("B"):
            return None
        return {"A": str(loaded["A"]), "B": str(loaded["B"])}

    def set_interface_labels_if_empty(self, participant_id: str, labels: dict[str, str]) -> dict[str, str]:
        import json

        existing = self.get_interface_labels(participant_id)
        if existing:
            return existing
        payload = json.dumps({"A": labels["A"], "B": labels["B"]})
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE participants
                SET interface_labels = ?
                WHERE participant_id = ? AND interface_labels IS NULL
                """,
                (payload, participant_id),
            )
        return self.get_interface_labels(participant_id) or {"A": labels["A"], "B": labels["B"]}

    def get_questionnaire_response(
        self,
        participant_id: str,
        questionnaire_key: str,
        scope: str,
    ) -> dict[str, Any] | None:
        import json

        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM questionnaire_responses
                WHERE participant_id = ? AND questionnaire_key = ? AND scope = ?
                """,
                (participant_id, questionnaire_key, scope),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["answers"] = json.loads(item.pop("answers_json") or "{}")
        item["context"] = json.loads(item.pop("context_json") or "null")
        return item

    def list_questionnaire_responses(
        self,
        participant_id: str | None = None,
        *,
        submitted_only: bool = False,
    ) -> list[dict[str, Any]]:
        import json

        query = "SELECT * FROM questionnaire_responses"
        params: list[Any] = []
        clauses: list[str] = []
        if participant_id:
            clauses.append("participant_id = ?")
            params.append(participant_id)
        if submitted_only:
            clauses.append("status = 'submitted'")
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY participant_id, scope, questionnaire_key"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["answers"] = json.loads(item.pop("answers_json") or "{}")
            item["context"] = json.loads(item.pop("context_json") or "null")
            items.append(item)
        return items

    def save_questionnaire_response(
        self,
        *,
        participant_id: str,
        questionnaire_key: str,
        scope: str,
        version: int,
        answers: dict[str, Any],
        context: dict[str, Any] | None,
        status: str,
        expected_updated_at: str | None,
    ) -> dict[str, Any]:
        import json

        now = _utc_now()
        answers_json = json.dumps(answers, sort_keys=True)
        context_json = json.dumps(context) if context is not None else None
        with self.connect() as conn:
            current = conn.execute(
                """
                SELECT status, updated_at, answers_json, started_at
                FROM questionnaire_responses
                WHERE participant_id = ? AND questionnaire_key = ? AND scope = ?
                """,
                (participant_id, questionnaire_key, scope),
            ).fetchone()
            if current and current["status"] == "submitted":
                if status != "submitted" or current["answers_json"] != answers_json:
                    raise ValueError("Questionnaire already submitted")
                return self.get_questionnaire_response(participant_id, questionnaire_key, scope) or {}
            if current and expected_updated_at and current["updated_at"] != expected_updated_at:
                raise ValueError("Questionnaire was updated elsewhere")
            if current and expected_updated_at is None:
                raise ValueError("Questionnaire was updated elsewhere")
            submitted_at = now if status == "submitted" else None
            if current is None:
                conn.execute(
                    """
                    INSERT INTO questionnaire_responses (
                        participant_id, questionnaire_key, scope, version, answers_json,
                        context_json, status, started_at, updated_at, submitted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        participant_id,
                        questionnaire_key,
                        scope,
                        version,
                        answers_json,
                        context_json,
                        status,
                        now,
                        now,
                        submitted_at,
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE questionnaire_responses
                    SET version = ?, answers_json = ?, context_json = ?, status = ?,
                        updated_at = ?, submitted_at = COALESCE(?, submitted_at)
                    WHERE participant_id = ? AND questionnaire_key = ? AND scope = ?
                    """,
                    (
                        version,
                        answers_json,
                        context_json,
                        status,
                        now,
                        submitted_at,
                        participant_id,
                        questionnaire_key,
                        scope,
                    ),
                )
        return self.get_questionnaire_response(participant_id, questionnaire_key, scope) or {}

    def get_trial_by_marking_session(self, marking_session_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM trials WHERE marking_session_id = ?",
                (marking_session_id,),
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def generate_token() -> str:
        return secrets.token_urlsafe(32)
