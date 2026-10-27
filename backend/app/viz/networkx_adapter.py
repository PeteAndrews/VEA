"""Convert GraphInstance layers into a read-only NetworkX graph."""

from __future__ import annotations

from typing import Any

import networkx as nx

from app.representation.instance import GraphInstance

LABEL_LIMIT = 96
LABEL_WRAP_WIDTH = 24


def _wrap_words(text: str, width: int = LABEL_WRAP_WIDTH) -> str:
    if width <= 0 or len(text) <= width:
        return text
    words = text.split()
    if not words:
        return text
    lines: list[str] = []
    current: list[str] = []
    current_len = 0
    for word in words:
        extra = len(word) if not current else len(word) + 1
        if current and current_len + extra > width:
            lines.append(" ".join(current))
            current = [word]
            current_len = len(word)
        elif not current and len(word) > width:
            lines.append(word)
            current = []
            current_len = 0
        else:
            current.append(word)
            current_len += extra
    if current:
        lines.append(" ".join(current))
    return "\n".join(lines)


def _label(text: str, limit: int = LABEL_LIMIT, wrap_width: int = LABEL_WRAP_WIDTH) -> str:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return ""
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1] + "…"
    return _wrap_words(cleaned, wrap_width)


def to_networkx(instance: GraphInstance, *, include_structural: bool = True) -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    assessment = instance.assessment

    for node_id, node in assessment.nodes.items():
        if node.get("segment_type") == "response_segment":
            continue
        graph.add_node(
            node_id,
            layer="assessment",
            node_type=node.get("node_type"),
            segment_type=node.get("segment_type"),
            label=_label(node.get("text") or node_id),
        )

    for node_id, edges in assessment.out_edges.items():
        for edge in edges:
            if edge["target"] not in assessment.nodes:
                continue
            if not include_structural and edge.get("kind") == "structural":
                continue
            graph.add_edge(
                edge["source"],
                edge["target"],
                relation=edge.get("relation"),
                kind=edge.get("kind"),
                layer="assessment",
            )

    if instance.response is not None:
        response = instance.response
        graph.add_node(
            response.root_id,
            layer="response",
            node_type="response",
            segment_type="response_root",
            label=_label(response.text[:120] or response.response_id),
        )
        for segment in response.segments:
            graph.add_node(
                segment.id,
                layer="response",
                node_type="response",
                segment_type="response_segment",
                label=_label(segment.text),
            )
        for edge in response.edges:
            graph.add_edge(
                edge.source,
                edge.target,
                relation=edge.relation,
                kind=edge.kind,
                layer="response",
            )

    if instance.judgement is not None:
        judgement = instance.judgement
        for span in judgement.spans:
            graph.add_node(
                span.id,
                layer="judgement",
                node_type="evidence_span",
                segment_type="evidence_span",
                label=_label(span.text),
            )
        for link in judgement.links:
            graph.add_edge(
                link.span_id,
                link.criterion_id,
                relation=link.relation,
                kind="judgement",
                layer="judgement",
                active=link.active,
            )
        for overlap in judgement.overlaps:
            graph.add_edge(
                overlap.span_id,
                overlap.segment_id,
                relation="OVERLAPS",
                kind="alignment",
                layer="judgement",
                overlap_chars=overlap.overlap_chars,
            )
        if judgement.tentative_level and judgement.tentative_level.level_node_id:
            decision_id = f"decision-level-{judgement.tentative_level.level}"
            graph.add_node(
                decision_id,
                layer="judgement",
                node_type="decision",
                segment_type="tentative_level",
                label=f"Tentative L{judgement.tentative_level.level}",
            )
            graph.add_edge(
                decision_id,
                judgement.tentative_level.level_node_id,
                relation="ASSIGNS_LEVEL",
                kind="judgement",
                layer="judgement",
            )
        if judgement.final_mark is not None:
            mark_id = "decision-final-mark"
            graph.add_node(
                mark_id,
                layer="judgement",
                node_type="decision",
                segment_type="final_mark",
                label=f"Final mark {judgement.final_mark.final_mark}",
            )

    return graph
