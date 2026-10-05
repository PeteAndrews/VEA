from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.classifier import EvidenceRelationClassifier, RelationDecision
from app.evidence import build_response_local_context_for_span, containing_sentence_span
from app.graph_service import GraphService
from app.views import _split_alternatives

GUIDANCE_RELATIONS = frozenset({"ACCEPTS", "REJECTS", "CONSTRAINS", "CLARIFIES", "REQUIRES"})
ANCHOR_RELATIONS = frozenset({"REJECTS", "CONSTRAINS", "REQUIRES"})
DISAGREEMENT_RELATIONS = frozenset({"PARTIALLY_SUPPORTS", "DOES_NOT_SUPPORT"})
WEAK_RELATIONS = frozenset({"PARTIALLY_SUPPORTS", "DOES_NOT_SUPPORT", "UNCERTAIN"})
SUPPORTED_WITH_ADDITIONAL_EVIDENCE_MESSAGE = (
    "More evidence is needed for this link. The nearby response contains the missing evidence."
)
INTERVENTION_REVIEW_PROBABILITY_THRESHOLD = 0.60
INTERVENTION_REVIEW_TOP_TWO_MARGIN = 0.15
MAX_CONTEXT_ITEMS = 16
MAX_NUANCE_ITEMS = 2
SNIPPET_LENGTH = 160
QUESTION_TEXT_LIMIT = 500
USER_STATUSES = frozenset({"dismissed", "explore"})

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _snippet(text: str, limit: int = SNIPPET_LENGTH) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def _criterion_payload(node: dict[str, Any]) -> dict[str, Any]:
    text = node["text"].strip()
    primary, alternatives = _split_alternatives(text)
    payload: dict[str, Any] = {
        "id": node["id"],
        "node_type": node["node_type"],
        "segment_type": node.get("segment_type"),
        "text": text,
    }
    if alternatives:
        payload["primary"] = primary
        payload["alternatives"] = alternatives
    return payload


def _edge_items(graph_service: GraphService, node_id: str, scope: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for edge in graph_service.graph.in_edges.get(node_id, []):
        if edge["kind"] != "assessment" or edge["relation"] not in GUIDANCE_RELATIONS:
            continue
        neighbor = graph_service.graph.nodes[edge["source"]]
        items.append(
            {
                "node_id": neighbor["id"],
                "node_type": neighbor["node_type"],
                "relation": edge["relation"],
                "direction": "incoming",
                "scope": scope,
                "target_id": node_id,
                "text": neighbor["text"].strip(),
            }
        )
    for edge in graph_service.graph.out_edges.get(node_id, []):
        if edge["kind"] != "assessment" or edge["relation"] not in GUIDANCE_RELATIONS:
            continue
        neighbor = graph_service.graph.nodes[edge["target"]]
        items.append(
            {
                "node_id": neighbor["id"],
                "node_type": neighbor["node_type"],
                "relation": edge["relation"],
                "direction": "outgoing",
                "scope": scope,
                "target_id": node_id,
                "text": neighbor["text"].strip(),
            }
        )
    return items


def _indicative_parent(graph_service: GraphService, node: dict[str, Any]) -> dict[str, Any] | None:
    parent_id = node.get("parent_id")
    if not parent_id or parent_id not in graph_service.graph.nodes:
        return None
    parent = graph_service.graph.nodes[parent_id]
    if parent.get("segment_type") != "indicative_point":
        return None
    return parent


def _indicative_children(graph_service: GraphService, node_id: str) -> list[dict[str, Any]]:
    children = [
        child
        for child in graph_service.graph.nodes.values()
        if child.get("parent_id") == node_id and child.get("segment_type") == "indicative_point"
    ]
    children.sort(key=lambda child: child["order"])
    return children


def _rule_items(graph_service: GraphService, target_ids: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for node_id, node in graph_service.graph.nodes.items():
        if node["node_type"] != "level_rule":
            continue
        for edge in graph_service.graph.out_edges.get(node_id, []):
            if edge["kind"] != "assessment" or edge["relation"] != "REQUIRES":
                continue
            if edge["target"] not in target_ids:
                continue
            items.append(
                {
                    "node_id": node_id,
                    "node_type": "level_rule",
                    "relation": "REQUIRES",
                    "direction": "incoming",
                    "scope": "rule",
                    "target_id": edge["target"],
                    "text": node["text"].strip(),
                }
            )
            for rule_edge in graph_service.graph.in_edges.get(node_id, []):
                if rule_edge["kind"] != "assessment" or rule_edge["relation"] != "CLARIFIES":
                    continue
                commentary = graph_service.graph.nodes[rule_edge["source"]]
                items.append(
                    {
                        "node_id": commentary["id"],
                        "node_type": commentary["node_type"],
                        "relation": "CLARIFIES",
                        "direction": "incoming",
                        "scope": "rule",
                        "target_id": node_id,
                        "text": commentary["text"].strip(),
                    }
                )
    return items


def _question_text(graph_service: GraphService) -> str | None:
    question_nodes = [
        node
        for node in graph_service.graph.nodes.values()
        if node["document_type"] == "question" and not node["structural_only"]
    ]
    question_nodes.sort(key=lambda node: node["order"])
    combined = " ".join(node["text"].strip() for node in question_nodes if node["text"].strip())
    if not combined:
        return None
    if len(combined) > QUESTION_TEXT_LIMIT:
        return combined[: QUESTION_TEXT_LIMIT - 3] + "..."
    return combined


def build_intervention_context(graph_service: GraphService, criterion_id: str) -> dict[str, Any]:
    node = graph_service.get_node(criterion_id)
    if node.get("segment_type") != "indicative_point":
        raise ValueError(f"Node is not an indicative_point criterion: {criterion_id}")

    parent = _indicative_parent(graph_service, node)
    items: list[dict[str, Any]] = []
    items.extend(_edge_items(graph_service, criterion_id, "direct"))
    if parent is not None:
        items.extend(_edge_items(graph_service, parent["id"], "parent"))
    for child in _indicative_children(graph_service, criterion_id):
        items.extend(_edge_items(graph_service, child["id"], "child"))

    rule_targets = [criterion_id] + ([parent["id"]] if parent is not None else [])
    items.extend(_rule_items(graph_service, rule_targets))

    scope_rank = {"direct": 0, "parent": 1, "rule": 2, "child": 3}
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda item: (scope_rank[item["scope"]], item["relation"], item["node_id"])):
        key = (item["node_id"], item["relation"], item["target_id"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    deduped = deduped[:MAX_CONTEXT_ITEMS]

    context_node_ids = [criterion_id]
    if parent is not None:
        context_node_ids.append(parent["id"])
    for item in deduped:
        if item["node_id"] not in context_node_ids:
            context_node_ids.append(item["node_id"])

    return {
        "criterion": _criterion_payload(node),
        "parent_criterion": _criterion_payload(parent) if parent is not None else None,
        "guidance": [
            {
                "relation": item["relation"],
                "direction": item["direction"],
                "scope": item["scope"],
                "node_id": item["node_id"],
                "text": item["text"],
            }
            for item in deduped
        ],
        "items": deduped,
        "question": _question_text(graph_service),
        "context_node_ids": context_node_ids,
    }


def _criterion_id(graph_context: dict[str, Any]) -> str | None:
    criterion = graph_context.get("criterion")
    if not criterion:
        return None
    return criterion["id"]


def popup_guidance_items(graph_context: dict[str, Any]) -> list[dict[str, Any]]:
    """Material guidance that may interrupt the examiner (direct or rule on selected criterion)."""
    criterion_id = _criterion_id(graph_context)
    if criterion_id is None:
        return []

    items: list[dict[str, Any]] = []
    for item in graph_context.get("items", []):
        if item["relation"] not in ANCHOR_RELATIONS:
            continue
        if item["scope"] == "direct" and item["target_id"] == criterion_id:
            items.append(item)
        elif item["scope"] == "rule" and item["target_id"] == criterion_id:
            items.append(item)
    return items


def reanchor_items(graph_context: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in popup_guidance_items(graph_context)
        if item["scope"] == "direct"
    ]


def nuance_items(graph_context: dict[str, Any]) -> list[dict[str, Any]]:
    return popup_guidance_items(graph_context)


def _nuance_payload(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "node_id": item["node_id"],
            "relation": item["relation"],
            "scope": item["scope"],
            "text": _snippet(item["text"]),
        }
        for item in items[:MAX_NUANCE_ITEMS]
    ]


def _criterion_label(graph_context: dict[str, Any]) -> str:
    criterion = graph_context.get("criterion")
    if not criterion:
        return "this criterion"
    return _snippet(criterion["text"].lstrip("•o ").strip(), 80)


def _top_two_margin(probabilities: dict[str, float]) -> float | None:
    sorted_probs = sorted(probabilities.values(), reverse=True)
    if len(sorted_probs) < 2:
        return None
    return sorted_probs[0] - sorted_probs[1]


def intervention_needs_review(decision: dict[str, Any]) -> bool:
    """Examiner-facing borderline check. Ignores Jev's diagnostic needs_review flag."""
    relation = decision["relation"]
    if relation == "UNCERTAIN":
        return True

    probability = float(decision.get("probability", 0.0))
    if probability < INTERVENTION_REVIEW_PROBABILITY_THRESHOLD:
        return True

    probabilities = dict(decision.get("probabilities") or {})
    margin = _top_two_margin(probabilities)
    if margin is not None and margin < INTERVENTION_REVIEW_TOP_TWO_MARGIN:
        return True

    return False


def _intervention_review_reasons(decision: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if decision["relation"] == "UNCERTAIN":
        reasons.append("jev_uncertain")
    probability = float(decision.get("probability", 0.0))
    if probability < INTERVENTION_REVIEW_PROBABILITY_THRESHOLD:
        reasons.append("low_probability")
    probabilities = dict(decision.get("probabilities") or {})
    margin = _top_two_margin(probabilities)
    if margin is not None and margin < INTERVENTION_REVIEW_TOP_TWO_MARGIN:
        reasons.append("close_probabilities")
    return reasons or ["borderline"]


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


def _should_search_additional_evidence(direct_jev: dict[str, Any]) -> bool:
    if _relation_weak(direct_jev["relation"]):
        return True
    return direct_jev["relation"] == "SUPPORTS" and intervention_needs_review(direct_jev)


def _expansion_candidates(
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


def _search_additional_evidence(
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
    for candidate in _expansion_candidates(
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


def decide_intervention(decision: dict[str, Any], graph_context: dict[str, Any]) -> dict[str, Any]:
    relation = decision["relation"]
    reanchors = reanchor_items(graph_context)
    nuances = nuance_items(graph_context)
    criterion = _criterion_label(graph_context)

    if intervention_needs_review(decision):
        return {
            "type": "REVIEW",
            "reasons": _intervention_review_reasons(decision),
            "message": (
                f"Jev could not reliably decide whether this evidence supports '{criterion}'. "
                "Worth a second look."
            ),
            "nuance_items": [],
        }

    if relation in DISAGREEMENT_RELATIONS and reanchors:
        return {
            "type": "REANCHOR",
            "reasons": ["disagreement_with_explicit_guidance"],
            "message": (
                f"Explicit mark-scheme guidance applies to '{criterion}'. "
                "Check this evidence against it before confirming the link."
            ),
            "nuance_items": _nuance_payload(reanchors),
        }

    if relation in DISAGREEMENT_RELATIONS:
        reading = "partially supporting" if relation == "PARTIALLY_SUPPORTS" else "not supporting"
        return {
            "type": "CHALLENGE",
            "reasons": ["jev_disagrees"],
            "message": (
                f"Jev reads this evidence as {reading} '{criterion}'. "
                "Check the full step is evidenced."
            ),
            "nuance_items": [],
        }

    if nuances:
        return {
            "type": "NUANCE",
            "reasons": ["supported_with_material_guidance"],
            "message": (
                f"Jev agrees this supports '{criterion}', but guidance affects how it is applied."
            ),
            "nuance_items": _nuance_payload(nuances),
        }

    return {
        "type": "SILENCE",
        "reasons": ["supported_no_material_guidance"],
        "message": "",
        "nuance_items": [],
    }


class AIInterpretationStore:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    def _path(self, marking_session_id: str, response_id: str) -> Path:
        return self.base_dir / marking_session_id / f"{response_id}.json"

    def load(self, marking_session_id: str, response_id: str) -> dict[str, Any]:
        path = self._path(marking_session_id, response_id)
        if not path.is_file():
            return {
                "schema_version": 1,
                "marking_session_id": marking_session_id,
                "response_id": response_id,
                "interpretations": [],
            }
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)

    def save(self, payload: dict[str, Any]) -> None:
        path = self._path(payload["marking_session_id"], payload["response_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        payload["updated_at"] = _utc_now()
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        os.replace(tmp_path, path)

    def add(self, payload: dict[str, Any], interpretation: dict[str, Any]) -> dict[str, Any]:
        now = _utc_now()
        for existing in payload["interpretations"]:
            if existing["coding_id"] == interpretation["coding_id"] and existing["status"] != "superseded":
                existing["status"] = "superseded"
                existing["superseded_by"] = interpretation["id"]
                existing["updated_at"] = now
        payload["interpretations"].append(interpretation)
        return interpretation

    def find(self, payload: dict[str, Any], ai_id: str) -> dict[str, Any]:
        for interpretation in payload["interpretations"]:
            if interpretation["id"] == ai_id:
                return interpretation
        raise KeyError(ai_id)


def _coding_matches(interpretation: dict[str, Any], relation: dict[str, Any], span: dict[str, Any]) -> bool:
    return (
        interpretation["criterion_id"] == relation["target"]
        and interpretation["start_char"] == span["start_char"]
        and interpretation["end_char"] == span["end_char"]
    )


def active_interpretations(
    payload: dict[str, Any],
    judgement_state: dict[str, Any],
) -> list[dict[str, Any]]:
    spans = {span["id"]: span for span in judgement_state.get("evidence_spans", [])}
    relations = {relation["id"]: relation for relation in judgement_state.get("relations", [])}
    active: list[dict[str, Any]] = []
    for interpretation in payload["interpretations"]:
        if interpretation["status"] == "superseded":
            continue
        relation = relations.get(interpretation["coding_id"])
        if relation is None:
            continue
        span = spans.get(relation["source"])
        if span is None or not _coding_matches(interpretation, relation, span):
            continue
        active.append(interpretation)
    return active


def public_interpretation(interpretation: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in interpretation.items() if key != "response_id"}


def _log_evidence_check(
    interpretation: dict[str, Any],
    *,
    criterion_text: str,
    response_context: dict[str, Any],
) -> None:
    jev_direct = interpretation.get("jev_direct")
    jev_additional = interpretation.get("jev_additional")
    intervention = interpretation.get("intervention") or {}
    additional = interpretation.get("additional_evidence") or {}
    containing = response_context.get("containing_sentence") or (
        (response_context.get("containing_segment") or {}).get("text")
    )
    if jev_direct is None:
        logger.info(
            "ai-check error coding=%s criterion=%s evidence=%r error=%s",
            interpretation["coding_id"],
            interpretation["criterion_id"],
            interpretation["evidence_text"],
            interpretation.get("error"),
        )
        return

    logger.info(
        "ai-check coding=%s criterion=%s (%s) evidence=%r context=%r "
        "jev_direct=%s jev_additional=%s intervene=%s additional_found=%s expansion=%s",
        interpretation["coding_id"],
        interpretation["criterion_id"],
        _snippet(criterion_text, 60),
        interpretation["evidence_text"],
        containing,
        jev_direct["relation"],
        jev_additional["relation"] if jev_additional else None,
        intervention.get("type"),
        additional.get("found"),
        additional.get("expansion"),
    )


def run_evidence_check(
    *,
    classifier: EvidenceRelationClassifier,
    graph_service: GraphService,
    record: dict[str, Any],
    judgement_state: dict[str, Any],
    coding_id: str,
    stage: str,
    stage_source: str,
) -> dict[str, Any]:
    relation = next(
        (item for item in judgement_state.get("relations", []) if item["id"] == coding_id),
        None,
    )
    if relation is None:
        raise KeyError(coding_id)
    span = next(
        (item for item in judgement_state.get("evidence_spans", []) if item["id"] == relation["source"]),
        None,
    )
    if span is None:
        raise KeyError(relation["source"])

    graph_context = build_intervention_context(graph_service, relation["target"])
    now = _utc_now()
    interpretation: dict[str, Any] = {
        "id": f"ai-{uuid.uuid4().hex[:8]}",
        "coding_id": coding_id,
        "evidence_id": span["id"],
        "response_id": record["response_id"],
        "start_char": span["start_char"],
        "end_char": span["end_char"],
        "evidence_text": span["text"],
        "criterion_id": relation["target"],
        "examiner_relation": relation["relation"],
        "graph_context": {
            "node_ids": graph_context["context_node_ids"],
            "items": [
                {**item, "text": _snippet(item["text"], 240)} for item in graph_context["items"]
            ],
        },
        "stage": stage,
        "stage_source": stage_source,
        "explore_context": None,
        "created_at": now,
        "updated_at": now,
    }

    interpretive_context = build_response_local_context_for_span(
        record,
        start_char=span["start_char"],
        end_char=span["end_char"],
    )
    interpretation["interpretive_context"] = interpretive_context
    jev_context_base = {
        "evidence_id": span["id"],
        "start_char": span["start_char"],
        "end_char": span["end_char"],
        "context_node_ids": graph_context["context_node_ids"],
        "parent_criterion": graph_context["parent_criterion"],
        "guidance": graph_context["guidance"],
        "question": graph_context["question"],
    }

    try:
        direct_decision: RelationDecision = classifier.classify(
            span["text"],
            graph_context["criterion"],
            {
                **jev_context_base,
                "check_mode": "interpretive",
                "response_context": interpretive_context,
            },
        )
    except Exception as exc:  # noqa: BLE001
        interpretation["jev"] = None
        interpretation["jev_direct"] = None
        interpretation["jev_additional"] = None
        interpretation["additional_evidence"] = None
        interpretation["suggested_evidence_span"] = None
        interpretation["intervention"] = None
        interpretation["status"] = "error"
        interpretation["error"] = str(exc)[:500]
        _log_evidence_check(
            interpretation,
            criterion_text=graph_context["criterion"]["text"],
            response_context=interpretive_context,
        )
        return interpretation

    direct_jev = _jev_payload(direct_decision)
    interpretation["jev_direct"] = direct_jev
    interpretation["jev"] = direct_jev
    interpretation["jev_additional"] = None
    interpretation["suggested_evidence_span"] = None

    intervention: dict[str, Any]
    additional_evidence: dict[str, Any] = {"searched": False, "found": False, "expansion": None}

    if _should_search_additional_evidence(direct_jev):
        additional_evidence["searched"] = True
        try:
            suggested_span, additional_jev = _search_additional_evidence(
                classifier,
                record=record,
                criterion=graph_context["criterion"],
                jev_context_base=jev_context_base,
                start_char=span["start_char"],
                end_char=span["end_char"],
                interpretive_context=interpretive_context,
            )
        except Exception as exc:  # noqa: BLE001
            interpretation["additional_evidence"] = {
                "searched": True,
                "found": False,
                "expansion": None,
                "error": str(exc)[:500],
            }
            interpretation["intervention"] = None
            interpretation["status"] = "error"
            interpretation["error"] = str(exc)[:500]
            _log_evidence_check(
                interpretation,
                criterion_text=graph_context["criterion"]["text"],
                response_context=interpretive_context,
            )
            return interpretation

        if suggested_span and additional_jev:
            additional_evidence["found"] = True
            additional_evidence["expansion"] = suggested_span["expansion"]
            interpretation["jev_additional"] = additional_jev
            interpretation["suggested_evidence_span"] = suggested_span
            intervention = {
                "type": "SUPPORTED_WITH_ADDITIONAL_EVIDENCE",
                "reasons": ["additional_evidence_available"],
                "message": SUPPORTED_WITH_ADDITIONAL_EVIDENCE_MESSAGE,
                "nuance_items": [],
            }
        else:
            intervention = decide_intervention(direct_jev, graph_context)
    else:
        intervention = decide_intervention(direct_jev, graph_context)

    interpretation["additional_evidence"] = additional_evidence
    interpretation["intervention"] = intervention
    interpretation["status"] = "silent" if intervention["type"] == "SILENCE" else "pending"
    _log_evidence_check(
        interpretation,
        criterion_text=graph_context["criterion"]["text"],
        response_context=interpretive_context,
    )
    return interpretation


def build_explore_context(
    interpretation: dict[str, Any],
    judgement_state: dict[str, Any],
) -> dict[str, Any]:
    return {
        "evidence": {
            "evidence_id": interpretation["evidence_id"],
            "text": interpretation["evidence_text"],
            "start_char": interpretation["start_char"],
            "end_char": interpretation["end_char"],
        },
        "criterion_id": interpretation["criterion_id"],
        "examiner_relation": interpretation["examiner_relation"],
        "jev": interpretation.get("jev"),
        "interpretive_context": interpretation.get("interpretive_context"),
        "jev_direct": interpretation.get("jev_direct"),
        "jev_additional": interpretation.get("jev_additional"),
        "suggested_evidence_span": interpretation.get("suggested_evidence_span"),
        "additional_evidence": interpretation.get("additional_evidence"),
        "intervention": interpretation.get("intervention"),
        "graph_context": interpretation["graph_context"],
        "stage": interpretation["stage"],
        "tentative_level": judgement_state.get("tentative_level"),
        "prepared_at": _utc_now(),
    }


def _find_interpretation(payload: dict[str, Any], ai_id: str) -> dict[str, Any]:
    for interpretation in payload["interpretations"]:
        if interpretation["id"] == ai_id:
            return interpretation
    raise KeyError(ai_id)


def update_interpretation_status(
    payload: dict[str, Any],
    ai_id: str,
    status: str,
    judgement_state: dict[str, Any],
) -> dict[str, Any]:
    if status not in USER_STATUSES:
        raise ValueError(f"Unsupported status: {status}")
    interpretation = _find_interpretation(payload, ai_id)
    if interpretation["status"] not in {"pending", "dismissed", "explore"}:
        raise ValueError(f"Interpretation is not actionable: {interpretation['status']}")
    interpretation["status"] = status
    interpretation["updated_at"] = _utc_now()
    if status == "explore":
        interpretation["explore_context"] = build_explore_context(interpretation, judgement_state)
    return interpretation
