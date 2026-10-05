"""Bounded evidence–criterion assessment via graph context and Jev.

This module performs classification only. Interruption decisions (REVIEW,
CHALLENGE, REANCHOR, SILENCE, etc.) live in intervention policy and must not
be applied to explicit conversational ASSESS_LINK requests.
"""

from __future__ import annotations

from typing import Any

from app.classifier import EvidenceRelationClassifier, RelationDecision
from app.evidence import build_response_local_context_for_span, containing_sentence_span
from app.graph_service import GraphService
WEAK_RELATIONS = frozenset({"PARTIALLY_SUPPORTS", "DOES_NOT_SUPPORT", "UNCERTAIN"})


def _jev_payload(decision: RelationDecision) -> dict[str, Any]:
    jev = decision.to_dict()
    return {
        "relation": jev["relation"],
        "probabilities": jev["probabilities"],
        "probability": jev["probability"],
        "confidence": jev["confidence"],
        "needs_review": jev["needs_review"],
        "classifier": jev["classifier"],
        "model": jev["model"],
    }


def _relation_supports(relation: str) -> bool:
    return relation == "SUPPORTS"


def _relation_weak(relation: str) -> bool:
    return relation in WEAK_RELATIONS


def should_search_additional_evidence(direct_jev: dict[str, Any]) -> bool:
    from app.intervention import intervention_needs_review

    if _relation_weak(direct_jev["relation"]):
        return True
    return direct_jev["relation"] == "SUPPORTS" and intervention_needs_review(direct_jev)


def expansion_candidates(
    record: dict[str, Any],
    *,
    start_char: int,
    end_char: int,
    interpretive_context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build minimal contiguous expansions within the sentence and neighbour segments."""
    text = record["text"]
    preceding = interpretive_context.get("preceding_segment")
    following = interpretive_context.get("following_segment")
    candidates: list[dict[str, Any]] = []

    sentence_candidate = containing_sentence_span(
        record,
        start_char=start_char,
        end_char=end_char,
    )
    if sentence_candidate:
        candidates.append(sentence_candidate)

    if following:
        candidates.append(
            {
                "start_char": start_char,
                "end_char": int(following["end_char"]),
                "text": text[start_char : int(following["end_char"])],
                "expansion": "following",
            }
        )
    if preceding:
        candidates.append(
            {
                "start_char": int(preceding["start_char"]),
                "end_char": end_char,
                "text": text[int(preceding["start_char"]) : end_char],
                "expansion": "preceding",
            }
        )
    if preceding and following:
        candidates.append(
            {
                "start_char": int(preceding["start_char"]),
                "end_char": int(following["end_char"]),
                "text": text[int(preceding["start_char"]) : int(following["end_char"])],
                "expansion": "both",
            }
        )

    candidates.sort(key=lambda item: item["end_char"] - item["start_char"])
    return candidates


def search_additional_evidence(
    classifier: EvidenceRelationClassifier,
    *,
    record: dict[str, Any],
    criterion: dict[str, Any],
    jev_context_base: dict[str, Any],
    start_char: int,
    end_char: int,
    interpretive_context: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Find the smallest expanded span that Jev classifies as SUPPORTS."""
    for candidate in expansion_candidates(
        record,
        start_char=start_char,
        end_char=end_char,
        interpretive_context=interpretive_context,
    ):
        expanded_interpretive = build_response_local_context_for_span(
            record,
            start_char=candidate["start_char"],
            end_char=candidate["end_char"],
        )
        decision = classifier.classify(
            candidate["text"],
            criterion,
            {
                **jev_context_base,
                "start_char": candidate["start_char"],
                "end_char": candidate["end_char"],
                "check_mode": "interpretive",
                "response_context": expanded_interpretive,
            },
        )
        jev = _jev_payload(decision)
        if _relation_supports(jev["relation"]):
            suggested = {
                "start_char": candidate["start_char"],
                "end_char": candidate["end_char"],
                "text": candidate["text"],
                "expansion": candidate["expansion"],
            }
            return suggested, jev
    return None, None


def assess_evidence_link(
    *,
    classifier: EvidenceRelationClassifier,
    graph_service: GraphService,
    record: dict[str, Any],
    criterion_id: str,
    start_char: int,
    end_char: int,
    text: str,
    evidence_id: str | None = None,
    search_additional: bool = True,
) -> dict[str, Any]:
    """Run graph → Jev assessment for a span/criterion pair without intervention policy."""
    from app.intervention import build_intervention_context

    graph_context = build_intervention_context(graph_service, criterion_id)
    span_id = evidence_id or f"span-{start_char}-{end_char}"
    interpretive_context = build_response_local_context_for_span(
        record,
        start_char=start_char,
        end_char=end_char,
    )
    jev_context_base = {
        "evidence_id": span_id,
        "start_char": start_char,
        "end_char": end_char,
        "context_node_ids": graph_context["context_node_ids"],
        "parent_criterion": graph_context["parent_criterion"],
        "guidance": graph_context["guidance"],
        "question": graph_context["question"],
    }
    result: dict[str, Any] = {
        "criterion_id": criterion_id,
        "criterion": graph_context["criterion"],
        "parent_criterion": graph_context["parent_criterion"],
        "evidence": {
            "evidence_id": span_id,
            "text": text,
            "start_char": start_char,
            "end_char": end_char,
        },
        "interpretive_context": interpretive_context,
        "graph_context": graph_context,
        "jev_direct": None,
        "jev": None,
        "jev_additional": None,
        "suggested_evidence_span": None,
        "additional_evidence": {"searched": False, "found": False, "expansion": None},
        "error": None,
    }

    try:
        direct_decision = classifier.classify(
            text,
            graph_context["criterion"],
            {
                **jev_context_base,
                "check_mode": "interpretive",
                "response_context": interpretive_context,
            },
        )
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)[:500]
        return result

    direct_jev = _jev_payload(direct_decision)
    result["jev_direct"] = direct_jev
    result["jev"] = direct_jev

    if search_additional and should_search_additional_evidence(direct_jev):
        result["additional_evidence"]["searched"] = True
        try:
            suggested_span, additional_jev = search_additional_evidence(
                classifier,
                record=record,
                criterion=graph_context["criterion"],
                jev_context_base=jev_context_base,
                start_char=start_char,
                end_char=end_char,
                interpretive_context=interpretive_context,
            )
        except Exception as exc:  # noqa: BLE001
            result["error"] = str(exc)[:500]
            return result
        if suggested_span and additional_jev:
            result["additional_evidence"]["found"] = True
            result["additional_evidence"]["expansion"] = suggested_span["expansion"]
            result["jev_additional"] = additional_jev
            result["suggested_evidence_span"] = suggested_span

    return result
