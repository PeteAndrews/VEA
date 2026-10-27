"""Runtime loading of registered assessment artifacts."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

import torch

from app.assessment_paths import (
    artifact_embeddings_meta_path,
    artifact_embeddings_path,
    artifact_graph_path,
    artifact_response_json_path,
    artifact_response_pt_path,
    resolve_response_paths,
)
from app.assessment_registry import AssessmentRegistry, EMBEDDING_DIM
from app.graph import AssessmentGraph, load_graph, load_graph_artifact
from app.graph_service import GraphService


def use_registry(data_dir: str | Path = "data", assessment_id: str | None = None) -> bool:
    if os.getenv("VEA_USE_REGISTRY", "0").strip().lower() in {"0", "false", "no"}:
        return False
    registry = AssessmentRegistry(data_dir).load()
    store = AssessmentRegistry(data_dir)
    if assessment_id:
        return store.latest_ready(registry, assessment_id) is not None
    return bool(store.list_ready_assessments(registry))


def _scatter_assessment_embeddings(graph: AssessmentGraph, node_ids: list[str], embeddings: torch.Tensor) -> None:
    by_type: dict[str, list[tuple[int, torch.Tensor]]] = {}
    for retrieval_index, node_id in enumerate(node_ids):
        node_type, pyg_index = graph.index[node_id]
        by_type.setdefault(node_type, []).append((pyg_index, embeddings[retrieval_index]))

    for node_type in graph.data.node_types:
        if node_type == "response":
            continue
        store = graph.data[node_type]
        count = int(store.num_nodes)
        emb = torch.zeros(count, EMBEDDING_DIM, dtype=torch.float)
        mask = torch.zeros(count, dtype=torch.bool)
        for pyg_index, vector in by_type.get(node_type, []):
            emb[pyg_index] = vector
            mask[pyg_index] = True
        store.emb = emb
        store.retrieval_mask = mask


@lru_cache(maxsize=16)
def load_registered_graph(data_dir: str, assessment_id: str, artifact_version: str) -> AssessmentGraph:
    graph_path = artifact_graph_path(data_dir, assessment_id, artifact_version)
    if not graph_path.is_file():
        raise FileNotFoundError(f"Missing graph artifact: {graph_path}")
    graph = load_graph_artifact(graph_path)

    meta_path = artifact_embeddings_meta_path(data_dir, assessment_id, artifact_version)
    emb_path = artifact_embeddings_path(data_dir, assessment_id, artifact_version)
    with meta_path.open(encoding="utf-8") as handle:
        meta = json.load(handle)
    payload = torch.load(emb_path, map_location="cpu", weights_only=True)
    _scatter_assessment_embeddings(graph, meta["node_ids"], payload["embeddings"].float())
    return graph


def load_registered_response(
    data_dir: str | Path,
    assessment_id: str,
    artifact_version: str,
    response_id: str,
) -> dict:
    path = artifact_response_json_path(data_dir, assessment_id, artifact_version, response_id)
    if not path.is_file():
        raise KeyError(response_id)
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_registered_response_embeddings(
    data_dir: str | Path,
    assessment_id: str,
    artifact_version: str,
    response_id: str,
) -> dict:
    path = artifact_response_pt_path(data_dir, assessment_id, artifact_version, response_id)
    if not path.is_file():
        raise KeyError(response_id)
    return torch.load(path, map_location="cpu", weights_only=True)


def get_version_record(
    data_dir: str | Path,
    assessment_id: str,
    artifact_version: str | None = None,
) -> dict:
    registry = AssessmentRegistry(data_dir).load()
    store = AssessmentRegistry(data_dir)
    if artifact_version:
        version = store.find_version(registry, assessment_id, artifact_version)
        if version is None or version.get("status") != "ready":
            raise KeyError(f"Unknown or not-ready version: {artifact_version}")
        return version
    version = store.latest_ready(registry, assessment_id)
    if version is None:
        raise KeyError(assessment_id)
    return version


class RegisteredGraphService(GraphService):
    def __init__(self, graph: AssessmentGraph, *, artifact_version: str, version_record: dict) -> None:
        super().__init__(graph)
        self.artifact_version = artifact_version
        self.version_record = version_record


@lru_cache(maxsize=16)
def get_graph_service(
    data_dir: str,
    assessment_id: str,
    artifact_version: str | None = None,
) -> RegisteredGraphService | GraphService:
    if use_registry(data_dir, assessment_id):
        version = get_version_record(data_dir, assessment_id, artifact_version)
        graph = load_registered_graph(data_dir, assessment_id, version["artifact_version"])
        return RegisteredGraphService(
            graph,
            artifact_version=version["artifact_version"],
            version_record=version,
        )
    return GraphService(load_graph(data_dir=data_dir, assessment_id=assessment_id))
