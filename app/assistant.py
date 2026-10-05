"""Tool-using orchestration for the Examiner Assistant."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from app.assessment import assess_evidence_link
from app.classifier import EvidenceRelationClassifier
from app.conversation import compact_context_for_llm
from app.graph_service import GraphService
from app.intervention import build_intervention_context
from app.judgement import judgement_view
from app.retrieval import RetrievalService
from app.stages import resolve_stage

Intent = Literal["DISCUSS", "LOCATE_EVIDENCE", "ASSESS_LINK"]

ASSESS_HINTS = (
    "enough for",
    "would that",
    "does that support",
    "does this support",
    "is that sufficient",
    "is this sufficient",
    "support the",
    "count for",
    "credit for",
    "meet the criterion",
    "meet point",
)
LOCATE_HINTS = (
    "where does",
    "where do they",
    "where is",
    "find",
    "mention",
    "talk about",
    "refer to",
    "show me",
    "which part",
    "which sentence",
)
DISCUSS_HINTS = (
    "what does",
    "what is",
    "explain",
    "mean",
    "tell me about",
    "how is",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def classify_intent(content: str) -> Intent:
    lower = _normalize(content)
    if any(hint in lower for hint in ASSESS_HINTS):
        return "ASSESS_LINK"
    if any(hint in lower for hint in LOCATE_HINTS):
        return "LOCATE_EVIDENCE"
    if any(hint in lower for hint in DISCUSS_HINTS):
        return "DISCUSS"
    return "DISCUSS"


def _judgement_summary(
    graph_service: GraphService,
    judgement_state: dict[str, Any],
    data_dir: str,
) -> dict[str, Any]:
    view = judgement_view(judgement_state, graph_service, data_dir)
    return {
        "codings": view.get("codings", []),
        "tentative_level": view.get("tentative_level"),
        "event_count": len(judgement_state.get("events", [])),
    }


def build_session_context(
    *,
    graph_service: GraphService,
    record: dict[str, Any],
    judgement_state: dict[str, Any],
    assessment_id: str,
    data_dir: str,
    source: str = "general",
    stage: str | None = None,
    stage_source: str | None = None,
    coding_id: str | None = None,
    interpretation: dict[str, Any] | None = None,
    resolved_references: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_stage, resolved_stage_source = resolve_stage(judgement_state, stage, None)
    context: dict[str, Any] = {
        "context_id": _new_id("ctx"),
        "source": source,
        "stage": resolved_stage,
        "stage_source": stage_source or resolved_stage_source,
        "assessment_id": assessment_id,
        "response_id": record["response_id"],
        "response_segments": [
            {
                "segment_id": segment["id"],
                "order": segment["order"],
                "text": segment["text"],
                "start_char": segment["start_char"],
                "end_char": segment["end_char"],
            }
            for segment in record.get("segments", [])
        ],
        "assessment_overview": graph_service.assessment_overview(),
        "judgement": _judgement_summary(graph_service, judgement_state, data_dir),
        "tentative_level": judgement_state.get("tentative_level"),
        "coding_id": coding_id,
        "resolved_references": dict(resolved_references or {}),
        "prepared_at": _utc_now(),
    }
    if coding_id and interpretation:
        from app.conversation import build_conversation_context

        coding_context = build_conversation_context(
            graph_service=graph_service,
            record=record,
            judgement_state=judgement_state,
            coding_id=coding_id,
            source=source if source in {"explore", "verify"} else "verify",
            interpretation=interpretation,
            stage=stage,
            stage_source=stage_source,
        )
        context.update(
            {
                "evidence": coding_context.get("evidence"),
                "criterion": coding_context.get("criterion"),
                "parent_criterion": coding_context.get("parent_criterion"),
                "interpretive_context": coding_context.get("interpretive_context"),
                "jev": coding_context.get("jev"),
                "jev_direct": coding_context.get("jev_direct"),
                "intervention": coding_context.get("intervention"),
                "interpretation_id": coding_context.get("interpretation_id"),
                "graph_context": coding_context.get("graph_context"),
            }
        )
    return context


def _find_coding_by_id(judgement_state: dict[str, Any], coding_id: str) -> dict[str, Any] | None:
    spans = {span["id"]: span for span in judgement_state.get("evidence_spans", [])}
    for relation in judgement_state.get("relations", []):
        if relation["id"] != coding_id:
            continue
        span = spans.get(relation["source"])
        if span is None:
            return None
        return {
            "coding_id": relation["id"],
            "criterion_id": relation["target"],
            "start_char": span["start_char"],
            "end_char": span["end_char"],
            "text": span["text"],
        }
    return None


def _lexical_response_matches(record: dict[str, Any], query: str, limit: int = 5) -> list[dict[str, Any]]:
    needle = _normalize(query)
    if len(needle) < 3:
        return []
    matches: list[dict[str, Any]] = []
    for segment in record.get("segments", []):
        if needle in _normalize(segment["text"]):
            matches.append(
                {
                    "segment_id": segment["id"],
                    "text": segment["text"],
                    "start_char": segment["start_char"],
                    "end_char": segment["end_char"],
                    "match_type": "lexical",
                }
            )
    return matches[:limit]


def _resolve_span_reference(
    *,
    content: str,
    active_context: dict[str, Any],
    record: dict[str, Any],
    retrieval_service: RetrievalService | None,
) -> dict[str, Any] | None:
    lower = _normalize(content)
    refs = active_context.get("resolved_references") or {}
    if any(token in lower for token in ("that sentence", "this sentence", "that span", "this span", "that evidence")):
        span = refs.get("response_span") or active_context.get("evidence")
        if span:
            return span

    quoted = re.findall(r"[\"“](.+?)[\"”]", content)
    for fragment in quoted:
        matches = _lexical_response_matches(record, fragment, limit=1)
        if matches:
            return matches[0]

    if retrieval_service is not None:
        search = retrieval_service.search_response(record["response_id"], content, top_k=1)
        if search["matches"]:
            return search["matches"][0]

    if active_context.get("evidence"):
        return active_context["evidence"]
    return None


def _is_indicative_criterion(node: dict[str, Any]) -> bool:
    return node.get("node_type") == "mark_point" and node.get("segment_type") == "indicative_point"


def _resolve_criterion_reference(
    *,
    content: str,
    active_context: dict[str, Any],
    graph_service: GraphService,
    retrieval_service: RetrievalService | None,
) -> dict[str, Any] | None:
    lower = _normalize(content)
    refs = active_context.get("resolved_references") or {}
    if any(token in lower for token in ("this criterion", "that criterion", "this point", "that point", "control point")):
        criterion = refs.get("criterion") or active_context.get("criterion")
        if criterion:
            return criterion

    if active_context.get("criterion") and any(
        token in lower for token in ("this", "that", "partially", "why", "how", "enough")
    ):
        return active_context["criterion"]

    point_match = re.search(r"point\s+(\d+[a-z]?)", lower)
    if point_match:
        token = point_match.group(1)
        for node_id, node in graph_service.graph.nodes.items():
            if node.get("segment_type") != "indicative_point":
                continue
            if token in _normalize(node_id) or token in _normalize(node.get("text", "")):
                return graph_service.get_node(node_id)

    if retrieval_service is not None:
        result = retrieval_service.similar_text(content, top_k=5, scope="criteria")
        for match in result["matches"]:
            node = graph_service.get_node(match["node_id"])
            if _is_indicative_criterion(node):
                return node

    if active_context.get("criterion"):
        return active_context["criterion"]
    return None


def _citation_from_span(span: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "response_span",
        "segment_id": span.get("segment_id"),
        "start_char": span.get("start_char"),
        "end_char": span.get("end_char"),
        "text": span.get("text"),
    }


def _citation_from_criterion(criterion: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "criterion",
        "criterion_id": criterion.get("id"),
        "text": criterion.get("text"),
    }


def _explain_assessment(assessment: dict[str, Any]) -> dict[str, Any]:
    jev = assessment.get("jev") or {}
    return {
        "relation": jev.get("relation"),
        "criterion_id": assessment.get("criterion_id"),
        "criterion_text": (assessment.get("criterion") or {}).get("text"),
        "evidence_text": (assessment.get("evidence") or {}).get("text"),
        "suggested_evidence_span": assessment.get("suggested_evidence_span"),
        "additional_evidence": assessment.get("additional_evidence"),
        "guidance": (assessment.get("graph_context") or {}).get("guidance", [])[:4],
    }


def process_assistant_turn(
    *,
    content: str,
    active_context: dict[str, Any],
    graph_service: GraphService,
    record: dict[str, Any],
    judgement_state: dict[str, Any],
    classifier: EvidenceRelationClassifier,
    retrieval_service: RetrievalService | None,
    llm,
    prompt_loader,
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    intent = classify_intent(content)
    tool_results: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    resolved_references = dict(active_context.get("resolved_references") or {})
    clarification_needed = False
    clarification_message = ""

    if intent == "DISCUSS":
        criterion = _resolve_criterion_reference(
            content=content,
            active_context=active_context,
            graph_service=graph_service,
            retrieval_service=retrieval_service,
        )
        if criterion:
            graph_context = build_intervention_context(graph_service, criterion["id"])
            tool_results.append(
                {
                    "tool": "get_assessment_context",
                    "criterion_id": criterion["id"],
                    "criterion": graph_context["criterion"],
                    "parent_criterion": graph_context.get("parent_criterion"),
                    "guidance": graph_context.get("guidance", [])[:6],
                    "question": graph_context.get("question"),
                }
            )
            resolved_references["criterion"] = graph_context["criterion"]
            citations.append(_citation_from_criterion(graph_context["criterion"]))
        else:
            tool_results.append(
                {
                    "tool": "get_judgement_context",
                    "judgement": _judgement_summary(graph_service, judgement_state, "data"),
                    "assessment_overview": graph_service.assessment_overview(),
                }
            )

    elif intent == "LOCATE_EVIDENCE":
        lexical = _lexical_response_matches(record, content)
        semantic = (
            retrieval_service.search_response(record["response_id"], content, top_k=5)
            if retrieval_service is not None
            else {"matches": []}
        )
        matches = lexical or semantic.get("matches", [])
        tool_results.append({"tool": "search_response", "matches": matches[:5]})
        if matches:
            resolved_references["response_span"] = matches[0]
            citations.append(_citation_from_span(matches[0]))
        else:
            clarification_needed = True
            clarification_message = "I couldn't find a clear match in the response. Can you quote a few words from the part you mean?"

    elif intent == "ASSESS_LINK":
        span = _resolve_span_reference(
            content=content,
            active_context=active_context,
            record=record,
            retrieval_service=retrieval_service,
        )
        criterion = _resolve_criterion_reference(
            content=content,
            active_context=active_context,
            graph_service=graph_service,
            retrieval_service=retrieval_service,
        )
        if span is None or criterion is None:
            clarification_needed = True
            missing = []
            if span is None:
                missing.append("which response text")
            if criterion is None:
                missing.append("which mark-scheme point")
            clarification_message = (
                f"I need to pin down {' and '.join(missing)} before I can judge the link. "
                "Can you point me to the exact span and criterion?"
            )
        else:
            assessment = assess_evidence_link(
                classifier=classifier,
                graph_service=graph_service,
                record=record,
                criterion_id=criterion["id"],
                start_char=int(span["start_char"]),
                end_char=int(span["end_char"]),
                text=span["text"],
                evidence_id=span.get("segment_id") or span.get("evidence_id"),
                search_additional=True,
            )
            tool_results.append({"tool": "assess_evidence_link", "result": _explain_assessment(assessment)})
            resolved_references["response_span"] = assessment["evidence"]
            resolved_references["criterion"] = assessment["criterion"]
            citations.extend(
                [
                    _citation_from_span(assessment["evidence"]),
                    _citation_from_criterion(assessment["criterion"]),
                ]
            )
            active_context["evidence"] = assessment["evidence"]
            active_context["criterion"] = assessment["criterion"]
            active_context["parent_criterion"] = assessment.get("parent_criterion")
            active_context["jev"] = assessment.get("jev")
            active_context["jev_direct"] = assessment.get("jev_direct")
            active_context["suggested_evidence_span"] = assessment.get("suggested_evidence_span")

    active_context["resolved_references"] = resolved_references
    active_context["last_intent"] = intent
    active_context["updated_at"] = _utc_now()

    if clarification_needed:
        assistant_text = clarification_message
    else:
        system_prompt = prompt_loader.load_system()
        explain_prompt = prompt_loader.load("assistant_explain.txt")
        turn_context = {
            "source": active_context.get("source", "general"),
            "intent": intent,
            "user_message": content,
            "active_context": compact_context_for_llm(active_context),
            "tool_results": tool_results,
            "citations": citations,
        }
        assistant_text = llm.respond(
            system_prompt=system_prompt,
            launch_prompt=explain_prompt,
            active_context=turn_context,
            messages=history,
        )

    return {
        "content": assistant_text,
        "intent": intent,
        "tool_results": tool_results,
        "citations": citations,
        "resolved_references": resolved_references,
        "clarification_needed": clarification_needed,
        "active_context": active_context,
    }
