from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import api
from app.responses import load_response
from app.views import dev_responses_list, load_stage1, resolve_response_id

ASSESSMENT_ID = "C-JUN25-8464C1H-02_3"
BIOLOGY_ASSESSMENT_ID = "B-JUN24-84612H-05_6"
CANDIDATE_ID = "A"
CRITERION_ID = "ms_02_3-point-4"
DETAIL_ID = "ms_02_3-detail-4a"
BIOLOGY_ANSWER_DETAIL_ID = "ms_05_6-contraception-detail-fsh"
BAD_CRITERION_ID = "ms_02_3-level-2"


@pytest.fixture
def client(tmp_path):
    api._graph_service.cache_clear()
    api._evidence_pipeline.cache_clear()
    api.JUDGEMENTS_DIR = tmp_path / "judgements"
    return TestClient(api.app)


@pytest.fixture
def session(client):
    response = client.post("/marking-sessions", json={"examiner_id": "Alex Parker", "label": "test"})
    assert response.status_code == 200
    return response.json()


@pytest.fixture
def response_record():
    response_id = resolve_response_id("data", ASSESSMENT_ID, CANDIDATE_ID)
    return load_response(response_id, responses_dir=Path("data/responses"))


@pytest.fixture
def sample_span(response_record):
    text = response_record["text"]
    start_char = 0
    end_char = 40
    return {
        "start_char": start_char,
        "end_char": end_char,
        "text": text[start_char:end_char],
    }


def _judgement_path(tmp_path: Path, session_id: str, response_id: str) -> Path:
    return tmp_path / "judgements" / session_id / f"{response_id}.json"


def _judgement_prefix(session_id: str, assessment_id: str = ASSESSMENT_ID) -> str:
    return f"/marking-sessions/{session_id}/assessments/{assessment_id}/candidates/{CANDIDATE_ID}/judgement"


def test_create_marking_session(client):
    response = client.post("/marking-sessions", json={"examiner_id": "Alex Parker"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["marking_session_id"].startswith("ms-")
    assert payload["examiner_id"] == "Alex Parker"


def test_create_coding_accepts_biology_answer_detail(client, session):
    sid = session["marking_session_id"]
    span_text = "Oestrogen and progesterone are used in the contraceptive pill."
    response = client.post(
        f"{_judgement_prefix(sid, BIOLOGY_ASSESSMENT_ID)}/codings",
        json={
            "start_char": 0,
            "end_char": len(span_text),
            "text": span_text,
            "criterion_id": BIOLOGY_ANSWER_DETAIL_ID,
        },
    )
    assert response.status_code == 200
    assert response.json()["codings"][0]["criterion_id"] == BIOLOGY_ANSWER_DETAIL_ID


def test_create_coding_persists_offsets(client, session, sample_span, tmp_path, response_record):
    sid = session["marking_session_id"]
    response = client.post(
        f"{_judgement_prefix(sid)}/codings",
        json={**sample_span, "criterion_id": CRITERION_ID},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["marking_session_id"] == sid
    assert "response_id" not in payload
    assert len(payload["codings"]) == 1
    coding = payload["codings"][0]
    assert coding["start_char"] == sample_span["start_char"]
    assert coding["end_char"] == sample_span["end_char"]
    assert coding["text"] == sample_span["text"]
    assert coding["criterion_id"] == CRITERION_ID

    stored = json.loads(_judgement_path(tmp_path, sid, response_record["response_id"]).read_text(encoding="utf-8"))
    assert stored["response_id"] == response_record["response_id"]
    assert stored["events"][-1]["type"] == "EVIDENCE_CODED"


def test_text_mismatch_returns_422(client, session, sample_span):
    sid = session["marking_session_id"]
    response = client.post(
        f"{_judgement_prefix(sid)}/codings",
        json={**sample_span, "text": "wrong text", "criterion_id": CRITERION_ID},
    )
    assert response.status_code == 422


def test_non_criterion_returns_422(client, session, sample_span):
    sid = session["marking_session_id"]
    response = client.post(
        f"{_judgement_prefix(sid)}/codings",
        json={**sample_span, "criterion_id": BAD_CRITERION_ID},
    )
    assert response.status_code == 422


def test_duplicate_coding_is_idempotent(client, session, sample_span, tmp_path, response_record):
    sid = session["marking_session_id"]
    body = {**sample_span, "criterion_id": CRITERION_ID}
    first = client.post(f"{_judgement_prefix(sid)}/codings", json=body)
    second = client.post(f"{_judgement_prefix(sid)}/codings", json=body)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["codings"][0]["id"] == second.json()["codings"][0]["id"]

    stored = json.loads(_judgement_path(tmp_path, sid, response_record["response_id"]).read_text(encoding="utf-8"))
    assert len(stored["events"]) == 1


def test_update_criterion_and_span(client, session, response_record, sample_span):
    sid = session["marking_session_id"]
    created = client.post(
        f"{_judgement_prefix(sid)}/codings",
        json={**sample_span, "criterion_id": CRITERION_ID},
    ).json()
    coding_id = created["codings"][0]["id"]

    revised = client.patch(
        f"{_judgement_prefix(sid)}/codings/{coding_id}",
        json={"criterion_id": DETAIL_ID},
    )
    assert revised.status_code == 200
    assert revised.json()["codings"][0]["criterion_id"] == DETAIL_ID

    new_start = 50
    new_end = 90
    reanchored = client.patch(
        f"{_judgement_prefix(sid)}/codings/{coding_id}",
        json={
            "start_char": new_start,
            "end_char": new_end,
            "text": response_record["text"][new_start:new_end],
        },
    )
    assert reanchored.status_code == 200
    coding = reanchored.json()["codings"][0]
    assert coding["start_char"] == new_start
    assert coding["end_char"] == new_end


def test_remove_coding_cleans_orphan_span(client, session, sample_span, tmp_path, response_record):
    sid = session["marking_session_id"]
    created = client.post(
        f"{_judgement_prefix(sid)}/codings",
        json={**sample_span, "criterion_id": CRITERION_ID},
    ).json()
    coding_id = created["codings"][0]["id"]

    removed = client.delete(f"{_judgement_prefix(sid)}/codings/{coding_id}")
    assert removed.status_code == 200
    assert removed.json()["codings"] == []
    assert removed.json()["spans"] == []

    stored = json.loads(_judgement_path(tmp_path, sid, response_record["response_id"]).read_text(encoding="utf-8"))
    assert stored["events"][-1]["type"] == "CODING_REMOVED"


def test_tentative_level_set_change_clear(client, session, sample_span):
    sid = session["marking_session_id"]
    client.post(
        f"{_judgement_prefix(sid)}/codings",
        json={**sample_span, "criterion_id": CRITERION_ID},
    )

    set_level = client.put(f"{_judgement_prefix(sid)}/tentative-level", json={"level": 2})
    assert set_level.status_code == 200
    payload = set_level.json()
    assert payload["tentative_level"]["level"] == 2
    assert payload["level_context"]["mark_range"] == {"min": 3, "max": 4}

    changed = client.put(f"{_judgement_prefix(sid)}/tentative-level", json={"level": 3})
    assert changed.status_code == 200
    assert changed.json()["tentative_level"]["level"] == 3

    cleared = client.put(f"{_judgement_prefix(sid)}/tentative-level", json={"level": None})
    assert cleared.status_code == 200
    assert cleared.json()["tentative_level"] is None


def test_level_context_includes_control_variable(client):
    response = client.get(f"/assessments/{ASSESSMENT_ID}/levels/3/context")
    assert response.status_code == 200
    required = response.json()["required_criteria"]
    assert any(item["criterion_id"] == "ms_02_3-point-6" for item in required)


def test_independent_sessions(client, sample_span):
    session_a = client.post("/marking-sessions", json={"examiner_id": "Examiner A"}).json()
    session_b = client.post("/marking-sessions", json={"examiner_id": "Examiner B"}).json()

    created_a = client.post(
        f"{_judgement_prefix(session_a['marking_session_id'])}/codings",
        json={**sample_span, "criterion_id": CRITERION_ID},
    ).json()
    judgement_b = client.get(_judgement_prefix(session_b["marking_session_id"])).json()

    assert len(created_a["codings"]) == 1
    assert judgement_b["codings"] == []


def test_layer1_files_unchanged(client, session, sample_span, tmp_path):
    stage1_path = Path("data/questions") / f"{ASSESSMENT_ID}.json"
    before = stage1_path.read_bytes()
    sid = session["marking_session_id"]
    client.post(
        f"{_judgement_prefix(sid)}/codings",
        json={**sample_span, "criterion_id": CRITERION_ID},
    )
    client.put(f"{_judgement_prefix(sid)}/tentative-level", json={"level": 2})
    after = stage1_path.read_bytes()
    assert before == after
    assert load_stage1("data", ASSESSMENT_ID) == json.loads(before.decode("utf-8"))
