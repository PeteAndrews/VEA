"""Tool-using orchestration for the Examiner Assistant."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from app.assessment import assess_evidence_link
from app.classifier import EvidenceRelationClassifier
from app.conversation import _compact_criterion
from app.graph_service import GraphService
from app.intent import Intent, IntentClassifier, build_intent_conversation_context
from app.intervention import build_intervention_context
from app.judgement import judgement_view
from app.retrieval import RetrievalService
from app.stages import resolve_stage

SPAN_ANAPHORA = (
    "that sentence",
    "this sentence",
    "that span",
    "this span",
    "that evidence",
    "this evidence",
    "that excerpt",
    "this excerpt",
)
CRITERION_ANAPHORA = (
    "this criterion",
    "that criterion",
    "this point",
    "that point",
    "this link",
    "that link",
    "control point",
)
STALE_CONTEXT_KEYS = (
    "interpretive_context",
    "intervention",
    "interpretation_id",
    "jev_additional",
    "suggested_evidence_span",
    "graph_context",
    "borderline_link",
    "borderline_reasons",
)
INTENT_CLARIFICATION_MESSAGE = (
    "I'm not sure whether you're asking about a specific part of the response or whether "
    "the response contains evidence anywhere for a mark-scheme point. Could you clarify?"
)
ASSESSMENT_INTENTS = frozenset({"ASSESS_LINK", "FIND_SUPPORT"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _token_set(text: str) -> set[str]:
    stopwords = {
        "the",
        "and",
        "with",
        "for",
        "that",
        "this",
        "does",
        "response",
        "support",
        "using",
        "from",
        "into",
        "same",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9]+", _normalize(text))
        if len(token) > 2 and token not in stopwords
    }


def _has_span_anaphora(content: str) -> bool:
    lower = _normalize(content)
    return any(token in lower for token in SPAN_ANAPHORA)


def _prior_criterion_id(active_context: dict[str, Any]) -> str | None:
    refs = active_context.get("resolved_references") or {}
    criterion = refs.get("criterion") or active_context.get("criterion")
    return criterion.get("id") if criterion else None


def _drop_inherited_span(active_context: dict[str, Any]) -> None:
    refs = active_context.get("resolved_references") or {}
    refs.pop("response_span", None)
    active_context["resolved_references"] = refs
    active_context.pop("evidence", None)
    active_context.pop("jev", None)
    active_context.pop("jev_direct", None)


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


def _segment_dict(segment: dict[str, Any]) -> dict[str, Any]:
    return {
        "segment_id": segment["id"],
        "text": segment["text"],
        "start_char": segment["start_char"],
        "end_char": segment["end_char"],
    }


def _lexical_response_matches(record: dict[str, Any], query: str, limit: int = 5) -> list[dict[str, Any]]:
    needle = _normalize(query)
    if len(needle) < 3:
        return []
    matches: list[dict[str, Any]] = []
    for segment in record.get("segments", []):
        if needle in _normalize(segment["text"]):
            matches.append({**_segment_dict(segment), "match_type": "lexical"})
    return matches[:limit]


def _score_text_overlap(query: str, target: str) -> float:
    query_tokens = _token_set(query)
    target_tokens = _token_set(target)
    if not query_tokens or not target_tokens:
        return 0.0
    shared = len(query_tokens & target_tokens)
    return max(shared / len(target_tokens), shared / len(query_tokens))


def _strip_criterion_prefix(text: str) -> str:
    return re.sub(r"^[•o\s]+", "", text).strip()


def _query_phrases(content: str, criterion: dict[str, Any] | None = None) -> list[str]:
    phrases: list[str] = []
    lower = _normalize(content)
    support_match = re.search(
        r"(?:support|enough for|sufficient for|hold evidence for|evidence for|meet(?:s)?(?: the)?)\s+(.+?)(?:\?|$)",
        lower,
    )
    if support_match:
        phrases.append(support_match.group(1).strip(" ."))
    if criterion:
        phrases.append(_strip_criterion_prefix(criterion.get("text", "")))
    phrases.extend(re.findall(r"[a-z0-9]+(?: [a-z0-9]+){1,4}", lower))
    seen: set[str] = set()
    ordered: list[str] = []
    for phrase in phrases:
        normalized = _normalize(phrase)
        if len(normalized) >= 5 and normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)
    return ordered


def _resolve_criterion_from_query(
    content: str,
    graph_service: GraphService,
) -> dict[str, Any] | None:
    best_node = None
    best_score = 0.0
    for node in graph_service.graph.nodes.values():
        if not _is_indicative_criterion(node):
            continue
        score = _score_text_overlap(content, node["text"])
        if score > best_score:
            best_score = score
            best_node = node
    if best_node is not None and best_score >= 0.25:
        return graph_service.get_node(best_node["id"])
    return None


def _resolve_span_from_query(
    content: str,
    record: dict[str, Any],
    criterion: dict[str, Any] | None,
    retrieval_service: RetrievalService | None,
) -> dict[str, Any] | None:
    keyword_matches = _lexical_response_matches(record, content, limit=5)
    if keyword_matches:
        return keyword_matches[0]

    for phrase in _query_phrases(content, criterion):
        phrase_matches = _lexical_response_matches(record, phrase, limit=1)
        if phrase_matches:
            return phrase_matches[0]

    if criterion:
        best_segment = None
        best_score = 0.0
        for segment in record.get("segments", []):
            score = max(
                _score_text_overlap(criterion["text"], segment["text"]),
                _score_text_overlap(content, segment["text"]),
            )
            if score > best_score:
                best_score = score
                best_segment = segment
        if best_segment is not None and best_score >= 0.25:
            return _segment_dict(best_segment)

    if retrieval_service is not None:
        search = retrieval_service.search_response(record["response_id"], content, top_k=3)
        if search["matches"]:
            return search["matches"][0]

    return None


def _find_supporting_span(
    *,
    criterion: dict[str, Any],
    record: dict[str, Any],
    content: str,
    retrieval_service: RetrievalService | None,
) -> dict[str, Any] | None:
    criterion_text = _strip_criterion_prefix(criterion.get("text", ""))
    candidates: list[dict[str, Any]] = []
    seen_spans: set[tuple[int, int]] = set()

    def add_candidate(span: dict[str, Any] | None) -> None:
        if span is None:
            return
        key = (int(span["start_char"]), int(span["end_char"]))
        if key in seen_spans:
            return
        seen_spans.add(key)
        candidates.append(span)

    if retrieval_service is not None:
        search = retrieval_service.search_response(
            record["response_id"],
            criterion_text or content,
            top_k=5,
        )
        if search.get("matches"):
            return search["matches"][0]

    for phrase in [criterion_text, *_query_phrases(content, criterion)]:
        for match in _lexical_response_matches(record, phrase, limit=10):
            add_candidate(match)

    for segment in record.get("segments", []):
        score = _score_text_overlap(criterion["text"], segment["text"])
        if score >= 0.25:
            add_candidate(_segment_dict(segment))

    if not candidates:
        return None

    return max(
        candidates,
        key=lambda span: _score_text_overlap(criterion["text"], span["text"]),
    )


def _resolve_span_reference(
    *,
    content: str,
    active_context: dict[str, Any],
    record: dict[str, Any],
    retrieval_service: RetrievalService | None,
    criterion: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if _has_span_anaphora(content):
        refs = active_context.get("resolved_references") or {}
        span = refs.get("response_span") or active_context.get("evidence")
        if span:
            return span

    quoted = re.findall(r"[\"“](.+?)[\"”]", content)
    for fragment in quoted:
        matches = _lexical_response_matches(record, fragment, limit=1)
        if matches:
            return matches[0]

    return _resolve_span_from_query(content, record, criterion, retrieval_service)


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
    if any(token in lower for token in CRITERION_ANAPHORA):
        criterion = refs.get("criterion") or active_context.get("criterion")
        if criterion:
            return criterion

    criterion = _resolve_criterion_from_query(content, graph_service)
    if criterion:
        return criterion

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
        "guidance": (assessment.get("graph_context") or {}).get("guidance", [])[:2],
    }


def _clear_stale_turn_context(active_context: dict[str, Any]) -> None:
    for key in STALE_CONTEXT_KEYS:
        active_context.pop(key, None)


def _apply_turn_resolution(
    active_context: dict[str, Any],
    *,
    resolved_references: dict[str, Any],
    assessment: dict[str, Any] | None = None,
) -> None:
    _clear_stale_turn_context(active_context)
    if resolved_references.get("response_span"):
        active_context["evidence"] = resolved_references["response_span"]
    elif resolved_references.get("criterion"):
        active_context.pop("evidence", None)
        active_context.pop("jev", None)
        active_context.pop("jev_direct", None)
    if resolved_references.get("criterion"):
        active_context["criterion"] = resolved_references["criterion"]
    if assessment:
        active_context["jev"] = assessment.get("jev")
        active_context["jev_direct"] = assessment.get("jev_direct")
        active_context["parent_criterion"] = assessment.get("parent_criterion")
        active_context["suggested_evidence_span"] = assessment.get("suggested_evidence_span")


def _prepare_span_resolution(
    *,
    content: str,
    active_context: dict[str, Any],
    intent: Intent,
    new_criterion: dict[str, Any] | None,
) -> None:
    prior_criterion_id = _prior_criterion_id(active_context)
    new_criterion_id = new_criterion["id"] if new_criterion else None
    criterion_changed = (
        new_criterion_id is not None
        and prior_criterion_id is not None
        and new_criterion_id != prior_criterion_id
    )
    if intent == "FIND_SUPPORT" or (criterion_changed and not _has_span_anaphora(content)):
        _drop_inherited_span(active_context)


def _build_turn_llm_context(
    *,
    intent: Intent,
    content: str,
    resolved_references: dict[str, Any],
    tool_results: list[dict[str, Any]],
    citations: list[dict[str, Any]],
) -> dict[str, Any]:
    turn_context: dict[str, Any] = {
        "source": "turn",
        "intent": intent,
        "user_message": content,
        "tool_results": tool_results,
        "citations": citations,
    }
    criterion = resolved_references.get("criterion")
    span = resolved_references.get("response_span")
    if criterion:
        turn_context["criterion"] = _compact_criterion(criterion)
    if span:
        turn_context["evidence"] = {
            "text": span.get("text"),
            "start_char": span.get("start_char"),
            "end_char": span.get("end_char"),
        }
    for tool_result in tool_results:
        if tool_result.get("tool") == "assess_evidence_link":
            turn_context["assessment"] = tool_result.get("result")
        if tool_result.get("tool") == "get_assessment_context":
            turn_context["mark_scheme_context"] = {
                "criterion": _compact_criterion(tool_result.get("criterion")),
                "parent_criterion": _compact_criterion(tool_result.get("parent_criterion")),
                "question": tool_result.get("question"),
                "guidance": tool_result.get("guidance", [])[:2],
            }
        if tool_result.get("tool") == "search_response":
            turn_context["response_matches"] = tool_result.get("matches", [])[:3]
    return turn_context


def _explain_messages(
    intent: Intent,
    content: str,
    history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if intent in ASSESSMENT_INTENTS:
        return [{"role": "user", "content": content}]
    return list(history)


def _run_link_assessment(
    *,
    classifier: EvidenceRelationClassifier,
    graph_service: GraphService,
    record: dict[str, Any],
    criterion: dict[str, Any],
    span: dict[str, Any],
    tool_results: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    resolved_references: dict[str, Any],
    trace: dict[str, Any],
) -> dict[str, Any] | None:
    assessment = assess_evidence_link(
        classifier=classifier,
        graph_service=graph_service,
        record=record,
        criterion_id=criterion["id"],
        start_char=int(span["start_char"]),
        end_char=int(span["end_char"]),
        text=span["text"],
        evidence_id=span.get("segment_id") or span.get("evidence_id"),
        search_additional=False,
    )
    assessment_result = _explain_assessment(assessment)
    tool_results.append({"tool": "assess_evidence_link", "result": assessment_result})
    trace["jev_relation"] = assessment_result.get("relation")
    resolved_references["response_span"] = assessment["evidence"]
    resolved_references["criterion"] = assessment["criterion"]
    citations.extend(
        [
            _citation_from_span(assessment["evidence"]),
            _citation_from_criterion(assessment["criterion"]),
        ]
    )
    return assessment


def process_assistant_turn(
    *,
    content: str,
    active_context: dict[str, Any],
    graph_service: GraphService,
    record: dict[str, Any],
    judgement_state: dict[str, Any],
    classifier: EvidenceRelationClassifier,
    intent_classifier: IntentClassifier,
    retrieval_service: RetrievalService | None,
    llm,
    prompt_loader,
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    from app.level_conversation import is_level_conversation_context, process_level_conversation_turn

    if is_level_conversation_context(active_context):
        context_id = active_context.get("context_id", "")
        history_messages = [
            *history,
            {"role": "user", "content": content, "context_id": context_id},
        ]
        return process_level_conversation_turn(
            active_context=active_context,
            llm=llm,
            prompt_loader=prompt_loader,
            messages=history_messages,
            context_id=context_id,
        )

    intent_decision = intent_classifier.classify(
        content,
        build_intent_conversation_context(active_context),
    )
    intent = intent_decision.intent
    tool_results: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    resolved_references: dict[str, Any] = {}
    clarification_needed = intent_decision.needs_clarification
    clarification_message = INTENT_CLARIFICATION_MESSAGE
    assessment: dict[str, Any] | None = None
    trace: dict[str, Any] = {
        "intent": intent,
        "intent_decision": intent_decision.to_dict(),
    }

    if not clarification_needed and intent == "DISCUSS":
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
            trace["resolved_criterion_id"] = criterion["id"]
        else:
            overview = graph_service.assessment_overview()
            question_text = " ".join(
                item["text"].strip()
                for item in overview.get("question", [])
                if item.get("text")
            )
            tool_results.append(
                {
                    "tool": "get_judgement_context",
                    "judgement": _judgement_summary(graph_service, judgement_state, "data"),
                    "assessment_overview": overview,
                    "question": question_text or None,
                }
            )

    elif not clarification_needed and intent == "LOCATE_EVIDENCE":
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
            trace["resolved_span"] = {
                "start_char": matches[0]["start_char"],
                "end_char": matches[0]["end_char"],
            }
        else:
            clarification_needed = True
            clarification_message = (
                "I couldn't find a clear match in the response. "
                "Can you quote a few words from the part you mean?"
            )

    elif not clarification_needed and intent in {"ASSESS_LINK", "FIND_SUPPORT"}:
        criterion = _resolve_criterion_reference(
            content=content,
            active_context=active_context,
            graph_service=graph_service,
            retrieval_service=retrieval_service,
        )
        _prepare_span_resolution(
            content=content,
            active_context=active_context,
            intent=intent,
            new_criterion=criterion,
        )
        if intent == "FIND_SUPPORT":
            span = (
                _find_supporting_span(
                    criterion=criterion,
                    record=record,
                    content=content,
                    retrieval_service=retrieval_service,
                )
                if criterion
                else None
            )
        else:
            span = _resolve_span_reference(
                content=content,
                active_context=active_context,
                record=record,
                retrieval_service=retrieval_service,
                criterion=criterion,
            )

        trace["resolved_criterion_id"] = criterion["id"] if criterion else None
        if span:
            trace["resolved_span"] = {
                "start_char": span["start_char"],
                "end_char": span["end_char"],
                "text": span["text"],
            }
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
            assessment = _run_link_assessment(
                classifier=classifier,
                graph_service=graph_service,
                record=record,
                criterion=criterion,
                span=span,
                tool_results=tool_results,
                citations=citations,
                resolved_references=resolved_references,
                trace=trace,
            )

    active_context["resolved_references"] = resolved_references
    active_context["last_intent"] = intent
    active_context["last_trace"] = trace
    active_context["updated_at"] = _utc_now()
    _apply_turn_resolution(active_context, resolved_references=resolved_references, assessment=assessment)

    if clarification_needed:
        assistant_text = clarification_message
    else:
        system_prompt = prompt_loader.load_system()
        explain_prompt = prompt_loader.load("assistant_explain.txt")
        turn_context = _build_turn_llm_context(
            intent=intent,
            content=content,
            resolved_references=resolved_references,
            tool_results=tool_results,
            citations=citations,
        )
        assistant_text = llm.respond(
            system_prompt=system_prompt,
            launch_prompt=explain_prompt,
            active_context=turn_context,
            messages=_explain_messages(intent, content, history),
        )

    return {
        "content": assistant_text,
        "intent": intent,
        "tool_results": tool_results,
        "citations": citations,
        "resolved_references": resolved_references,
        "clarification_needed": clarification_needed,
        "active_context": active_context,
        "trace": trace,
    }
