from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from app.graph import _questions_dir
from app.graph_service import GraphService
from app.responses import load_response

CANDIDATE_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
LEVEL_PREFIX = re.compile(r"^Level\s+\d+:\s*", re.IGNORECASE)
BULLET_PREFIX = re.compile(r"^[•\u2022o]\s*", re.IGNORECASE)


def list_assessment_ids(data_dir: str | Path = "data") -> list[str]:
    questions_dir = _questions_dir(Path(data_dir))
    ids: list[str] = []
    for path in sorted(questions_dir.glob("*.json")):
        name = path.name
        if name.endswith("-relationships.json") or name.endswith("-jev-verification.json"):
            continue
        ids.append(path.stem)
    return ids


def load_stage1(data_dir: str | Path, assessment_id: str) -> dict[str, Any]:
    path = _questions_dir(Path(data_dir)) / f"{assessment_id}.json"
    if not path.is_file():
        raise KeyError(assessment_id)
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_errata(data_dir: str | Path, assessment_id: str) -> list[dict[str, Any]]:
    path = Path(data_dir) / "errata" / f"{assessment_id}.json"
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as f:
        payload = json.load(f)
    return list(payload.get("errata", []))


def question_label_from_id(question_id: str) -> str:
    return f"Q{question_id.replace('_', '.')}"


def source_label(response_id: str) -> str:
    marker = "_response-"
    if marker in response_id:
        return response_id.rsplit(marker, 1)[1]
    return response_id


def candidate_aliases(response_ids: list[str]) -> dict[str, str]:
    ordered = sorted(response_ids, key=lambda rid: hashlib.sha256(rid.encode("utf-8")).hexdigest())
    if len(ordered) > len(CANDIDATE_LETTERS):
        raise ValueError("Too many candidates for single-letter aliases")
    return {response_id: CANDIDATE_LETTERS[index] for index, response_id in enumerate(ordered)}


def reverse_aliases(aliases: dict[str, str]) -> dict[str, str]:
    return {candidate_id: response_id for response_id, candidate_id in aliases.items()}


def word_count(text: str) -> int:
    if not text.strip():
        return 0
    return len(text.split())


def _strip_display_text(text: str) -> str:
    return BULLET_PREFIX.sub("", text.strip())


def _strip_level_text(text: str) -> str:
    cleaned = LEVEL_PREFIX.sub("", text.strip())
    if cleaned.startswith("Mark:"):
        cleaned = cleaned.split("Mark:", 1)[0].strip()
    return cleaned


def _split_alternatives(text: str) -> tuple[str, list[str]]:
    parts = re.split(r"\s+or\s+", text, flags=re.IGNORECASE)
    primary = _strip_display_text(parts[0])
    alternatives = [_strip_display_text(part) for part in parts[1:] if part.strip()]
    return primary, alternatives


def _children(graph_service: GraphService, parent_id: str) -> list[dict]:
    children = [
        graph_service.graph.nodes[node_id]
        for node_id, node in graph_service.graph.nodes.items()
        if node.get("parent_id") == parent_id
    ]
    children.sort(key=lambda node: node["order"])
    return children


def _control_variable_steps(graph_service: GraphService) -> set[str]:
    steps: set[str] = set()
    for node_id, node in graph_service.graph.nodes.items():
        if node["node_type"] != "level_rule":
            continue
        for edge in graph_service.graph.out_edges.get(node_id, []):
            if edge["kind"] == "assessment" and edge["relation"] == "REQUIRES":
                steps.add(edge["target"])
    return steps


def _level_rules_for_level(graph_service: GraphService, level: int) -> list[str]:
    rules: list[str] = []
    for _node_id, node in graph_service.graph.nodes.items():
        if node["node_type"] == "level_rule" and node.get("level") == level:
            rules.append(node["text"].strip())
    return rules


def _apply_erratum(
    node: dict,
    errata: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    mark_range = node.get("mark_range")
    mark_range_source = None
    provenance = None

    for item in errata:
        if item.get("node_id") != node["id"] or item.get("field") != "mark_range":
            continue
        current = node.get("mark_range")
        if current != item.get("source_value"):
            warnings.append(
                {
                    "errata_id": item["id"],
                    "node_id": node["id"],
                    "reason": "source_value mismatch; erratum skipped",
                    "expected": item.get("source_value"),
                    "actual": current,
                }
            )
            continue
        mark_range = item["corrected_value"]
        mark_range_source = item["source_value"]
        provenance = {
            "errata_id": item["id"],
            "reason": item.get("reason"),
            "verified_by": item.get("verified_by"),
            "verified_on": item.get("verified_on"),
        }
        break

    return mark_range, mark_range_source, provenance


def _find_source_level_zero(graph_service: GraphService) -> dict | None:
    for _node_id, node in graph_service.graph.nodes.items():
        if node["node_type"] != "level":
            continue
        text = node.get("text", "").strip()
        mark_range = node.get("mark_range") or {}
        if node.get("level") == 0:
            return node
        if mark_range.get("min") == 0 and mark_range.get("max") == 0:
            return node
        if text.lower().startswith("no relevant content"):
            return node
    return None


def assessment_summary(
    graph_service: GraphService,
    data_dir: str | Path,
    response_ids: list[str],
) -> dict[str, Any]:
    stage1 = load_stage1(data_dir, graph_service.graph.assessment_id)
    metadata = stage1.get("metadata", {})
    question_id = stage1.get("question_id", "")
    return {
        "assessment_id": graph_service.graph.assessment_id,
        "question_id": question_id,
        "question_label": question_label_from_id(question_id),
        "max_mark": metadata.get("maximum_mark"),
        "marking_mode": metadata.get("marking_mode"),
        "candidate_count": len(response_ids),
    }


def question_view(graph_service: GraphService, data_dir: str | Path) -> dict[str, Any]:
    stage1 = load_stage1(data_dir, graph_service.graph.assessment_id)
    metadata = stage1.get("metadata", {})
    question_id = stage1.get("question_id", "")

    stimulus: list[tuple[int, str]] = []
    instructions: list[tuple[int, str]] = []
    subparts: list[tuple[int, str]] = []
    marks_text = None

    for node in graph_service.graph.nodes.values():
        if node["document_type"] != "question" or node["structural_only"]:
            continue
        text = node["text"].strip()
        order = node.get("order") or 0
        if node["segment_type"] in {"stimulus", "question_text"}:
            stimulus.append((order, text))
        elif node["segment_type"] == "question_instruction":
            instructions.append((order, text))
        elif node["segment_type"] == "subquestion":
            subparts.append((order, text))
        elif node["segment_type"] == "other_question_content":
            marks_text = text

    if marks_text is None and metadata.get("maximum_mark") is not None:
        marks_text = f"[{metadata['maximum_mark']} marks]"

    return {
        "assessment_id": graph_service.graph.assessment_id,
        "question_label": question_label_from_id(question_id),
        "max_mark": metadata.get("maximum_mark"),
        "stimulus": [text for _, text in sorted(stimulus)],
        "instructions": [text for _, text in sorted(instructions)],
        "subparts": [text for _, text in sorted(subparts)],
        "marks_text": marks_text,
    }


def levels_view(
    graph_service: GraphService,
    data_dir: str | Path,
) -> dict[str, Any]:
    errata = load_errata(data_dir, graph_service.graph.assessment_id)
    warnings: list[dict[str, Any]] = []
    levels: list[dict[str, Any]] = []

    level_nodes = [
        node
        for node in graph_service.graph.nodes.values()
        if node["node_type"] == "level" and node.get("level") is not None and node.get("level") > 0
    ]
    level_nodes.sort(key=lambda node: node["level"], reverse=True)

    for node in level_nodes:
        mark_range, mark_range_source, provenance = _apply_erratum(node, errata, warnings)
        entry: dict[str, Any] = {
            "id": node["id"],
            "level": node["level"],
            "label": f"Level {node['level']}",
            "mark_range": mark_range,
            "text": _strip_level_text(node["text"]),
            "rules": _level_rules_for_level(graph_service, node["level"]),
            "source": "mark_scheme",
            "provenance": provenance,
        }
        if mark_range_source is not None:
            entry["mark_range_source"] = mark_range_source
        levels.append(entry)

    zero_node = _find_source_level_zero(graph_service)
    if zero_node is not None:
        levels.append(
            {
                "id": zero_node["id"],
                "level": 0,
                "label": "No relevant content",
                "mark_range": zero_node.get("mark_range") or {"min": 0, "max": 0},
                "text": _strip_level_text(zero_node["text"]),
                "rules": [],
                "source": "mark_scheme",
                "provenance": None,
            }
        )
    else:
        levels.append(
            {
                "id": None,
                "level": 0,
                "label": "No relevant content",
                "mark_range": {"min": 0, "max": 0},
                "text": "No relevant content.",
                "rules": [],
                "source": "fallback",
                "provenance": {
                    "note": "Not present in source mark scheme; synthesized for display"
                },
            }
        )

    return {"levels": levels, "errata_warnings": warnings}


_DETAIL_SEGMENT_TYPES = {"indicative_point", "answer_detail"}


def _detail_rows(graph_service: GraphService, point_id: str) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for detail in _children(graph_service, point_id):
        if detail["segment_type"] not in _DETAIL_SEGMENT_TYPES:
            continue
        details.append(
            {
                "id": detail["id"],
                "text": _strip_display_text(detail["text"]),
            }
        )
    return details


def _key_steps_for_group(graph_service: GraphService, group_id: str, control_steps: set[str]) -> list[dict[str, Any]]:
    key_steps: list[dict[str, Any]] = []
    for child in _children(graph_service, group_id):
        if child["segment_type"] != "indicative_point":
            continue
        if child.get("parent_id") != group_id:
            continue

        primary, alternatives = _split_alternatives(child["text"])
        key_steps.append(
            {
                "id": child["id"],
                "text": primary,
                "alternatives": alternatives,
                "is_control_variable": child["id"] in control_steps,
                "details": _detail_rows(graph_service, child["id"]),
            }
        )
    return key_steps


def indicative_content_view(graph_service: GraphService) -> dict[str, Any]:
    control_steps = _control_variable_steps(graph_service)
    groups: list[dict[str, Any]] = []

    group_nodes = [
        (node_id, node)
        for node_id, node in graph_service.graph.nodes.items()
        if node["segment_type"] == "indicative_content_group"
    ]
    group_nodes.sort(key=lambda item: item[1]["order"])

    for node_id, node in group_nodes:
        groups.append(
            {
                "id": node_id,
                "text": node["text"].strip(),
                "key_steps": _key_steps_for_group(graph_service, node_id, control_steps),
            }
        )

    return {"groups": groups}


def candidate_view(
    record: dict[str, Any],
    candidate_id: str,
    *,
    include_dev: bool = False,
) -> dict[str, Any]:
    text = record["text"]
    segments = []
    segment_map: dict[str, str] = {}

    for segment in record["segments"]:
        display_id = f"{candidate_id}-seg-{segment['order']}"
        segment_map[display_id] = segment["id"]
        segments.append(
            {
                "id": display_id,
                "order": segment["order"],
                "start_char": segment["start_char"],
                "end_char": segment["end_char"],
                "text": segment["text"],
            }
        )

    payload: dict[str, Any] = {
        "assessment_id": record["assessment_id"],
        "candidate_id": candidate_id,
        "candidate_label": f"Candidate {candidate_id}",
        "candidate_number": None,
        "script": None,
        "variant": None,
        "word_count": word_count(text),
        "segment_count": len(segments),
        "text": text,
        "segments": segments,
    }

    if include_dev:
        payload["dev"] = {
            "response_id": record["response_id"],
            "source_label": source_label(record["response_id"]),
            "segment_map": segment_map,
        }

    return payload


def _list_response_ids_for_assessment(responses_dir: Path, assessment_id: str) -> list[str]:
    from app.assessment_paths import legacy_responses_dir
    from app.assessment_runtime import get_version_record, use_registry

    data_dir = responses_dir.parent
    if use_registry(data_dir, assessment_id):
        version = get_version_record(data_dir, assessment_id)
        return [item["response_id"] for item in version.get("responses", [])]

    nested_dir = legacy_responses_dir(data_dir, assessment_id)
    if nested_dir.is_dir():
        return sorted(path.stem for path in nested_dir.glob("*.json"))

    if not responses_dir.is_dir():
        return []
    ids: list[str] = []
    for path in sorted(responses_dir.glob("*.json")):
        with path.open(encoding="utf-8") as f:
            record = json.load(f)
        if record.get("assessment_id") == assessment_id:
            ids.append(record["response_id"])
    return ids


def _candidate_aliases_for_assessment(data_dir: str | Path, assessment_id: str, response_ids: list[str]) -> dict[str, str]:
    from app.assessment_runtime import get_version_record, use_registry

    if use_registry():
        try:
            version = get_version_record(data_dir, assessment_id)
            return {
                item["response_id"]: item["candidate_id"]
                for item in version.get("responses", [])
            }
        except KeyError:
            pass
    return candidate_aliases(response_ids)


def candidates_list_view(data_dir: str | Path, assessment_id: str) -> list[dict[str, Any]]:
    responses_dir = Path(data_dir) / "responses"
    response_ids = _list_response_ids_for_assessment(responses_dir, assessment_id)
    aliases = _candidate_aliases_for_assessment(data_dir, assessment_id, response_ids)
    items: list[dict[str, Any]] = []
    artifact_version = _artifact_version_for_assessment(data_dir, assessment_id)
    for response_id in response_ids:
        record = load_response(
            response_id,
            responses_dir=responses_dir,
            assessment_id=assessment_id,
            artifact_version=artifact_version,
        )
        candidate_id = aliases[response_id]
        items.append(
            {
                "candidate_id": candidate_id,
                "candidate_label": f"Candidate {candidate_id}",
                "word_count": word_count(record["text"]),
            }
        )
    items.sort(key=lambda item: item["candidate_id"])
    return items


def candidate_detail_view(
    data_dir: str | Path,
    assessment_id: str,
    candidate_id: str,
    *,
    include_dev: bool = False,
) -> dict[str, Any]:
    responses_dir = Path(data_dir) / "responses"
    response_ids = _list_response_ids_for_assessment(responses_dir, assessment_id)
    aliases = _candidate_aliases_for_assessment(data_dir, assessment_id, response_ids)
    reverse = reverse_aliases(aliases)
    if candidate_id not in reverse:
        raise KeyError(candidate_id)
    artifact_version = _artifact_version_for_assessment(data_dir, assessment_id)
    record = load_response(
        reverse[candidate_id],
        responses_dir=responses_dir,
        assessment_id=assessment_id,
        artifact_version=artifact_version,
    )
    return candidate_view(record, candidate_id, include_dev=include_dev)


def _artifact_version_for_assessment(data_dir: str | Path, assessment_id: str) -> str | None:
    from app.assessment_runtime import get_version_record, use_registry

    if not use_registry(data_dir, assessment_id):
        return None
    return get_version_record(data_dir, assessment_id)["artifact_version"]


def resolve_response_id(
    data_dir: str | Path,
    assessment_id: str,
    candidate_id: str,
) -> str:
    responses_dir = Path(data_dir) / "responses"
    response_ids = _list_response_ids_for_assessment(responses_dir, assessment_id)
    aliases = _candidate_aliases_for_assessment(data_dir, assessment_id, response_ids)
    reverse = reverse_aliases(aliases)
    if candidate_id not in reverse:
        raise KeyError(candidate_id)
    return reverse[candidate_id]


def dev_responses_list(data_dir: str | Path, assessment_id: str) -> list[dict[str, Any]]:
    responses_dir = Path(data_dir) / "responses"
    response_ids = _list_response_ids_for_assessment(responses_dir, assessment_id)
    aliases = _candidate_aliases_for_assessment(data_dir, assessment_id, response_ids)
    return [
        {
            "response_id": response_id,
            "candidate_id": aliases[response_id],
            "source_label": source_label(response_id),
        }
        for response_id in response_ids
    ]
