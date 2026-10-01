from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

import torch

from app.graph import AssessmentGraph, _add_adjacency

RESPONSE_NODE_TYPE = "response"
RESPONSE_ROOT_SEGMENT_TYPE = "response_root"
RESPONSE_SEGMENT_TYPE = "response_segment"

MIN_SEGMENT_CHARS = 12

SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
CLAUSE_SPLITS = (re.compile(r"\s+(?=and repeat the tests\b)", re.IGNORECASE),)


def response_id_from_path(path: str | Path) -> str:
    return Path(path).stem


def segment_id(response_id: str, order: int) -> str:
    return f"{response_id}-seg-{order}"


def _trim_span(text: str, start: int, end: int) -> tuple[int, int, str]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end, text[start:end]


def _merge_short_spans(text: str, spans: list[tuple[int, int]]) -> list[tuple[int, int, str]]:
    merged: list[tuple[int, int, str]] = []
    for start, end in spans:
        start, end, segment_text = _trim_span(text, start, end)
        if not segment_text:
            continue
        if merged and len(segment_text) < MIN_SEGMENT_CHARS:
            prev_start, prev_end, prev_text = merged[-1]
            combined_start, combined_end, combined_text = _trim_span(text, prev_start, end)
            merged[-1] = (combined_start, combined_end, combined_text)
        else:
            merged.append((start, end, segment_text))
    return merged


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for match in SENTENCE_END.finditer(text):
        end = match.start() + 1
        if end > start:
            spans.append((start, end))
        start = match.end()
    if start < len(text):
        spans.append((start, len(text)))
    return spans


def _refine_sentence_span(text: str, start: int, end: int) -> list[tuple[int, int]]:
    sentence = text[start:end]
    split_at: list[int] = [0, len(sentence)]
    for pattern in CLAUSE_SPLITS:
        for match in pattern.finditer(sentence):
            split_at.append(match.start())
    split_at = sorted(set(split_at))

    spans: list[tuple[int, int]] = []
    for i, rel_start in enumerate(split_at):
        rel_end = split_at[i + 1] if i + 1 < len(split_at) else len(sentence)
        if rel_end <= rel_start:
            continue
        spans.append((start + rel_start, start + rel_end))
    return spans or [(start, end)]


def segment_response_text(text: str) -> list[dict]:
    if not text:
        return []

    raw_spans: list[tuple[int, int]] = []
    for sent_start, sent_end in _sentence_spans(text):
        raw_spans.extend(_refine_sentence_span(text, sent_start, sent_end))

    segments: list[dict] = []
    for order, (start, end, segment_text) in enumerate(_merge_short_spans(text, raw_spans), start=1):
        segments.append(
            {
                "order": order,
                "text": segment_text,
                "start_char": start,
                "end_char": end,
            }
        )
    return segments


def ingest_response_file(
    txt_path: str | Path,
    assessment_id: str = "C-JUN25-8464C1H-02_3",
    responses_dir: str | Path = "data/responses",
) -> dict:
    txt_path = Path(txt_path)
    response_id = response_id_from_path(txt_path)
    text = txt_path.read_text(encoding="utf-8")
    raw_segments = segment_response_text(text)

    segments = [
        {
            "id": segment_id(response_id, segment["order"]),
            **segment,
        }
        for segment in raw_segments
    ]

    record = {
        "response_id": response_id,
        "assessment_id": assessment_id,
        "source_file": str(txt_path).replace("\\", "/"),
        "text": text,
        "segments": segments,
    }

    out_dir = Path(responses_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{response_id}.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
        f.write("\n")

    return record


def load_response(response_id: str, responses_dir: str | Path = "data/responses") -> dict:
    path = Path(responses_dir) / f"{response_id}.json"
    if not path.exists():
        raise KeyError(response_id)
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def response_id_from_segment(segment_id_value: str) -> str:
    marker = "-seg-"
    if marker not in segment_id_value:
        raise KeyError(segment_id_value)
    return segment_id_value.rsplit(marker, 1)[0]


def attach_response_to_graph(graph: AssessmentGraph, response: dict) -> None:
    if not isinstance(graph.out_edges, defaultdict):
        graph.out_edges = defaultdict(list, graph.out_edges)
        graph.in_edges = defaultdict(list, graph.in_edges)

    response_id = response["response_id"]
    assessment_id = response["assessment_id"]
    root_id = response_id

    root_record = {
        "id": root_id,
        "type": RESPONSE_ROOT_SEGMENT_TYPE,
        "text": response["text"],
        "order": 0,
        "parent_id": None,
        "node_type": RESPONSE_NODE_TYPE,
        "segment_type": RESPONSE_ROOT_SEGMENT_TYPE,
        "structural_only": True,
        "document_id": response_id,
        "document_type": "response",
        "response_id": response_id,
        "assessment_id": assessment_id,
        "start_char": None,
        "end_char": None,
    }
    graph.nodes[root_id] = root_record

    segment_records: list[dict] = []
    for segment in response["segments"]:
        record = {
            "id": segment["id"],
            "type": RESPONSE_SEGMENT_TYPE,
            "text": segment["text"],
            "order": segment["order"],
            "parent_id": root_id,
            "node_type": RESPONSE_NODE_TYPE,
            "segment_type": RESPONSE_SEGMENT_TYPE,
            "structural_only": False,
            "document_id": response_id,
            "document_type": "response",
            "response_id": response_id,
            "assessment_id": assessment_id,
            "start_char": segment["start_char"],
            "end_char": segment["end_char"],
        }
        graph.nodes[segment["id"]] = record
        segment_records.append(record)

    response_ids = [root_id] + [segment["id"] for segment in response["segments"]]
    _append_response_nodes(graph, response_ids)

    edge_records: list[dict] = []
    for segment in segment_records:
        edge = {
            "source": segment["id"],
            "target": root_id,
            "relation": "PART_OF",
            "kind": "structural",
            "document_id": response_id,
        }
        edge_records.append(edge)
        _add_adjacency(graph.out_edges, graph.in_edges, edge)

    segment_records.sort(key=lambda item: item["order"])
    for i, segment in enumerate(segment_records):
        if i + 1 >= len(segment_records):
            break
        next_segment = segment_records[i + 1]
        edge = {
            "source": segment["id"],
            "target": next_segment["id"],
            "relation": "NEXT",
            "kind": "structural",
            "document_id": response_id,
            "parent_id": root_id,
            "source_order": segment["order"],
            "target_order": next_segment["order"],
        }
        edge_records.append(edge)
        _add_adjacency(graph.out_edges, graph.in_edges, edge)

    _append_response_edges(graph, edge_records)
    graph.edge_count += len(edge_records)


def _append_response_nodes(graph: AssessmentGraph, response_ids: list[str]) -> None:
    store = graph.data[RESPONSE_NODE_TYPE]
    existing_ids = list(getattr(store, "node_id", []))
    start_index = len(existing_ids)
    all_ids = existing_ids + response_ids

    store.num_nodes = len(all_ids)
    store.node_id = all_ids
    store.segment_type = [graph.nodes[node_id]["segment_type"] for node_id in all_ids]
    store.structural_only = torch.tensor(
        [graph.nodes[node_id]["structural_only"] for node_id in all_ids],
        dtype=torch.bool,
    )
    store.level = torch.tensor([-1 for _ in all_ids], dtype=torch.long)

    embed_dim = int(getattr(store, "emb", torch.zeros(0, 1024)).size(-1) or 1024)
    existing_emb = getattr(store, "emb", None)
    existing_mask = getattr(store, "retrieval_mask", None)
    if existing_emb is None:
        store.emb = torch.zeros(len(all_ids), embed_dim, dtype=torch.float)
        store.retrieval_mask = torch.zeros(len(all_ids), dtype=torch.bool)
    else:
        padded = torch.zeros(len(all_ids), embed_dim, dtype=torch.float)
        padded[: existing_emb.size(0)] = existing_emb
        mask = torch.zeros(len(all_ids), dtype=torch.bool)
        if existing_mask is not None:
            mask[: existing_mask.size(0)] = existing_mask
        store.emb = padded
        store.retrieval_mask = mask

    for offset, node_id in enumerate(response_ids):
        graph.index[node_id] = (RESPONSE_NODE_TYPE, start_index + offset)


def _append_response_edges(graph: AssessmentGraph, edge_records: list[dict]) -> None:
    grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for edge in edge_records:
        src_type = graph.nodes[edge["source"]]["node_type"]
        dst_type = graph.nodes[edge["target"]]["node_type"]
        grouped[(src_type, edge["relation"], dst_type)].append(edge)

    for (src_type, relation, dst_type), edges in grouped.items():
        key = (src_type, relation, dst_type)
        existing = graph.data[key].edge_index if key in graph.data.edge_types else None
        src_indices = [graph.index[e["source"]][1] for e in edges]
        dst_indices = [graph.index[e["target"]][1] for e in edges]
        new_index = torch.tensor([src_indices, dst_indices], dtype=torch.long)
        if existing is not None and existing.numel() > 0:
            new_index = torch.cat([existing, new_index], dim=1)
        graph.data[key].edge_index = new_index
