import json
from pathlib import Path

import pytest

from app.assessment_registry import AssessmentRegistry


def test_fingerprint_is_stable():
    registry = AssessmentRegistry("data")
    source_hashes = {"assessment": "abc", "relationships": "def", "jev_verification": "ghi"}
    response_hashes = {"response-a": "111", "response-b": "222"}
    first = registry.compute_fingerprint(source_hashes, response_hashes=response_hashes)
    second = registry.compute_fingerprint(source_hashes, response_hashes=response_hashes)
    assert first == second


def test_append_version_is_immutable(tmp_path):
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "assessments": {},
            }
        ),
        encoding="utf-8",
    )
    store = AssessmentRegistry(tmp_path)
    registry = store.load()
    version = {
        "artifact_version": "v1",
        "fingerprint": "v1",
        "status": "ready",
        "metadata": {"maximum_mark": 6},
        "responses": [],
    }
    store.append_version(registry, "C-JUN25-8464C1H-02_3", version)
    store.save(registry)
    with pytest.raises(ValueError):
        store.append_version(registry, "C-JUN25-8464C1H-02_3", version)
