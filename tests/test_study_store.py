import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import app
from app.dependencies import STUDY_SESSION_COOKIE
from app.judgement import JudgementStore
from app.study.service import StudyService
from app.study.store import StudyStore, hash_token


@pytest.fixture
def study_env(tmp_path, monkeypatch):
    db_path = tmp_path / "study.db"
    judgements_dir = tmp_path / "judgements"
    monkeypatch.setenv("VEA_STUDY_DB", str(db_path))
    monkeypatch.setenv("VEA_JUDGEMENTS_DIR", str(judgements_dir))
    monkeypatch.setenv("VEA_DATA_DIR", "data")
    monkeypatch.setenv("VEA_USE_REGISTRY", "0")
    store = StudyStore(db_path)
    service = StudyService(
        store=store,
        judgement_store=JudgementStore(judgements_dir),
        data_dir="data",
        project_root=Path.cwd(),
    )
    return {"store": store, "service": service}


def test_token_digest_is_one_way(study_env):
    token = "example-token-value"
    assert hash_token(token) != token
    assert hash_token(token) == hash_token(token)


def test_provision_and_resume_session(study_env):
    service = study_env["service"]
    token = "participant-a-token"
    service.provision_participant(
        study_id="pilot-study",
        participant_id="P001",
        token=token,
        condition="vea",
        subject="chemistry",
    )
    auth = service.authenticate_token(token)
    restored = service.restore_session(auth["session_id"])
    assert restored["participant"]["participant_id"] == "P001"


def test_question_progression_returns_to_selection(study_env):
    service = study_env["service"]
    token = "participant-b-token"
    service.provision_participant(
        study_id="pilot-study",
        participant_id="P002",
        token=token,
        condition="vea",
        subject="chemistry",
    )
    auth = service.authenticate_token(token)
    participant_id = auth["participant"]["participant_id"]

    first = service.start_question(participant_id, "C-JUN25-8464C1H-02_3")
    trial_id = first["trial_id"]
    outcome = service.submit_final_mark(participant_id, trial_id, 4)
    assert outcome["destination"] in {"next_trial", "question_selection"}


def test_import_participants_file(study_env):
    result = study_env["service"].import_participants_file("pilot-study")
    assert result["imported"] >= 1
    assert result["participants"][0]["question_count"] >= 1


def test_list_questions_includes_responses(study_env):
    service = study_env["service"]
    token = "responses-token"
    service.provision_participant(
        study_id="pilot-study",
        participant_id="P004",
        token=token,
        condition="vea",
        subject="chemistry",
    )
    auth = service.authenticate_token(token)
    questions = service.list_questions(auth["participant"]["participant_id"])
    assert questions["questions"][0]["responses"]
    assert len(questions["questions"][0]["responses"]) >= 1


def test_authenticate_token_from_participants_json_without_import(study_env, tmp_path):
    config_dir = tmp_path / "config" / "studies"
    config_dir.mkdir(parents=True)
    (config_dir / "pilot-study.json").write_text(
        '{"schema_version":"1.0","study_id":"pilot-study","subjects":{"chemistry":{"assessment_order":["C-JUN25-8464C1H-02_3"]}}}',
        encoding="utf-8",
    )
    (config_dir / "pilot-study-participants.json").write_text(
        """{
  "study_id": "pilot-study",
  "participants": [
    {
      "participant_id": "JSON-ONLY-001",
      "token": "json-only-login-token",
      "condition": "vea",
      "subject": "chemistry"
    }
  ]
}""",
        encoding="utf-8",
    )
    service = StudyService(
        store=study_env["store"],
        judgement_store=study_env["service"].judgement_store,
        data_dir="data",
        project_root=tmp_path,
    )
    auth = service.authenticate_token("json-only-login-token")
    assert auth["participant"]["participant_id"] == "JSON-ONLY-001"
    assert service.store.get_participant("JSON-ONLY-001") is not None


def test_study_api_sets_cookie(study_env):
    token = "api-token"
    study_env["service"].provision_participant(
        study_id="pilot-study",
        participant_id="P003",
        token=token,
        condition="control",
        subject="chemistry",
    )
    client = TestClient(app)
    response = client.post("/study/session", json={"token": token})
    assert response.status_code == 200
    assert STUDY_SESSION_COOKIE in response.cookies
