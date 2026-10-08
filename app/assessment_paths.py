"""Canonical path resolution for assessments, artifacts, and responses."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class ResponsePaths:
    assessment_id: str
    response_id: str
    txt: Path | None
    json: Path
    pt: Path

    @property
    def base_dir(self) -> Path:
        return self.json.parent


def data_root(data_dir: str | Path = "data") -> Path:
    return Path(data_dir)


def legacy_questions_dir(data_dir: str | Path) -> Path:
    root = data_root(data_dir)
    sub = root / "questions"
    return sub if sub.is_dir() else root


def assessment_source_dir(data_dir: str | Path, assessment_id: str) -> Path:
    packaged = data_root(data_dir) / "assessments" / assessment_id / "source"
    if packaged.is_dir():
        return packaged
    return legacy_questions_dir(data_dir)


def source_assessment_path(data_dir: str | Path, assessment_id: str) -> Path:
    packaged = assessment_source_dir(data_dir, assessment_id) / "assessment.json"
    if packaged.is_file():
        return packaged
    return legacy_questions_dir(data_dir) / f"{assessment_id}.json"


def source_relationships_path(data_dir: str | Path, assessment_id: str) -> Path:
    packaged = assessment_source_dir(data_dir, assessment_id) / "relationships.json"
    if packaged.is_file():
        return packaged
    return legacy_questions_dir(data_dir) / f"{assessment_id}-relationships.json"


def source_jev_verification_path(data_dir: str | Path, assessment_id: str) -> Path:
    packaged = assessment_source_dir(data_dir, assessment_id) / "jev-verification.json"
    if packaged.is_file():
        return packaged
    return legacy_questions_dir(data_dir) / f"{assessment_id}-jev-verification.json"


def source_errata_path(data_dir: str | Path, assessment_id: str) -> Path:
    packaged = assessment_source_dir(data_dir, assessment_id) / "errata.json"
    if packaged.is_file():
        return packaged
    return data_root(data_dir) / "errata" / f"{assessment_id}.json"


def legacy_responses_dir(data_dir: str | Path, assessment_id: str) -> Path:
    return data_root(data_dir) / "responses" / assessment_id


def artifact_version_dir(data_dir: str | Path, assessment_id: str, artifact_version: str) -> Path:
    return data_root(data_dir) / "artifacts" / assessment_id / artifact_version


def artifact_graph_path(data_dir: str | Path, assessment_id: str, artifact_version: str) -> Path:
    return artifact_version_dir(data_dir, assessment_id, artifact_version) / "graph.pt"


def artifact_embeddings_path(data_dir: str | Path, assessment_id: str, artifact_version: str) -> Path:
    return artifact_version_dir(data_dir, assessment_id, artifact_version) / "embeddings.pt"


def artifact_embeddings_meta_path(data_dir: str | Path, assessment_id: str, artifact_version: str) -> Path:
    return artifact_version_dir(data_dir, assessment_id, artifact_version) / "embeddings.meta.json"


def artifact_manifest_path(data_dir: str | Path, assessment_id: str, artifact_version: str) -> Path:
    return artifact_version_dir(data_dir, assessment_id, artifact_version) / "manifest.json"


def artifact_response_json_path(
    data_dir: str | Path,
    assessment_id: str,
    artifact_version: str,
    response_id: str,
) -> Path:
    return (
        artifact_version_dir(data_dir, assessment_id, artifact_version)
        / "responses"
        / f"{response_id}.json"
    )


def artifact_response_pt_path(
    data_dir: str | Path,
    assessment_id: str,
    artifact_version: str,
    response_id: str,
) -> Path:
    return (
        artifact_version_dir(data_dir, assessment_id, artifact_version)
        / "responses"
        / f"{response_id}.pt"
    )


def registry_path(data_dir: str | Path) -> Path:
    return data_root(data_dir) / "registry.json"


def resolve_response_paths(
    data_dir: str | Path,
    assessment_id: str,
    response_id: str,
    *,
    artifact_version: str | None = None,
) -> ResponsePaths:
    if artifact_version:
        json_path = artifact_response_json_path(data_dir, assessment_id, artifact_version, response_id)
        pt_path = artifact_response_pt_path(data_dir, assessment_id, artifact_version, response_id)
        txt_path = legacy_responses_dir(data_dir, assessment_id) / f"{response_id}.txt"
        if not txt_path.is_file():
            txt_path = None
        return ResponsePaths(
            assessment_id=assessment_id,
            response_id=response_id,
            txt=txt_path,
            json=json_path,
            pt=pt_path,
        )

    nested_json = legacy_responses_dir(data_dir, assessment_id) / f"{response_id}.json"
    nested_pt = legacy_responses_dir(data_dir, assessment_id) / f"{response_id}.pt"
    flat_json = data_root(data_dir) / "responses" / f"{response_id}.json"
    flat_pt = data_root(data_dir) / "responses" / f"{response_id}.pt"

    if nested_json.is_file():
        json_path = nested_json
        pt_path = nested_pt
        txt_path = legacy_responses_dir(data_dir, assessment_id) / f"{response_id}.txt"
    elif flat_json.is_file():
        json_path = flat_json
        pt_path = flat_pt
        txt_path = data_root(data_dir) / "responses" / f"{response_id}.txt"
    else:
        raise KeyError(response_id)

    if txt_path is not None and not txt_path.is_file():
        txt_path = None

    return ResponsePaths(
        assessment_id=assessment_id,
        response_id=response_id,
        txt=txt_path,
        json=json_path,
        pt=pt_path,
    )


def iter_source_response_txt(data_dir: str | Path, assessment_id: str) -> Iterator[Path]:
    response_dir = legacy_responses_dir(data_dir, assessment_id)
    if response_dir.is_dir():
        yield from sorted(response_dir.glob("*.txt"))
        return
    responses_root = data_root(data_dir) / "responses"
    if not responses_root.is_dir():
        return
    for path in sorted(responses_root.glob("*.txt")):
        response_id = path.stem
        json_path = responses_root / f"{response_id}.json"
        if json_path.is_file():
            with json_path.open(encoding="utf-8") as handle:
                record = json.load(handle)
            if record.get("assessment_id") == assessment_id:
                yield path
