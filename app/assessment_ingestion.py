"""One-time assessment ingestion into immutable versioned artifacts."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import torch
from sentence_transformers import SentenceTransformer

from app.assessment_paths import (
    artifact_embeddings_meta_path,
    artifact_embeddings_path,
    artifact_graph_path,
    artifact_manifest_path,
    artifact_response_json_path,
    artifact_response_pt_path,
    artifact_version_dir,
    iter_source_response_txt,
    legacy_responses_dir,
    source_assessment_path,
    source_errata_path,
    source_jev_verification_path,
    source_relationships_path,
)
from app.assessment_registry import (
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    AssessmentRegistry,
    INGESTION_SPEC_VERSION,
    SEGMENTATION_SPEC,
)
from app.graph import load_graph_from_sources, save_graph_artifact
from app.responses import ingest_response_file, segment_response_text
from app.retrieval import QUERY_PREFIX, is_retrieval_eligible

CANDIDATE_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    os.replace(tmp_path, path)


def _validate_sources(
    assessment_id: str,
    stage1: dict,
    stage2: dict,
    jev: dict,
) -> dict[str, Any]:
    if stage1.get("assessment_id") != assessment_id:
        raise ValueError(f"assessment_id mismatch: {stage1.get('assessment_id')} != {assessment_id}")
    node_ids = {
        segment["id"]
        for document in stage1["documents"]
        for segment in document["segments"]
    }
    for rel in stage2.get("relationships", []):
        if rel["source_id"] not in node_ids or rel["target_id"] not in node_ids:
            raise ValueError(f"Relationship references unknown node: {rel}")
    metadata = stage1.get("metadata") or {}
    maximum_mark = metadata.get("maximum_mark")
    if maximum_mark is None:
        raise ValueError("metadata.maximum_mark is required")
    return {
        "subject": metadata.get("subject"),
        "question_id": stage1.get("question_id"),
        "question_label": metadata.get("question_label")
        or f"Q{str(stage1.get('question_id', '')).replace('_', '.')}",
        "maximum_mark": int(maximum_mark),
        "marking_mode": metadata.get("marking_mode"),
    }


def _stable_candidate_aliases(response_ids: list[str]) -> dict[str, str]:
    ordered = sorted(response_ids)
    if len(ordered) > len(CANDIDATE_LETTERS):
        raise ValueError("Too many responses for single-letter aliases")
    return {response_id: CANDIDATE_LETTERS[index] for index, response_id in enumerate(ordered)}


def _build_response_record(txt_path: Path, assessment_id: str) -> dict[str, Any]:
    text = txt_path.read_text(encoding="utf-8")
    response_id = txt_path.stem
    raw_segments = segment_response_text(text)
    segments = [
        {"id": f"{response_id}-seg-{segment['order']}", **segment}
        for segment in raw_segments
    ]
    return {
        "response_id": response_id,
        "assessment_id": assessment_id,
        "source_file": str(txt_path).replace("\\", "/"),
        "text": text,
        "segments": segments,
    }


def _embed_assessment_nodes(graph, model: SentenceTransformer) -> tuple[list[str], torch.Tensor, dict[str, str]]:
    import hashlib

    eligible_ids = [
        node_id
        for node_id, node in graph.nodes.items()
        if is_retrieval_eligible(node)
    ]
    eligible_ids.sort(key=lambda node_id: graph.nodes[node_id]["order"])
    texts = [graph.nodes[node_id]["text"] for node_id in eligible_ids]
    text_hashes = {
        node_id: hashlib.sha256(graph.nodes[node_id]["text"].encode("utf-8")).hexdigest()
        for node_id in eligible_ids
    }
    embeddings = model.encode(
        texts,
        batch_size=16,
        convert_to_tensor=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    ).float().cpu()
    return eligible_ids, embeddings, text_hashes


def _embed_response_segments(response: dict, model: SentenceTransformer) -> torch.Tensor:
    texts = [f"{QUERY_PREFIX}{segment['text']}" for segment in response["segments"]]
    return model.encode(
        texts,
        batch_size=16,
        convert_to_tensor=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    ).float().cpu()


def ingest_assessment(
    data_dir: str | Path,
    assessment_id: str,
    *,
    rebuild: bool = False,
    model: SentenceTransformer | None = None,
) -> dict[str, Any]:
    data_dir = Path(data_dir)
    registry_store = AssessmentRegistry(data_dir)
    registry = registry_store.load()

    assessment_path = source_assessment_path(data_dir, assessment_id)
    relationships_path = source_relationships_path(data_dir, assessment_id)
    jev_path = source_jev_verification_path(data_dir, assessment_id)
    errata_path = source_errata_path(data_dir, assessment_id)

    for path in (assessment_path, relationships_path, jev_path):
        if not path.is_file():
            raise FileNotFoundError(f"Missing source file: {path}")

    stage1 = json.loads(assessment_path.read_text(encoding="utf-8"))
    stage2 = json.loads(relationships_path.read_text(encoding="utf-8"))
    jev = json.loads(jev_path.read_text(encoding="utf-8"))
    metadata = _validate_sources(assessment_id, stage1, stage2, jev)

    source_hashes = registry_store.hash_sources(
        assessment_id,
        assessment_path=assessment_path,
        relationships_path=relationships_path,
        jev_path=jev_path,
        errata_path=errata_path if errata_path.is_file() else None,
    )

    txt_paths = list(iter_source_response_txt(data_dir, assessment_id))
    if not txt_paths:
        raise ValueError(f"No response .txt files found for {assessment_id}")

    response_hashes = {_sha256_file(path): path.stem for path in txt_paths}
    response_hash_map = {path.stem: _sha256_file(path) for path in txt_paths}

    fingerprint = registry_store.compute_fingerprint(
        source_hashes,
        response_hashes=response_hash_map,
    )

    existing = registry_store.find_by_fingerprint(registry, assessment_id, fingerprint)
    if existing and not rebuild:
        return {"status": "unchanged", "version": existing}

    predecessor = registry_store.latest_ready(registry, assessment_id)
    artifact_version = fingerprint
    version_dir = artifact_version_dir(data_dir, assessment_id, artifact_version)
    if version_dir.exists() and not rebuild:
        raise ValueError(f"Artifact version directory already exists: {version_dir}")

    version_dir.mkdir(parents=True, exist_ok=True)
    (version_dir / "responses").mkdir(exist_ok=True)

    graph = load_graph_from_sources(
        assessment_id=assessment_id,
        stage1=stage1,
        stage2=stage2,
        jev=jev,
    )
    save_graph_artifact(graph, artifact_graph_path(data_dir, assessment_id, artifact_version))

    embed_model = model or SentenceTransformer(EMBEDDING_MODEL, device="cpu")
    node_ids, embeddings, text_hashes = _embed_assessment_nodes(graph, embed_model)
    torch.save({"embeddings": embeddings}, artifact_embeddings_path(data_dir, assessment_id, artifact_version))
    _atomic_write_json(
        artifact_embeddings_meta_path(data_dir, assessment_id, artifact_version),
        {
            "model": EMBEDDING_MODEL,
            "dim": EMBEDDING_DIM,
            "assessment_id": assessment_id,
            "artifact_version": artifact_version,
            "node_ids": node_ids,
            "text_hashes": text_hashes,
            "source_hashes": source_hashes,
            "ingestion_spec_version": INGESTION_SPEC_VERSION,
            "segmentation_spec": SEGMENTATION_SPEC,
            "built_at": _utc_now(),
        },
    )

    response_ids = sorted(path.stem for path in txt_paths)
    aliases = _stable_candidate_aliases(response_ids)
    response_records: list[dict[str, Any]] = []

    for order, response_id in enumerate(response_ids, start=1):
        txt_path = next(path for path in txt_paths if path.stem == response_id)
        record = _build_response_record(txt_path, assessment_id)
        json_path = artifact_response_json_path(data_dir, assessment_id, artifact_version, response_id)
        _atomic_write_json(json_path, record)
        segment_embeddings = _embed_response_segments(record, embed_model)
        torch.save(
            {"segment_ids": [segment["id"] for segment in record["segments"]], "embeddings": segment_embeddings},
            artifact_response_pt_path(data_dir, assessment_id, artifact_version, response_id),
        )
        response_records.append(
            {
                "response_id": response_id,
                "candidate_id": aliases[response_id],
                "response_order": order,
                "source_txt_hash": response_hash_map[response_id],
                "segment_count": len(record["segments"]),
            }
        )

    version_record = {
        "artifact_version": artifact_version,
        "fingerprint": fingerprint,
        "status": "ready",
        "created_at": _utc_now(),
        "predecessor": predecessor["artifact_version"] if predecessor else None,
        "source_hashes": source_hashes,
        "metadata": metadata,
        "responses": response_records,
        "artifacts": {
            "graph": str(artifact_graph_path(data_dir, assessment_id, artifact_version).relative_to(data_dir)).replace("\\", "/"),
            "embeddings": str(artifact_embeddings_path(data_dir, assessment_id, artifact_version).relative_to(data_dir)).replace("\\", "/"),
            "embeddings_meta": str(
                artifact_embeddings_meta_path(data_dir, assessment_id, artifact_version).relative_to(data_dir)
            ).replace("\\", "/"),
        },
        "ingestion_spec_version": INGESTION_SPEC_VERSION,
        "segmentation_spec": SEGMENTATION_SPEC,
        "embedding_model": EMBEDDING_MODEL,
    }

    _atomic_write_json(artifact_manifest_path(data_dir, assessment_id, artifact_version), version_record)
    registry_store.append_version(registry, assessment_id, version_record)
    registry_store.save(registry)

    return {"status": "ingested", "version": version_record}


def ingest_all(data_dir: str | Path, *, rebuild: bool = False) -> list[dict[str, Any]]:
    from app.views import list_assessment_ids

    results: list[dict[str, Any]] = []
    for assessment_id in list_assessment_ids(data_dir):
        try:
            relationships_path = source_relationships_path(data_dir, assessment_id)
            jev_path = source_jev_verification_path(data_dir, assessment_id)
            if not relationships_path.is_file() or not jev_path.is_file():
                results.append({"assessment_id": assessment_id, "status": "skipped", "reason": "incomplete triplet"})
                continue
            result = ingest_assessment(data_dir, assessment_id, rebuild=rebuild)
            results.append({"assessment_id": assessment_id, **result})
        except Exception as exc:
            results.append({"assessment_id": assessment_id, "status": "error", "error": str(exc)})
    return results
