from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import api
from app.responses import load_response
from app.views import dev_responses_list, load_stage1

ASSESSMENT_ID = "C-JUN25-8464C1H-02_3"
BIOLOGY_ASSESSMENT_ID = "B-JUN24-84612H-05_6"
FORBIDDEN_LABELS = ("top-mark", "low-mark", "higher-ambiguity", "JUN25-8464C1H-02_3_response")


@pytest.fixture
def client():
    api._graph_service.cache_clear()
    api._evidence_pipeline.cache_clear()
    return TestClient(api.app)


def test_list_assessments(client):
    response = client.get("/assessments")
    assert response.status_code == 200
    items = response.json()["assessments"]
    assert any(item["assessment_id"] == ASSESSMENT_ID for item in items)


def test_question_view(client):
    response = client.get(f"/assessments/{ASSESSMENT_ID}/question")
    assert response.status_code == 200
    payload = response.json()
    assert payload["max_mark"] == 6
    assert any("calcium oxide" in text for text in payload["instructions"])


def test_levels_view_errata_and_fallback(client):
    response = client.get(f"/assessments/{ASSESSMENT_ID}/levels")
    assert response.status_code == 200
    payload = response.json()
    levels = payload["levels"]
    assert [level["level"] for level in levels] == [3, 2, 1, 0]

    level2 = next(level for level in levels if level["level"] == 2)
    assert level2["mark_range"] == {"min": 3, "max": 4}
    assert level2["mark_range_source"] == {"min": 5, "max": 6}
    assert level2["provenance"]["errata_id"] == "errata-02_3-001"

    level0 = next(level for level in levels if level["level"] == 0)
    assert level0["source"] == "fallback"

    stage1 = load_stage1("data", ASSESSMENT_ID)
    source_level2 = next(
        segment
        for document in stage1["documents"]
        for segment in document["segments"]
        if segment["id"] == "ms_02_3-level-2"
    )
    assert source_level2["mark_range"] == {"min": 5, "max": 6}


def test_indicative_content_view(client):
    response = client.get(f"/assessments/{ASSESSMENT_ID}/indicative-content")
    assert response.status_code == 200
    groups = response.json()["groups"]
    assert len(groups) == 1
    key_steps = groups[0]["key_steps"]
    assert len(key_steps) == 6
    point6 = next(step for step in key_steps if step["id"] == "ms_02_3-point-6")
    assert point6["is_control_variable"] is True
    point4 = next(step for step in key_steps if step["id"] == "ms_02_3-point-4")
    assert point4["alternatives"]
    assert any(detail["id"] == "ms_02_3-detail-4a" for detail in point4["details"])


def test_indicative_content_view_biology_includes_answer_details(client):
    response = client.get(f"/assessments/{BIOLOGY_ASSESSMENT_ID}/indicative-content")
    assert response.status_code == 200
    groups = response.json()["groups"]

    populated = [group for group in groups if group["key_steps"]]
    assert len(populated) == 2
    assert {group["text"] for group in populated} == {"contraception:", "treatment of infertility:"}

    key_steps = [step for group in populated for step in group["key_steps"]]
    assert len(key_steps) == 5

    details = [detail for step in key_steps for detail in step["details"]]
    assert len(details) == 5
    assert any(detail["id"] == "ms_05_6-contraception-detail-fsh" for detail in details)
    assert any("inhibition of FSH" in detail["text"] for detail in details)

    hormones = next(step for step in key_steps if step["id"] == "ms_05_6-contraception-point-1")
    assert len(hormones["details"]) == 2


def test_candidates_neutral_labels(client):
    response = client.get(f"/assessments/{ASSESSMENT_ID}/candidates")
    assert response.status_code == 200
    candidates = response.json()["candidates"]
    assert len(candidates) == 3
    assert [item["candidate_id"] for item in candidates] == ["A", "B", "C"]
    serialized = json.dumps(candidates)
    for label in FORBIDDEN_LABELS:
        assert label not in serialized


def test_candidate_detail_preserves_text_and_offsets(client):
    dev = dev_responses_list("data", ASSESSMENT_ID)
    by_candidate = {item["candidate_id"]: item["response_id"] for item in dev}
    record = load_response(by_candidate["A"], responses_dir=Path("data/responses"))

    response = client.get(f"/assessments/{ASSESSMENT_ID}/candidates/A")
    assert response.status_code == 200
    detail = response.json()
    serialized = json.dumps(detail)
    for label in FORBIDDEN_LABELS:
        assert label not in serialized

    assert detail["text"] == record["text"]
    for segment in detail["segments"]:
        assert detail["text"][segment["start_char"] : segment["end_char"]] == segment["text"]


def test_dev_response_includes_source_label(client):
    dev = client.get("/responses", params={"assessment_id": ASSESSMENT_ID}).json()["responses"]
    assert len(dev) == 3
    assert all("source_label" in item for item in dev)


def test_unknown_assessment(client):
    response = client.get("/assessments/UNKNOWN")
    assert response.status_code == 404


def test_unknown_candidate(client):
    response = client.get(f"/assessments/{ASSESSMENT_ID}/candidates/Z")
    assert response.status_code == 404
