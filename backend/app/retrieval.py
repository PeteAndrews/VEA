from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Literal

import torch
from sentence_transformers import SentenceTransformer

from app.graph_service import GraphService
from app.responses import RESPONSE_SEGMENT_TYPE, attach_response_to_graph, load_response

MODEL_NAME = "BAAI/bge-large-en-v1.5"
EMBED_DIM = 1024
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

RETRIEVAL_DOCUMENT_TYPES = {"question", "mark_scheme", "commentary"}
CRITERIA_NODE_TYPES = {"level", "level_rule", "mark_point"}
RetrievalScope = Literal["criteria", "commentary", "question", "all"]
SCOPES: tuple[str, ...] = ("criteria", "commentary", "question", "all")


def is_retrieval_eligible(node: dict) -> bool:
    return (
        not node["structural_only"]
        and node["document_type"] in RETRIEVAL_DOCUMENT_TYPES
        and node.get("segment_type") != RESPONSE_SEGMENT_TYPE
    )


def scope_matches(node: dict, scope: RetrievalScope) -> bool:
    if not is_retrieval_eligible(node):
        return False
    if scope == "all":
        return True
    if scope == "criteria":
        return node["node_type"] in CRITERIA_NODE_TYPES
    if scope == "commentary":
        return node["node_type"] == "commentary"
    if scope == "question":
        return node["node_type"] == "question"
    raise ValueError(f"Unsupported scope: {scope}")


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _device() -> str:
    forced = os.getenv("VEA_EMBED_DEVICE")
    if forced:
        return forced
    return "cuda" if torch.cuda.is_available() else "cpu"


class RetrievalService:
    def __init__(
        self,
        graph_service: GraphService,
        data_dir: str | Path = "data",
        model: SentenceTransformer | None = None,
    ) -> None:
        self.graph_service = graph_service
        self.graph = graph_service.graph
        self.data_dir = Path(data_dir)
        self.cache_dir = self.data_dir / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.model = model
        self._retrieval_node_ids: list[str] = []
        self._retrieval_embeddings: torch.Tensor | None = None
        self._artifact_version: str | None = None
        self._ensure_assessment_embeddings()

    @classmethod
    def from_data_dir(
        cls,
        data_dir: str | Path = "data",
        assessment_id: str = "C-JUN25-8464C1H-02_3",
        response_id: str | None = None,
        model: SentenceTransformer | None = None,
        *,
        artifact_version: str | None = None,
    ) -> RetrievalService:
        from app.assessment_runtime import get_graph_service, get_version_record, use_registry
        from app.graph import load_graph

        if use_registry(data_dir, assessment_id):
            version = get_version_record(data_dir, assessment_id, artifact_version)
            graph_service = get_graph_service(str(data_dir), assessment_id, version["artifact_version"])
            graph = graph_service.graph
            artifact_version = version["artifact_version"]
        else:
            graph = load_graph(data_dir=data_dir, assessment_id=assessment_id)
            graph_service = GraphService(graph)
            artifact_version = None

        if response_id:
            response = load_response(
                response_id,
                responses_dir=Path(data_dir) / "responses",
                assessment_id=assessment_id,
                artifact_version=artifact_version,
            )
            attach_response_to_graph(graph, response)
        service = cls(graph_service, data_dir=data_dir, model=model)
        service._artifact_version = artifact_version
        return service

    def ingest_response(self, txt_path: str | Path, assessment_id: str | None = None) -> dict:
        from app.responses import ingest_response_file

        assessment_id = assessment_id or self.graph.assessment_id
        record = ingest_response_file(
            txt_path,
            assessment_id=assessment_id,
            data_dir=self.data_dir,
        )
        self._embed_and_save_response(record)
        return record

    def similar(
        self,
        response_segment_id: str,
        top_k: int = 5,
        scope: RetrievalScope = "criteria",
    ) -> dict:
        segment = self.graph_service.get_node(response_segment_id)
        if segment["segment_type"] != RESPONSE_SEGMENT_TYPE:
            raise KeyError(response_segment_id)

        response_id = segment["document_id"]
        segment_embedding = self._load_response_segment_embedding(response_id, response_segment_id)
        matches = self._rank(segment_embedding, scope=scope, top_k=top_k)

        return {
            "response_segment_id": response_segment_id,
            "response_segment_text": segment["text"],
            "start_char": segment.get("start_char"),
            "end_char": segment.get("end_char"),
            "scope": scope,
            "retrieval": "candidate",
            "matches": matches,
        }

    def search_response(
        self,
        response_id: str,
        query: str,
        top_k: int = 5,
    ) -> dict:
        """Semantic search across all segments in a candidate response."""
        from app.assessment_paths import resolve_response_paths
        from app.assessment_runtime import load_registered_response_embeddings, use_registry

        response = load_response(
            response_id,
            responses_dir=self.data_dir / "responses",
            assessment_id=self.graph.assessment_id,
            artifact_version=self._artifact_version,
        )
        if use_registry(self.data_dir, self.graph.assessment_id) and self._artifact_version:
            payload = load_registered_response_embeddings(
                self.data_dir, self.graph.assessment_id, self._artifact_version, response_id
            )
        else:
            paths = resolve_response_paths(self.data_dir, self.graph.assessment_id, response_id)
            if not paths.pt.exists():
                self._embed_and_save_response(response)
            payload = torch.load(paths.pt, map_location="cpu", weights_only=True)
        segment_ids: list[str] = payload["segment_ids"]
        embeddings = payload["embeddings"].float()
        if embeddings.numel() == 0:
            return {"query": query, "response_id": response_id, "matches": []}

        model = self._get_model()
        query_embedding = model.encode(
            f"{QUERY_PREFIX}{query}",
            convert_to_tensor=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).float().cpu()
        scores = query_embedding @ embeddings.T
        k = min(top_k, scores.size(0))
        values, indices = torch.topk(scores, k=k)

        segment_lookup = {segment["id"]: segment for segment in response["segments"]}
        matches: list[dict] = []
        for score, index in zip(values.tolist(), indices.tolist()):
            segment_id = segment_ids[index]
            segment = segment_lookup.get(segment_id)
            if segment is None:
                continue
            matches.append(
                {
                    "segment_id": segment_id,
                    "text": segment["text"],
                    "start_char": segment["start_char"],
                    "end_char": segment["end_char"],
                    "cosine_similarity": round(float(score), 6),
                    "retrieval": "response_segment",
                }
            )
        return {
            "query": query,
            "response_id": response_id,
            "matches": matches,
        }

    def similar_text(
        self,
        text: str,
        top_k: int = 5,
        scope: RetrievalScope = "criteria",
        *,
        evidence_id: str | None = None,
        start_char: int | None = None,
        end_char: int | None = None,
    ) -> dict:
        model = self._get_model()
        embedding = model.encode(
            f"{QUERY_PREFIX}{text}",
            convert_to_tensor=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).float().cpu()
        matches = self._rank(embedding, scope=scope, top_k=top_k)
        return {
            "response_segment_id": evidence_id,
            "response_segment_text": text,
            "start_char": start_char,
            "end_char": end_char,
            "scope": scope,
            "retrieval": "candidate",
            "matches": matches,
        }

    def _rank(
        self,
        segment_embedding: torch.Tensor,
        *,
        scope: RetrievalScope,
        top_k: int,
    ) -> list[dict]:
        node_ids, embeddings = self._scoped_embeddings(scope)
        if not node_ids:
            return []

        scores = segment_embedding @ embeddings.T
        k = min(top_k, scores.size(0))
        values, indices = torch.topk(scores, k=k)

        matches = []
        for score, index in zip(values.tolist(), indices.tolist()):
            node_id = node_ids[index]
            node = self.graph_service.get_node(node_id)
            matches.append(
                {
                    "node_id": node_id,
                    "node_type": node["node_type"],
                    "segment_type": node["segment_type"],
                    "text": node["text"],
                    "cosine_similarity": round(float(score), 6),
                    "retrieval": "candidate",
                }
            )
        return matches

    def response_context(
        self,
        response_segment_id: str,
        top_k: int = 5,
        scope: RetrievalScope = "criteria",
    ) -> dict:
        similar = self.similar(response_segment_id, top_k=top_k, scope=scope)
        enriched = []
        for match in similar["matches"]:
            enriched.append(
                {
                    **match,
                    "context": self.graph_service.get_context(match["node_id"]),
                }
            )
        return {
            "response_segment_id": similar["response_segment_id"],
            "response_segment_text": similar["response_segment_text"],
            "start_char": similar.get("start_char"),
            "end_char": similar.get("end_char"),
            "scope": scope,
            "retrieval": "candidate",
            "matches": enriched,
        }

    def _scoped_embeddings(self, scope: RetrievalScope) -> tuple[list[str], torch.Tensor]:
        assert self._retrieval_embeddings is not None
        node_ids = [node_id for node_id in self._retrieval_node_ids if scope_matches(self.graph.nodes[node_id], scope)]
        if not node_ids:
            return [], torch.empty(0, EMBED_DIM)
        index_lookup = {node_id: index for index, node_id in enumerate(self._retrieval_node_ids)}
        indices = [index_lookup[node_id] for node_id in node_ids]
        return node_ids, self._retrieval_embeddings[indices]

    def _ensure_assessment_embeddings(self) -> None:
        from app.assessment_paths import artifact_embeddings_meta_path, artifact_embeddings_path
        from app.assessment_runtime import use_registry

        if use_registry(self.data_dir, self.graph.assessment_id) and self._artifact_version:
            meta_path = artifact_embeddings_meta_path(
                self.data_dir, self.graph.assessment_id, self._artifact_version
            )
            emb_path = artifact_embeddings_path(
                self.data_dir, self.graph.assessment_id, self._artifact_version
            )
            if meta_path.is_file() and emb_path.is_file():
                with meta_path.open(encoding="utf-8") as f:
                    meta = json.load(f)
                payload = torch.load(emb_path, map_location="cpu", weights_only=True)
                self._retrieval_node_ids = meta["node_ids"]
                self._retrieval_embeddings = payload["embeddings"].float()
                return

        eligible_ids = [
            node_id
            for node_id, node in self.graph.nodes.items()
            if is_retrieval_eligible(node)
        ]
        eligible_ids.sort(key=lambda node_id: self.graph.nodes[node_id]["order"])

        meta_path = self.cache_dir / f"{self.graph.assessment_id}-bge-large.meta.json"
        emb_path = self.cache_dir / f"{self.graph.assessment_id}-bge-large.pt"
        text_hashes = {node_id: _text_hash(self.graph.nodes[node_id]["text"]) for node_id in eligible_ids}
        cache_valid = False

        if meta_path.exists() and emb_path.exists():
            with meta_path.open(encoding="utf-8") as f:
                meta = json.load(f)
            cache_valid = (
                meta.get("model") == MODEL_NAME
                and meta.get("node_ids") == eligible_ids
                and meta.get("text_hashes") == text_hashes
            )
            if cache_valid:
                payload = torch.load(emb_path, map_location="cpu", weights_only=True)
                self._retrieval_node_ids = meta["node_ids"]
                self._retrieval_embeddings = payload["embeddings"].float()
                self._scatter_assessment_embeddings()
                return

        model = self._get_model()
        texts = [self.graph.nodes[node_id]["text"] for node_id in eligible_ids]
        embeddings = model.encode(
            texts,
            batch_size=16,
            convert_to_tensor=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).float()
        self._retrieval_node_ids = eligible_ids
        self._retrieval_embeddings = embeddings.cpu()
        self._scatter_assessment_embeddings()

        torch.save({"embeddings": self._retrieval_embeddings}, emb_path)
        with meta_path.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "model": MODEL_NAME,
                    "assessment_id": self.graph.assessment_id,
                    "node_ids": eligible_ids,
                    "text_hashes": text_hashes,
                },
                f,
                indent=2,
            )
            f.write("\n")

    def _scatter_assessment_embeddings(self) -> None:
        assert self._retrieval_embeddings is not None
        by_type: dict[str, list[tuple[int, torch.Tensor]]] = {}
        for retrieval_index, node_id in enumerate(self._retrieval_node_ids):
            node_type, pyg_index = self.graph.index[node_id]
            by_type.setdefault(node_type, []).append((pyg_index, self._retrieval_embeddings[retrieval_index]))

        for node_type in self.graph.data.node_types:
            if node_type == "response":
                continue
            store = self.graph.data[node_type]
            count = int(store.num_nodes)
            emb = torch.zeros(count, EMBED_DIM, dtype=torch.float)
            mask = torch.zeros(count, dtype=torch.bool)
            for pyg_index, vector in by_type.get(node_type, []):
                emb[pyg_index] = vector
                mask[pyg_index] = True
            store.emb = emb
            store.retrieval_mask = mask

    def _embed_and_save_response(self, response: dict) -> None:
        model = self._get_model()
        segment_ids = [segment["id"] for segment in response["segments"]]
        texts = [f"{QUERY_PREFIX}{segment['text']}" for segment in response["segments"]]
        embeddings = model.encode(
            texts,
            batch_size=16,
            convert_to_tensor=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).float().cpu()

        from app.assessment_paths import legacy_responses_dir, resolve_response_paths

        paths = resolve_response_paths(self.data_dir, response["assessment_id"], response["response_id"])
        torch.save({"segment_ids": segment_ids, "embeddings": embeddings}, paths.pt)

    def _load_response_segment_embedding(self, response_id: str, segment_id: str) -> torch.Tensor:
        from app.assessment_paths import resolve_response_paths
        from app.assessment_runtime import load_registered_response_embeddings, use_registry

        assessment_id = self.graph.assessment_id
        if use_registry(self.data_dir, assessment_id) and self._artifact_version:
            payload = load_registered_response_embeddings(
                self.data_dir, assessment_id, self._artifact_version, response_id
            )
            segment_ids = payload["segment_ids"]
            embeddings = payload["embeddings"].float()
            try:
                index = segment_ids.index(segment_id)
            except ValueError as exc:
                raise KeyError(segment_id) from exc
            return embeddings[index]

        paths = resolve_response_paths(self.data_dir, assessment_id, response_id)
        if not paths.pt.exists():
            response = load_response(
                response_id,
                responses_dir=self.data_dir / "responses",
                assessment_id=assessment_id,
            )
            self._embed_and_save_response(response)
        path = paths.pt

        payload = torch.load(path, map_location="cpu", weights_only=True)
        segment_ids = payload["segment_ids"]
        embeddings = payload["embeddings"].float()
        try:
            index = segment_ids.index(segment_id)
        except ValueError as exc:
            raise KeyError(segment_id) from exc
        return embeddings[index]

    def _get_model(self) -> SentenceTransformer:
        if self.model is None:
            device = _device()
            try:
                self.model = SentenceTransformer(MODEL_NAME, device=device)
            except Exception:
                self.model = SentenceTransformer(MODEL_NAME, device="cpu")
        return self.model
