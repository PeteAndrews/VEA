from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import torch

from app.pyg_import import hetero_data_class

HeteroData = hetero_data_class()

JEV_LABELS: tuple[str, ...] = (
    "ACCEPTS",
    "APPLIES_TO",
    "CLARIFIES",
    "CONSTRAINS",
    "EXEMPLIFIES",
    "EXTENDS",
    "NONE",
    "REFERS_TO",
    "REJECTS",
    "REQUIRES",
)

QUESTION_TYPES = {
    "stimulus",
    "question_instruction",
    "question_text",
    "subquestion",
    "other_question_content",
}
LEVEL_TYPES = {"level_descriptor"}
LEVEL_RULE_TYPES = {"level_rule"}
MARK_POINT_TYPES = {
    "indicative_content_group",
    "indicative_point",
    "mark_point",
    "answer_detail",
}
EXTRA_INFO_TYPES = {
    "extra_information",
    "general_guidance",
    "other_mark_scheme_content",
}
COMMENTARY_TYPES = {
    "commentary_text",
    "commentary_heading",
    "commentary_example",
    "commentary_guidance",
    "other_commentary_content",
}

DOCUMENT_FALLBACK = {
    "question": "question",
    "mark_scheme": "mark_point",
    "commentary": "commentary",
}

STRUCTURAL_ONLY_SEGMENT_TYPES = {
    "indicative_content_group",
    "commentary_heading",
    "other_question_content",
    "other_mark_scheme_content",
    "other_commentary_content",
}


def is_structural_only(segment_type: str) -> bool:
    return segment_type in STRUCTURAL_ONLY_SEGMENT_TYPES


def segment_to_node_type(segment_type: str, document_type: str) -> str:
    if segment_type in QUESTION_TYPES:
        return "question"
    if segment_type in LEVEL_TYPES:
        return "level"
    if segment_type in LEVEL_RULE_TYPES:
        return "level_rule"
    if segment_type in MARK_POINT_TYPES:
        return "mark_point"
    if segment_type in EXTRA_INFO_TYPES:
        return "extra_info"
    if segment_type in COMMENTARY_TYPES:
        return "commentary"
    return DOCUMENT_FALLBACK.get(document_type, "question")


@dataclass
class AssessmentGraph:
    data: HeteroData
    assessment_id: str
    nodes: dict[str, dict]
    index: dict[str, tuple[str, int]]
    out_edges: dict[str, list[dict]]
    in_edges: dict[str, list[dict]]
    jev_labels: tuple[str, ...]
    edge_count: int


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _jev_probs_vector(probabilities: dict[str, float] | None) -> list[float]:
    if not probabilities:
        return [float("nan")] * len(JEV_LABELS)
    return [float(probabilities.get(label, 0.0)) for label in JEV_LABELS]


def _add_adjacency(
    out_edges: dict[str, list[dict]],
    in_edges: dict[str, list[dict]],
    edge: dict,
) -> None:
    out_edges[edge["source"]].append(edge)
    in_edges[edge["target"]].append(edge)


def _questions_dir(data_dir: Path) -> Path:
    sub = data_dir / "questions"
    return sub if sub.is_dir() else data_dir


def load_graph(
    data_dir: str | Path = "data",
    assessment_id: str = "C-JUN25-8464C1H-02_3",
) -> AssessmentGraph:
    data_dir = Path(data_dir)
    questions_dir = _questions_dir(data_dir)
    stage1 = _load_json(questions_dir / f"{assessment_id}.json")
    stage2 = _load_json(questions_dir / f"{assessment_id}-relationships.json")
    jev = _load_json(questions_dir / f"{assessment_id}-jev-verification.json")

    jev_lookup = {
        (v["source_id"], v["target_id"], v["llm_relation"]): v
        for v in jev["verifications"]
    }

    nodes: dict[str, dict] = {}
    index: dict[str, tuple[str, int]] = {}
    by_type: dict[str, list[str]] = defaultdict(list)
    segments_by_doc: dict[str, list[dict]] = defaultdict(list)

    for document in stage1["documents"]:
        doc_id = document["document_id"]
        doc_type = document["document_type"]
        for segment in document["segments"]:
            node_id = segment["id"]
            node_type = segment_to_node_type(segment["type"], doc_type)
            record = {
                **segment,
                "node_type": node_type,
                "segment_type": segment["type"],
                "structural_only": is_structural_only(segment["type"]),
                "document_id": doc_id,
                "document_type": doc_type,
            }
            nodes[node_id] = record
            by_type[node_type].append(node_id)
            segments_by_doc[doc_id].append(record)

    for node_type, ids in by_type.items():
        for pyg_index, node_id in enumerate(ids):
            index[node_id] = (node_type, pyg_index)

    out_edges: dict[str, list[dict]] = defaultdict(list)
    in_edges: dict[str, list[dict]] = defaultdict(list)
    edge_records: list[dict] = []

    for doc_id, doc_segments in segments_by_doc.items():
        groups: dict[str | None, list[dict]] = defaultdict(list)
        for segment in doc_segments:
            groups[segment.get("parent_id")].append(segment)

        for parent_id, siblings in groups.items():
            siblings.sort(key=lambda s: s["order"])
            for i, segment in enumerate(siblings):
                node_id = segment["id"]
                if parent_id is not None and parent_id in nodes:
                    edge = {
                        "source": node_id,
                        "target": parent_id,
                        "relation": "PART_OF",
                        "kind": "structural",
                        "document_id": doc_id,
                    }
                    edge_records.append(edge)
                    _add_adjacency(out_edges, in_edges, edge)

                if i + 1 < len(siblings):
                    next_segment = siblings[i + 1]
                    edge = {
                        "source": node_id,
                        "target": next_segment["id"],
                        "relation": "NEXT",
                        "kind": "structural",
                        "document_id": doc_id,
                        "parent_id": parent_id,
                        "source_order": segment["order"],
                        "target_order": next_segment["order"],
                    }
                    edge_records.append(edge)
                    _add_adjacency(out_edges, in_edges, edge)

    for rel in stage2["relationships"]:
        source_id = rel["source_id"]
        target_id = rel["target_id"]
        relation = rel["relation"]
        if source_id not in index or target_id not in index:
            continue

        verification = jev_lookup.get((source_id, target_id, relation))
        edge = {
            "source": source_id,
            "target": target_id,
            "relation": relation,
            "kind": "assessment",
            "llm_confidence": rel.get("confidence"),
            "llm_rationale": rel.get("rationale"),
            "llm_provenance": rel.get("provenance"),
            "jev_relation": verification["jev_relation"] if verification else None,
            "jev_probability": verification["jev_probability"] if verification else None,
            "jev_confidence": verification["jev_confidence"] if verification else None,
            "jev_probabilities": verification["jev_probabilities"] if verification else None,
            "agreement": verification["agreement"] if verification else None,
            "needs_review": verification["needs_review"] if verification else None,
        }
        edge_records.append(edge)
        _add_adjacency(out_edges, in_edges, edge)

    data = HeteroData()
    data.assessment_id = assessment_id
    data.jev_labels = list(JEV_LABELS)

    for node_type, ids in by_type.items():
        store = data[node_type]
        store.num_nodes = len(ids)
        store.node_id = ids
        store.segment_type = [nodes[node_id]["segment_type"] for node_id in ids]
        store.structural_only = torch.tensor(
            [nodes[node_id]["structural_only"] for node_id in ids],
            dtype=torch.bool,
        )
        store.level = torch.tensor(
            [nodes[node_id].get("level") if nodes[node_id].get("level") is not None else -1 for node_id in ids],
            dtype=torch.long,
        )

    grouped_edges: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for edge in edge_records:
        src_type = nodes[edge["source"]]["node_type"]
        dst_type = nodes[edge["target"]]["node_type"]
        grouped_edges[(src_type, edge["relation"], dst_type)].append(edge)

    for (src_type, relation, dst_type), edges in grouped_edges.items():
        src_indices = [index[e["source"]][1] for e in edges]
        dst_indices = [index[e["target"]][1] for e in edges]
        store = data[src_type, relation, dst_type]
        store.edge_index = torch.tensor([src_indices, dst_indices], dtype=torch.long)

        if edges[0]["kind"] == "assessment":
            store.llm_confidence = torch.tensor(
                [e.get("llm_confidence") or float("nan") for e in edges],
                dtype=torch.float,
            )
            store.jev_probability = torch.tensor(
                [e.get("jev_probability") if e.get("jev_probability") is not None else float("nan") for e in edges],
                dtype=torch.float,
            )
            store.jev_confidence = torch.tensor(
                [e.get("jev_confidence") if e.get("jev_confidence") is not None else float("nan") for e in edges],
                dtype=torch.float,
            )
            store.jev_probs = torch.tensor(
                [_jev_probs_vector(e.get("jev_probabilities")) for e in edges],
                dtype=torch.float,
            )
            store.agreement = torch.tensor(
                [
                    1.0 if e.get("agreement") is True else 0.0 if e.get("agreement") is False else float("nan")
                    for e in edges
                ],
                dtype=torch.float,
            )
            store.needs_review = torch.tensor(
                [
                    1.0 if e.get("needs_review") is True else 0.0 if e.get("needs_review") is False else float("nan")
                    for e in edges
                ],
                dtype=torch.float,
            )

    return AssessmentGraph(
        data=data,
        assessment_id=assessment_id,
        nodes=nodes,
        index=index,
        out_edges=dict(out_edges),
        in_edges=dict(in_edges),
        jev_labels=JEV_LABELS,
        edge_count=len(edge_records),
    )
