from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from app.classifier import EvidenceRelationClassifier, JevEvidenceRelationClassifier, RelationDecision
from app.graph_service import GraphService
from app.responses import load_response, response_id_from_segment
from app.retrieval import CRITERIA_NODE_TYPES, RetrievalScope, RetrievalService

GUIDANCE_RELATIONS = frozenset({"ACCEPTS", "REJECTS", "CONSTRAINS", "CLARIFIES", "REQUIRES"})
MAX_GUIDANCE_ITEMS = 8
QUESTION_TEXT_LIMIT = 500


@dataclass
class EvidenceRef:
    evidence_id: str
    response_id: str
    text: str
    start_char: int | None = None
    end_char: int | None = None
    segment_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "response_id": self.response_id,
            "text": self.text,
            "start_char": self.start_char,
            "end_char": self.end_char,
            "segment_id": self.segment_id,
        }


def _criterion_summary(node: dict) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": node["id"],
        "node_type": node["node_type"],
        "text": node["text"],
    }
    if node.get("level") is not None:
        payload["level"] = node["level"]
    if node.get("marks") is not None:
        payload["marks"] = node["marks"]
    if node.get("mark_range") is not None:
        payload["mark_range"] = node["mark_range"]
    return payload


def _question_text(graph_service: GraphService) -> str | None:
    question_nodes = [
        node
        for node in graph_service.graph.nodes.values()
        if node["document_type"] == "question" and not node["structural_only"]
    ]
    question_nodes.sort(key=lambda node: node["order"])
    if not question_nodes:
        return None
    combined = " ".join(node["text"].strip() for node in question_nodes if node["text"].strip())
    if len(combined) > QUESTION_TEXT_LIMIT:
        return combined[: QUESTION_TEXT_LIMIT - 3] + "..."
    return combined


def _guidance_items(graph_service: GraphService, criterion_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for edge in graph_service.graph.in_edges.get(criterion_id, []):
        if edge["kind"] != "assessment" or edge["relation"] not in GUIDANCE_RELATIONS:
            continue
        neighbor = graph_service.graph.nodes[edge["source"]]
        items.append(
            {
                "relation": edge["relation"],
                "direction": "incoming",
                "node_id": neighbor["id"],
                "text": neighbor["text"],
            }
        )
    for edge in graph_service.graph.out_edges.get(criterion_id, []):
        if edge["kind"] != "assessment" or edge["relation"] not in GUIDANCE_RELATIONS:
            continue
        neighbor = graph_service.graph.nodes[edge["target"]]
        items.append(
            {
                "relation": edge["relation"],
                "direction": "outgoing",
                "node_id": neighbor["id"],
                "text": neighbor["text"],
            }
        )
    items.sort(key=lambda item: (item["relation"], item["node_id"]))
    return items[:MAX_GUIDANCE_ITEMS]


def _segment_summary(segment: dict) -> dict[str, Any]:
    return {
        "segment_id": segment["id"],
        "order": segment["order"],
        "text": segment["text"],
        "start_char": segment["start_char"],
        "end_char": segment["end_char"],
    }


def _containing_sentence(
    segment_text: str,
    *,
    span_start: int,
    span_end: int,
    segment_start: int,
) -> str:
    rel_start = max(0, span_start - segment_start)
    rel_end = min(len(segment_text), span_end - segment_start)

    sentence_start = 0
    for index in range(rel_start - 1, -1, -1):
        if segment_text[index] in ".!?" and (index + 1 >= len(segment_text) or segment_text[index + 1].isspace()):
            sentence_start = index + 1
            while sentence_start < len(segment_text) and segment_text[sentence_start].isspace():
                sentence_start += 1
            break

    sentence_end = len(segment_text)
    for index in range(max(rel_end - 1, 0), len(segment_text)):
        if segment_text[index] in ".!?":
            sentence_end = index + 1
            break

    return segment_text[sentence_start:sentence_end].strip()


def build_response_local_context_for_span(
    record: dict,
    *,
    start_char: int | None,
    end_char: int | None,
    segment_id: str | None = None,
) -> dict[str, Any]:
    segments = record.get("segments", [])
    index = None
    if segment_id:
        for position, segment in enumerate(segments):
            if segment["id"] == segment_id:
                index = position
                break
    elif start_char is not None:
        for position, segment in enumerate(segments):
            segment_start = segment["start_char"]
            segment_end = segment["end_char"]
            if segment_start <= start_char < segment_end:
                index = position
                break
            if end_char is not None and segment_start < end_char <= segment_end:
                index = position
                break

    containing = None
    containing_sentence = None
    preceding = None
    following = None
    if index is not None:
        segment = segments[index]
        containing = _segment_summary(segment)
        if start_char is not None and end_char is not None:
            containing_sentence = _containing_sentence(
                segment["text"],
                span_start=start_char,
                span_end=end_char,
                segment_start=segment["start_char"],
            )
        if index > 0:
            preceding = _segment_summary(segments[index - 1])
        if index + 1 < len(segments):
            following = _segment_summary(segments[index + 1])

    return {
        "containing_segment": containing,
        "containing_sentence": containing_sentence,
        "preceding_segment": preceding,
        "following_segment": following,
        "note": (
            "Containing and surrounding response text is context only. "
            "Use it to interpret the selected evidence, not as additional coded evidence."
        ),
    }


def _segment_index_for_evidence(segments: list[dict], evidence: EvidenceRef) -> int | None:
    if evidence.segment_id:
        for index, segment in enumerate(segments):
            if segment["id"] == evidence.segment_id:
                return index
        return None

    if evidence.start_char is None:
        return None

    for index, segment in enumerate(segments):
        start = segment["start_char"]
        end = segment["end_char"]
        if start <= evidence.start_char < end:
            return index
        if evidence.end_char is not None and start < evidence.end_char <= end:
            return index
    return None


def build_response_local_context(record: dict, evidence: EvidenceRef) -> dict[str, Any]:
    return build_response_local_context_for_span(
        record,
        start_char=evidence.start_char,
        end_char=evidence.end_char,
        segment_id=evidence.segment_id,
    )


def build_criterion_context(graph_service: GraphService, criterion_id: str) -> dict[str, Any]:
    node = graph_service.get_node(criterion_id)
    if node["node_type"] not in CRITERIA_NODE_TYPES:
        raise ValueError(f"Node is not a criterion: {criterion_id}")

    parent = graph_service._meaningful_parent(criterion_id)
    parent_payload = None
    if parent is not None and parent["node_type"] in CRITERIA_NODE_TYPES:
        parent_payload = _criterion_summary(parent)

    guidance = _guidance_items(graph_service, criterion_id)
    context_node_ids = [criterion_id]
    if parent_payload:
        context_node_ids.append(parent_payload["id"])
    context_node_ids.extend(item["node_id"] for item in guidance)

    return {
        "criterion": _criterion_summary(node),
        "parent_criterion": parent_payload,
        "guidance": guidance,
        "question": _question_text(graph_service),
        "context_node_ids": context_node_ids,
    }


def list_response_ids(responses_dir: Path, assessment_id: str | None = None) -> list[str]:
    if not responses_dir.is_dir():
        return []
    ids: list[str] = []
    for path in sorted(responses_dir.glob("*.json")):
        with path.open(encoding="utf-8") as f:
            record = json.load(f)
        if assessment_id is None or record.get("assessment_id") == assessment_id:
            ids.append(record["response_id"])
    return ids


def response_payload(response_id: str, responses_dir: Path) -> dict[str, Any]:
    record = load_response(response_id, responses_dir=responses_dir)
    return {
        "response_id": record["response_id"],
        "assessment_id": record["assessment_id"],
        "text": record["text"],
        "segments": [
            {
                "id": segment["id"],
                "order": segment["order"],
                "text": segment["text"],
                "start_char": segment["start_char"],
                "end_char": segment["end_char"],
            }
            for segment in record["segments"]
        ],
    }


class HypothesisStore:
    def __init__(self, hypotheses_dir: Path) -> None:
        self.hypotheses_dir = hypotheses_dir
        self.hypotheses_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, response_id: str) -> Path:
        return self.hypotheses_dir / f"{response_id}.json"

    def list(self, response_id: str) -> list[dict[str, Any]]:
        path = self._path(response_id)
        if not path.exists():
            return []
        with path.open(encoding="utf-8") as f:
            payload = json.load(f)
        return payload.get("hypotheses", [])

    def upsert(self, response_id: str, decision: RelationDecision) -> dict[str, Any]:
        path = self._path(response_id)
        if path.exists():
            with path.open(encoding="utf-8") as f:
                payload = json.load(f)
        else:
            payload = {"response_id": response_id, "hypotheses": []}

        record = decision.to_dict()
        hypotheses = payload.get("hypotheses", [])
        key = (record["evidence_id"], record["criterion_id"], record["classifier"])
        replaced = False
        for index, existing in enumerate(hypotheses):
            existing_key = (
                existing["evidence_id"],
                existing["criterion_id"],
                existing["classifier"],
            )
            if existing_key == key:
                hypotheses[index] = record
                replaced = True
                break
        if not replaced:
            hypotheses.append(record)

        payload["hypotheses"] = hypotheses
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        return record


class EvidencePipeline:
    def __init__(
        self,
        data_dir: str | Path = "data",
        assessment_id: str = "C-JUN25-8464C1H-02_3",
        classifier: EvidenceRelationClassifier | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.assessment_id = assessment_id
        self.responses_dir = self.data_dir / "responses"
        self.graph_service = GraphService.from_data_dir(
            data_dir=self.data_dir,
            assessment_id=assessment_id,
        )
        self.classifier = classifier or JevEvidenceRelationClassifier()
        self.hypothesis_store = HypothesisStore(self.data_dir / "hypotheses")
        self._retrieval_by_response: dict[str, RetrievalService] = {}
        self._shared_model = None

    def _retrieval_for_response(self, response_id: str) -> RetrievalService:
        if response_id not in self._retrieval_by_response:
            self._retrieval_by_response[response_id] = RetrievalService.from_data_dir(
                data_dir=self.data_dir,
                assessment_id=self.assessment_id,
                response_id=response_id,
                model=self._shared_model,
            )
            if self._shared_model is None:
                self._shared_model = self._retrieval_by_response[response_id].model
        return self._retrieval_by_response[response_id]

    def resolve_evidence(
        self,
        *,
        response_id: str,
        segment_id: str | None = None,
        start_char: int | None = None,
        end_char: int | None = None,
    ) -> EvidenceRef:
        record = load_response(response_id, responses_dir=self.responses_dir)

        if segment_id is not None:
            for segment in record["segments"]:
                if segment["id"] == segment_id:
                    return EvidenceRef(
                        evidence_id=segment_id,
                        response_id=response_id,
                        text=segment["text"],
                        start_char=segment["start_char"],
                        end_char=segment["end_char"],
                        segment_id=segment_id,
                    )
            raise KeyError(segment_id)

        if start_char is None or end_char is None:
            raise ValueError("Provide segment_id or both start_char and end_char")

        text = record["text"]
        if not (0 <= start_char <= end_char <= len(text)):
            raise ValueError("Invalid character span for response text")
        span_text = text[start_char:end_char]
        if not span_text.strip():
            raise ValueError("Evidence span is empty")

        return EvidenceRef(
            evidence_id=f"{response_id}:{start_char}-{end_char}",
            response_id=response_id,
            text=span_text,
            start_char=start_char,
            end_char=end_char,
        )

    def resolve_evidence_from_segment(self, segment_id: str) -> EvidenceRef:
        response_id = response_id_from_segment(segment_id)
        return self.resolve_evidence(response_id=response_id, segment_id=segment_id)

    def candidates(
        self,
        evidence: EvidenceRef,
        top_k: int = 5,
        scope: RetrievalScope = "criteria",
    ) -> dict[str, Any]:
        retrieval = self._retrieval_for_response(evidence.response_id)
        if evidence.segment_id:
            result = retrieval.similar(evidence.segment_id, top_k=top_k, scope=scope)
        else:
            result = retrieval.similar_text(
                evidence.text,
                top_k=top_k,
                scope=scope,
                evidence_id=evidence.evidence_id,
                start_char=evidence.start_char,
                end_char=evidence.end_char,
            )
        return {
            "evidence": evidence.to_dict(),
            "scope": scope,
            "retrieval": "candidate",
            "matches": result["matches"],
        }

    def classify(
        self,
        evidence: EvidenceRef,
        criterion_id: str,
        *,
        save: bool = False,
    ) -> dict[str, Any]:
        context = build_criterion_context(self.graph_service, criterion_id)
        context["evidence_id"] = evidence.evidence_id
        context["start_char"] = evidence.start_char
        context["end_char"] = evidence.end_char
        record = load_response(evidence.response_id, responses_dir=self.responses_dir)
        context["response_context"] = build_response_local_context(record, evidence)

        decision = self.classifier.classify(
            evidence.text,
            context["criterion"],
            context,
        )
        record = decision.to_dict()
        if save:
            self.hypothesis_store.upsert(evidence.response_id, decision)
        return record

    def classify_top(
        self,
        evidence: EvidenceRef,
        top_k: int = 3,
        scope: RetrievalScope = "criteria",
        *,
        save: bool = False,
    ) -> dict[str, Any]:
        candidate_result = self.candidates(evidence, top_k=top_k, scope=scope)
        classified = []
        for match in candidate_result["matches"]:
            decision = self.classify(evidence, match["node_id"], save=save)
            classified.append({"match": match, "decision": decision})
        return {
            "evidence": evidence.to_dict(),
            "scope": scope,
            "candidates": classified,
        }

    def criterion_context(self, criterion_id: str) -> dict[str, Any]:
        context = build_criterion_context(self.graph_service, criterion_id)
        return {
            "criterion_id": criterion_id,
            "classification_context": context,
            "graph_context": self.graph_service.get_context(criterion_id),
        }

    def list_hypotheses(self, response_id: str) -> dict[str, Any]:
        return {
            "response_id": response_id,
            "hypotheses": self.hypothesis_store.list(response_id),
        }

    def list_responses(self) -> dict[str, Any]:
        return {
            "assessment_id": self.assessment_id,
            "responses": list_response_ids(self.responses_dir, self.assessment_id),
        }

    def get_response(self, response_id: str) -> dict[str, Any]:
        return response_payload(response_id, self.responses_dir)

    def get_assessment(self) -> dict[str, Any]:
        return self.graph_service.assessment_overview()
