"""Append-only registry for immutable assessment artifact versions."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.assessment_paths import registry_path

REGISTRY_SCHEMA_VERSION = "1.0"
INGESTION_SPEC_VERSION = "1"
SEGMENTATION_SPEC = "segment_v1"
EMBEDDING_MODEL = "BAAI/bge-large-en-v1.5"
EMBEDDING_DIM = 1024


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    os.replace(tmp_path, path)


class AssessmentRegistry:
    def __init__(self, data_dir: str | Path = "data") -> None:
        self.data_dir = Path(data_dir)
        self.path = registry_path(self.data_dir)

    def load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {
                "schema_version": REGISTRY_SCHEMA_VERSION,
                "ingestion_spec_version": INGESTION_SPEC_VERSION,
                "assessments": {},
            }
        with self.path.open(encoding="utf-8") as handle:
            return json.load(handle)

    def save(self, registry: dict[str, Any]) -> None:
        _atomic_write(self.path, registry)

    def hash_sources(
        self,
        assessment_id: str,
        *,
        assessment_path: Path,
        relationships_path: Path,
        jev_path: Path,
        errata_path: Path | None = None,
    ) -> dict[str, str]:
        hashes = {
            "assessment": _sha256_file(assessment_path),
            "relationships": _sha256_file(relationships_path),
            "jev_verification": _sha256_file(jev_path),
        }
        if errata_path is not None and errata_path.is_file():
            hashes["errata"] = _sha256_file(errata_path)
        return hashes

    def compute_fingerprint(
        self,
        source_hashes: dict[str, str],
        *,
        response_hashes: dict[str, str] | None = None,
    ) -> str:
        pipeline = {
            "ingestion_spec_version": INGESTION_SPEC_VERSION,
            "segmentation_spec": SEGMENTATION_SPEC,
            "embedding_model": EMBEDDING_MODEL,
        }
        payload = {
            "sources": dict(sorted(source_hashes.items())),
            "responses": dict(sorted((response_hashes or {}).items())),
            "pipeline": pipeline,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return _sha256_text(encoded)[:16]

    def find_version(self, registry: dict[str, Any], assessment_id: str, artifact_version: str) -> dict[str, Any] | None:
        entry = registry.get("assessments", {}).get(assessment_id)
        if entry is None:
            return None
        for version in entry.get("versions", []):
            if version.get("artifact_version") == artifact_version:
                return version
        return None

    def find_by_fingerprint(
        self,
        registry: dict[str, Any],
        assessment_id: str,
        fingerprint: str,
    ) -> dict[str, Any] | None:
        entry = registry.get("assessments", {}).get(assessment_id)
        if entry is None:
            return None
        for version in entry.get("versions", []):
            if version.get("fingerprint") == fingerprint and version.get("status") == "ready":
                return version
        return None

    def latest_ready(self, registry: dict[str, Any], assessment_id: str) -> dict[str, Any] | None:
        entry = registry.get("assessments", {}).get(assessment_id)
        if entry is None:
            return None
        latest_id = entry.get("latest_ready")
        if latest_id:
            version = self.find_version(registry, assessment_id, latest_id)
            if version and version.get("status") == "ready":
                return version
        versions = [v for v in entry.get("versions", []) if v.get("status") == "ready"]
        if not versions:
            return None
        return versions[-1]

    def list_ready_assessments(self, registry: dict[str, Any]) -> list[str]:
        ready: list[str] = []
        for assessment_id, entry in registry.get("assessments", {}).items():
            if self.latest_ready(registry, assessment_id) is not None:
                ready.append(assessment_id)
        return sorted(ready)

    def append_version(
        self,
        registry: dict[str, Any],
        assessment_id: str,
        version_record: dict[str, Any],
    ) -> dict[str, Any]:
        assessments = registry.setdefault("assessments", {})
        entry = assessments.setdefault(
            assessment_id,
            {"assessment_id": assessment_id, "versions": [], "latest_ready": None},
        )
        versions: list[dict[str, Any]] = entry.setdefault("versions", [])
        if any(v.get("artifact_version") == version_record["artifact_version"] for v in versions):
            raise ValueError(f"Version already registered: {version_record['artifact_version']}")
        versions.append(version_record)
        if version_record.get("status") == "ready":
            entry["latest_ready"] = version_record["artifact_version"]
        registry["updated_at"] = _utc_now()
        return version_record
