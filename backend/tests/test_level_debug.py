from __future__ import annotations

import json
from pathlib import Path

from app.level_debug import maybe_save_level_judgement_prompt_debug


def test_debug_save_skipped_when_disabled(monkeypatch, tmp_path):
    monkeypatch.delenv("VEA_DEBUG_LEVEL_JUDGEMENT", raising=False)
    maybe_save_level_judgement_prompt_debug(
        {"tentative_level": {"level": 2}},
        meta={"response_id": "r1", "marking_session_id": "ms-1", "tentative_level": 2},
    )
    assert not (tmp_path / "debug").exists()


def test_debug_save_writes_json(monkeypatch, tmp_path):
    monkeypatch.setenv("VEA_DEBUG_LEVEL_JUDGEMENT", "1")
    monkeypatch.setenv("VEA_DEBUG_LEVEL_JUDGEMENT_DIR", str(tmp_path))
    maybe_save_level_judgement_prompt_debug(
        {
            "tentative_level": {"level": 3},
            "rule_coverage": [],
            "coded_support": [],
        },
        meta={
            "response_id": "C-JUN25-8464C1H-02_3_response-A",
            "marking_session_id": "ms-abc",
            "tentative_level": 3,
        },
    )
    files = list(Path(tmp_path).glob("*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert "system_prompt" in payload
    assert payload["user_payload"]["tentative_level"] == {"level": 3}
    assert payload["meta"]["tentative_level"] == 3
