"""Build context for tentative-level AI checking."""

from __future__ import annotations

from typing import Any

from app.graph_service import GraphService
from app.interpretation_store import active_interpretations, judgement_fingerprint
from app.intervention import _question_text
from app.judgement import _criterion_display, level_context_view
from app.views import _strip_display_text, levels_view

LEVEL_GUIDANCE_RELATIONS = frozenset({"CONSTRAINS", "CLARIFIES", "REJECTS", "APPLIES_TO"})
SNIPPET_LENGTH = 160


def _snippet(text: str, limit: int = SNIPPET_LENGTH) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def build_rule_coverage(level_context: dict[str, Any]) -> list[dict[str, Any]]:
    coverage: list[dict[str, Any]] = []
    for item in level_context.get("required_criteria", []):
        coding_ids = list(item.get("coding_ids") or [])
        coverage.append(
            {
                "criterion_id": item["criterion_id"],
                "criterion_text": item["criterion_text"],
                "rule_id": item.get("rule_id"),
                "rule_text": item.get("rule_text"),
                "satisfied": len(coding_ids) > 0,
                "coding_ids": coding_ids,
            }
        )
    return coverage


def gather_level_guidance(graph_service: GraphService, level_node_id: str | None) -> list[dict[str, Any]]:
    if not level_node_id:
        return []
    items: list[dict[str, Any]] = []
    for edge in graph_service.graph.in_edges.get(level_node_id, []):
        if edge["kind"] != "assessment" or edge["relation"] not in LEVEL_GUIDANCE_RELATIONS:
            continue
        source = graph_service.graph.nodes[edge["source"]]
        items.append(
            {
                "node_id": source["id"],
                "text": source["text"].strip(),
            }
        )
    return items


def build_key_guidance(
    level_context: dict[str, Any],
    rule_coverage: list[dict[str, Any]],
    level_guidance: list[dict[str, Any]],
) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for rule in level_context.get("rules", []):
        cleaned = " ".join(str(rule).split())
        if cleaned and cleaned not in seen:
            parts.append(cleaned)
            seen.add(cleaned)
    for item in rule_coverage:
        if not item.get("satisfied"):
            line = f"This level requires linked evidence for: {item['criterion_text']}"
            if line not in seen:
                parts.append(line)
                seen.add(line)
    for item in level_guidance:
        cleaned = " ".join(item["text"].split())
        if cleaned and cleaned not in seen:
            parts.append(cleaned)
            seen.add(cleaned)
    return " ".join(parts[:6])


def gather_coded_support(
    judgement_state: dict[str, Any],
    evidence_interpretations: list[dict[str, Any]],
    graph_service: GraphService,
) -> list[dict[str, Any]]:
    spans = {span["id"]: span for span in judgement_state.get("evidence_spans", [])}
    interpretation_by_coding = {item["coding_id"]: item for item in evidence_interpretations}

    support: list[dict[str, Any]] = []
    for relation in judgement_state.get("relations", []):
        span = spans.get(relation["source"])
        if span is None:
            continue
        interpretation = interpretation_by_coding.get(relation["id"])
        jev = interpretation.get("jev_direct") or interpretation.get("jev") if interpretation else None
        display = _criterion_display(graph_service, relation["target"])
        support.append(
            {
                "coding_id": relation["id"],
                "criterion_id": relation["target"],
                "criterion_text": display["criterion_text"],
                "parent_criterion_id": display.get("parent_key_step_id"),
                "parent_criterion_text": display.get("parent_key_step_text"),
                "examiner_relation": relation["relation"],
                "start_char": span["start_char"],
                "end_char": span["end_char"],
                "text": span["text"],
                "jev_relation": jev.get("relation") if jev else None,
            }
        )
    return support


def summarize_coded_evidence(coded_support: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse to criterion-level summaries; hide parent when a child is also coded."""
    by_criterion: dict[str, list[dict[str, Any]]] = {}
    for item in coded_support:
        by_criterion.setdefault(item["criterion_id"], []).append(item)

    parents_with_coded_children: set[str] = set()
    for criterion_id, items in by_criterion.items():
        parent_id = items[0].get("parent_criterion_id")
        if parent_id and parent_id in by_criterion and parent_id != criterion_id:
            parents_with_coded_children.add(parent_id)

    summaries: list[dict[str, Any]] = []
    for criterion_id in sorted(by_criterion):
        if criterion_id in parents_with_coded_children:
            continue
        items = by_criterion[criterion_id]
        summaries.append(
            {
                "criterion_id": criterion_id,
                "label": items[0]["criterion_text"],
                "spans": [
                    {"coding_id": item["coding_id"], "text": item["text"]}
                    for item in items
                ],
            }
        )
    return summaries


def build_level_judgement_context(
    *,
    graph_service: GraphService,
    record: dict[str, Any],
    judgement_state: dict[str, Any],
    ai_payload: dict[str, Any],
    data_dir: str,
    stage: str,
    stage_source: str,
) -> dict[str, Any]:
    tentative = judgement_state.get("tentative_level")
    if tentative is None:
        raise ValueError("Tentative level is required for level checking.")

    level_context = level_context_view(
        graph_service,
        data_dir,
        tentative["level"],
        state=judgement_state,
    )
    all_levels_payload = levels_view(graph_service, data_dir)
    all_level_descriptors = [
        {
            "level": entry["level"],
            "label": entry["label"],
            "mark_range": entry.get("mark_range"),
            "text": entry.get("text"),
            "rules": entry.get("rules", []),
        }
        for entry in all_levels_payload["levels"]
        if entry.get("level", 0) > 0
    ]
    evidence_interpretations = active_interpretations(ai_payload, judgement_state)
    rule_coverage = build_rule_coverage(level_context)
    level_guidance = gather_level_guidance(graph_service, tentative.get("level_node_id"))
    coded_support = gather_coded_support(judgement_state, evidence_interpretations, graph_service)
    full_response = record.get("text") or ""

    return {
        "stage": stage,
        "stage_source": stage_source,
        "tentative_level": tentative,
        "level_descriptor": {
            "level": level_context["level"],
            "label": level_context["label"],
            "mark_range": level_context.get("mark_range"),
            "text": level_context.get("text"),
            "rules": level_context.get("rules", []),
        },
        "all_level_descriptors": all_level_descriptors,
        "rule_coverage": rule_coverage,
        "level_guidance": level_guidance,
        "key_guidance": build_key_guidance(level_context, rule_coverage, level_guidance),
        "coded_support": coded_support,
        "evidence_interpretations": [
            {
                "coding_id": item["coding_id"],
                "criterion_id": item["criterion_id"],
                "criterion_text": next(
                    (link["criterion_text"] for link in coded_support if link["coding_id"] == item["coding_id"]),
                    item["criterion_id"],
                ),
                "jev_relation": (item.get("jev_direct") or item.get("jev") or {}).get("relation"),
            }
            for item in evidence_interpretations
        ],
        "full_response": full_response,
        "response_note": (
            "Full response is for holistic reading. Only examiner-coded spans in coded_support "
            "count as mapped evidence."
        ),
        "question": _question_text(graph_service),
        "judgement_fingerprint": judgement_fingerprint(judgement_state),
    }


def _overlaps_coded_span(start_char: int, end_char: int, judgement_state: dict[str, Any]) -> bool:
    for span in judgement_state.get("evidence_spans", []):
        if start_char < span["end_char"] and end_char > span["start_char"]:
            return True
    return False


def discover_uncoded_candidates(
    *,
    classifier,
    graph_service: GraphService,
    record: dict[str, Any],
    judgement_state: dict[str, Any],
    context: dict[str, Any],
    retrieval_service=None,
    max_candidates: int = 3,
) -> list[dict[str, Any]]:
    """Search uncoded response text for optional evidence suggestions after the verdict."""
    from app.assessment import assess_evidence_link

    unresolved = [item for item in context.get("rule_coverage", []) if not item.get("satisfied")]
    weak_criteria = {
        item["criterion_id"]
        for item in context.get("coded_support", [])
        if item.get("jev_relation") in {"PARTIALLY_SUPPORTS", "DOES_NOT_SUPPORT", "UNCERTAIN"}
    }
    target_ids = {item["criterion_id"] for item in unresolved} | weak_criteria
    if not target_ids:
        return []

    candidates: list[dict[str, Any]] = []
    for criterion_id in sorted(target_ids):
        if len(candidates) >= max_candidates:
            break
        try:
            node = graph_service.get_node(criterion_id)
        except KeyError:
            continue
        query = _strip_display_text(node["text"])
        spans_to_try: list[dict[str, Any]] = []

        if retrieval_service is not None:
            search = retrieval_service.search_response(record["response_id"], query, top_k=3)
            for match in search.get("matches", []):
                start_char = match.get("start_char")
                end_char = match.get("end_char")
                text = match.get("text") or match.get("segment_text")
                if start_char is None or end_char is None or not text:
                    continue
                if _overlaps_coded_span(start_char, end_char, judgement_state):
                    continue
                spans_to_try.append({"start_char": start_char, "end_char": end_char, "text": text})
        else:
            lowered = query.lower()
            response_text = record.get("text") or ""
            index = response_text.lower().find(lowered[:40]) if lowered else -1
            if index >= 0:
                start_char = max(0, index - 20)
                end_char = min(len(response_text), index + len(query) + 40)
                spans_to_try.append(
                    {
                        "start_char": start_char,
                        "end_char": end_char,
                        "text": response_text[start_char:end_char],
                    }
                )

        for span in spans_to_try:
            assessment = assess_evidence_link(
                classifier=classifier,
                graph_service=graph_service,
                record=record,
                criterion_id=criterion_id,
                start_char=span["start_char"],
                end_char=span["end_char"],
                text=span["text"],
                search_additional=False,
            )
            jev = assessment.get("jev_direct") or assessment.get("jev")
            if not jev or jev.get("relation") not in {"SUPPORTS", "PARTIALLY_SUPPORTS"}:
                continue
            candidates.append(
                {
                    "criterion_id": criterion_id,
                    "criterion_text": query,
                    "start_char": span["start_char"],
                    "end_char": span["end_char"],
                    "text": _snippet(span["text"], 240),
                    "optional": True,
                }
            )
            break
    return candidates
