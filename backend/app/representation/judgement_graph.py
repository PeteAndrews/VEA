"""Layer 3: examiner judgement as a derived graph (not a competing store).

Adjacent AI interaction data lives in AIInterpretationStore and is intentionally excluded here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.representation.labels import supervision_for_relation
from app.representation.response_graph import ResponseGraph, ResponseSegmentNode


@dataclass(frozen=True)
class EvidenceSpanNode:
    id: str
    response_id: str
    start_char: int
    end_char: int
    text: str


@dataclass(frozen=True)
class OverlapEdge:
    span_id: str
    segment_id: str
    span_chars: int
    segment_chars: int
    overlap_chars: int
    overlap_fraction_of_span: float
    overlap_fraction_of_segment: float


@dataclass(frozen=True)
class JudgementLinkEdge:
    id: str
    span_id: str
    criterion_id: str
    relation: str
    origin: str
    examiner_id: str | None
    active: bool
    created_at: str | None
    updated_at: str | None
    event_seq: int | None = None


@dataclass(frozen=True)
class LevelDecision:
    level: int
    level_node_id: str | None
    examiner_id: str | None
    set_at: str | None
    active: bool = True


@dataclass(frozen=True)
class FinalMarkDecision:
    final_mark: int
    submitted_at: str | None = None


@dataclass
class JudgementGraph:
    marking_session_id: str
    assessment_id: str
    response_id: str
    spans: list[EvidenceSpanNode] = field(default_factory=list)
    links: list[JudgementLinkEdge] = field(default_factory=list)
    overlaps: list[OverlapEdge] = field(default_factory=list)
    tentative_level: LevelDecision | None = None
    final_mark: FinalMarkDecision | None = None

    @classmethod
    def from_state(
        cls,
        state: dict[str, Any],
        *,
        response_graph: ResponseGraph | None = None,
        final_mark: int | None = None,
        final_mark_submitted_at: str | None = None,
        include_history: bool = False,
    ) -> JudgementGraph:
        spans = [
            EvidenceSpanNode(
                id=span["id"],
                response_id=state["response_id"],
                start_char=int(span["start_char"]),
                end_char=int(span["end_char"]),
                text=span["text"],
            )
            for span in state.get("evidence_spans", [])
        ]
        span_by_id = {span.id: span for span in spans}

        active_relations = {rel["id"]: rel for rel in state.get("relations", [])}
        historical: list[JudgementLinkEdge] = []
        if include_history:
            historical = _historical_links_from_events(state.get("events", []), span_by_id)

        links: list[JudgementLinkEdge] = []
        for relation in state.get("relations", []):
            if relation.get("origin") != "examiner":
                continue
            span_id = relation["source"]
            if span_id not in span_by_id:
                continue
            links.append(
                JudgementLinkEdge(
                    id=relation["id"],
                    span_id=span_id,
                    criterion_id=relation["target"],
                    relation=relation.get("relation") or "SUPPORTS",
                    origin=relation.get("origin") or "examiner",
                    examiner_id=relation.get("examiner_id"),
                    active=True,
                    created_at=relation.get("created_at"),
                    updated_at=relation.get("updated_at"),
                )
            )
        links.extend(historical)

        tentative = state.get("tentative_level")
        level_decision = None
        if tentative is not None:
            level_decision = LevelDecision(
                level=int(tentative["level"]),
                level_node_id=tentative.get("level_node_id"),
                examiner_id=tentative.get("examiner_id"),
                set_at=tentative.get("set_at"),
                active=True,
            )

        overlaps: list[OverlapEdge] = []
        if response_graph is not None:
            overlaps = compute_overlaps(spans, response_graph.segments)

        final = None
        if final_mark is not None:
            final = FinalMarkDecision(final_mark=int(final_mark), submitted_at=final_mark_submitted_at)

        return cls(
            marking_session_id=state["marking_session_id"],
            assessment_id=state["assessment_id"],
            response_id=state["response_id"],
            spans=spans,
            links=links,
            overlaps=overlaps,
            tentative_level=level_decision,
            final_mark=final,
        )


def compute_overlaps(
    spans: list[EvidenceSpanNode],
    segments: list[ResponseSegmentNode],
) -> list[OverlapEdge]:
    results: list[OverlapEdge] = []
    for span in spans:
        span_len = max(0, span.end_char - span.start_char)
        if span_len == 0:
            continue
        for segment in segments:
            seg_len = max(0, segment.end_char - segment.start_char)
            if seg_len == 0:
                continue
            overlap = max(0, min(span.end_char, segment.end_char) - max(span.start_char, segment.start_char))
            if overlap <= 0:
                continue
            results.append(
                OverlapEdge(
                    span_id=span.id,
                    segment_id=segment.id,
                    span_chars=span_len,
                    segment_chars=seg_len,
                    overlap_chars=overlap,
                    overlap_fraction_of_span=round(overlap / span_len, 6),
                    overlap_fraction_of_segment=round(overlap / seg_len, 6),
                )
            )
    return results


def _historical_links_from_events(
    events: list[dict[str, Any]],
    span_by_id: dict[str, EvidenceSpanNode],
) -> list[JudgementLinkEdge]:
    """Inactive links reconstructed from EVIDENCE_CODED / CODING_REVISED / CODING_REMOVED."""
    active: dict[str, dict[str, Any]] = {}
    retired: list[JudgementLinkEdge] = []

    for event in sorted(events, key=lambda item: item.get("seq", 0)):
        seq = event.get("seq")
        event_type = event.get("type")
        payload = event.get("payload") or {}
        examiner_id = event.get("examiner_id")

        if event_type == "EVIDENCE_CODED":
            coding_id = payload.get("coding_id")
            if not coding_id:
                continue
            span = payload.get("span") or {}
            active[coding_id] = {
                "coding_id": coding_id,
                "criterion_id": payload.get("criterion_id"),
                "span_id": f"span-{span.get('start_char')}-{span.get('end_char')}",
                "relation": "SUPPORTS",
                "examiner_id": examiner_id,
                "at": event.get("at"),
            }
        elif event_type == "CODING_REVISED":
            before = payload.get("before") or {}
            after = payload.get("after") or {}
            coding_id = before.get("coding_id") or after.get("coding_id")
            prev = active.pop(coding_id, None) if coding_id else None
            if prev and prev.get("criterion_id") and prev.get("span_id") in span_by_id:
                retired.append(_inactive_link(prev, seq, relation=prev.get("relation", "SUPPORTS")))
            if coding_id:
                active[coding_id] = {
                    "coding_id": coding_id,
                    "criterion_id": after.get("criterion_id"),
                    "span_id": after.get("span_id"),
                    "relation": after.get("relation") or (prev.get("relation") if prev else "SUPPORTS"),
                    "examiner_id": examiner_id,
                    "at": event.get("at"),
                }
        elif event_type == "CODING_REMOVED":
            coding_id = payload.get("coding_id")
            if coding_id and coding_id in active:
                prev = active.pop(coding_id)
                if prev.get("criterion_id") and prev.get("span_id") in span_by_id:
                    retired.append(_inactive_link(prev, seq, relation=prev.get("relation", "SUPPORTS")))

    return retired


def _inactive_link(record: dict[str, Any], seq: int | None, *, relation: str) -> JudgementLinkEdge:
    return JudgementLinkEdge(
        id=str(record.get("coding_id")),
        span_id=str(record.get("span_id")),
        criterion_id=str(record.get("criterion_id")),
        relation=relation,
        origin="examiner",
        examiner_id=record.get("examiner_id"),
        active=False,
        created_at=record.get("at"),
        updated_at=record.get("at"),
        event_seq=seq,
    )


def link_supervision(link: JudgementLinkEdge) -> str | None:
    label = supervision_for_relation(link.relation, active=link.active)
    return label.value if label else None
