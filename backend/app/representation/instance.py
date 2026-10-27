"""Combined graph instance: Layer 1 assessment + optional Layer 2/3 views."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.assessment_runtime import get_graph_service
from app.graph import AssessmentGraph
from app.judgement import JudgementStore
from app.representation.judgement_graph import JudgementGraph
from app.representation.response_graph import ResponseGraph
from app.responses import load_response


@dataclass
class GraphInstance:
    assessment: AssessmentGraph
    assessment_id: str
    response: ResponseGraph | None = None
    judgement: JudgementGraph | None = None


def load_instance(
    *,
    data_dir: str | Path = "data",
    assessment_id: str,
    response_id: str | None = None,
    marking_session_id: str | None = None,
    include_judgement_history: bool = False,
    artifact_version: str | None = None,
) -> GraphInstance:
    data_dir = Path(data_dir)
    graph_service = get_graph_service(str(data_dir), assessment_id, artifact_version)
    assessment = graph_service.graph

    response_graph: ResponseGraph | None = None
    judgement_graph: JudgementGraph | None = None

    if response_id:
        record = load_response(
            response_id,
            responses_dir=data_dir / "responses",
            assessment_id=assessment_id,
            artifact_version=getattr(graph_service, "artifact_version", None),
        )
        response_graph = ResponseGraph.from_record(record)

    if marking_session_id and response_id:
        judgements_dir = Path(os.getenv("VEA_JUDGEMENTS_DIR", str(data_dir / "judgements")))
        state = JudgementStore(judgements_dir).load(marking_session_id, assessment_id, response_id)
        final_mark, submitted_at = _final_mark_for_session(
            Path(os.getenv("VEA_STUDY_DB", str(data_dir / "study.db"))),
            marking_session_id,
        )
        judgement_graph = JudgementGraph.from_state(
            state,
            response_graph=response_graph,
            final_mark=final_mark,
            final_mark_submitted_at=submitted_at,
            include_history=include_judgement_history,
        )

    return GraphInstance(
        assessment=assessment,
        assessment_id=assessment_id,
        response=response_graph,
        judgement=judgement_graph,
    )


def _final_mark_for_session(study_db: Path, marking_session_id: str) -> tuple[int | None, str | None]:
    if not study_db.is_file():
        return None, None
    with sqlite3.connect(study_db) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT s.final_mark, s.submitted_at
            FROM trial_submissions s
            JOIN trials t ON t.trial_id = s.trial_id
            WHERE t.marking_session_id = ?
            """,
            (marking_session_id,),
        ).fetchone()
    if row is None:
        return None, None
    return int(row["final_mark"]), row["submitted_at"]
