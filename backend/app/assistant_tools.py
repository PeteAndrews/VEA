"""Read-only tools and pending-action runtime for the examiner assistant."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from app.assessment import assess_evidence_link
from app.assistant_context import (
    PENDING_ACTION_MAX_STEPS,
    anchor_hash,
    append_working_assessment,
    append_working_search,
    note_criterion_viewed,
)
from app.classifier import EvidenceRelationClassifier
from app.evidence import build_response_local_context_for_span
from app.graph import is_codable_criterion
from app.graph_service import GraphService
from app.intervention import build_intervention_context
from app.judgement import judgement_view, level_context_view
from app.retrieval import RetrievalService

READ_TOOLS = frozenset(
    {
        "search_response",
        "get_response_context",
        "get_node_context",
        "find_support",
        "assess_link",
        "get_judgement_summary",
    }
)
META_TOOLS = frozenset({"propose_action", "resolve_pending_action"})


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def classify_node(graph_service: GraphService, node_id: str) -> dict[str, Any]:
    node = graph_service.get_node(node_id)
    navigable = node.get("segment_type") != "response_segment"
    assessable = node.get("node_type") == "mark_point" and is_codable_criterion(node.get("segment_type"))
    return {"node_id": node_id, "navigable": navigable, "assessable": assessable, "node": node}


def _segment_dict(segment: dict[str, Any]) -> dict[str, Any]:
    return {
        "segment_id": segment.get("segment_id") or segment.get("id"),
        "text": segment["text"],
        "start_char": segment["start_char"],
        "end_char": segment["end_char"],
    }


def lexical_response_matches(record: dict[str, Any], query: str, limit: int = 5) -> list[dict[str, Any]]:
    needle = _normalize(query)
    if len(needle) < 3:
        return []
    matches: list[dict[str, Any]] = []
    for segment in record.get("segments", []):
        if needle in _normalize(segment["text"]):
            matches.append({**_segment_dict(segment), "match_type": "lexical"})
    return matches[:limit]


def _strip_criterion_prefix(text: str) -> str:
    return re.sub(r"^[•o\s]+", "", text).strip()


def _token_set(text: str) -> set[str]:
    stopwords = {"the", "and", "with", "for", "that", "this", "does", "response", "support", "using", "from", "into", "same"}
    return {
        token
        for token in re.findall(r"[a-z0-9]+", _normalize(text))
        if len(token) > 2 and token not in stopwords
    }


def _score_text_overlap(query: str, target: str) -> float:
    query_tokens = _token_set(query)
    target_tokens = _token_set(target)
    if not query_tokens or not target_tokens:
        return 0.0
    shared = len(query_tokens & target_tokens)
    return max(shared / len(target_tokens), shared / len(query_tokens))


def find_supporting_span(
    *,
    criterion: dict[str, Any],
    record: dict[str, Any],
    retrieval_service: RetrievalService | None,
) -> dict[str, Any] | None:
    criterion_text = _strip_criterion_prefix(criterion.get("text", ""))
    if retrieval_service is not None:
        search = retrieval_service.search_response(record["response_id"], criterion_text or criterion.get("text", ""), top_k=5)
        if search.get("matches"):
            return search["matches"][0]
    for match in lexical_response_matches(record, criterion_text, limit=10):
        return match
    best_segment = None
    best_score = 0.0
    for segment in record.get("segments", []):
        score = _score_text_overlap(criterion["text"], segment["text"])
        if score > best_score:
            best_score = score
            best_segment = segment
    if best_segment is not None and best_score >= 0.25:
        return _segment_dict(best_segment)
    return None


def _assessable_children(graph_service: GraphService, node_id: str) -> list[dict[str, Any]]:
    children: list[dict[str, Any]] = []
    for child_id in graph_service.part_of_subtree_ids(node_id):
        if child_id == node_id:
            continue
        info = classify_node(graph_service, child_id)
        if info["assessable"]:
            children.append(
                {
                    "id": child_id,
                    "text": info["node"].get("text"),
                }
            )
    return children


def _response_length(record: dict[str, Any]) -> int:
    segments = record.get("segments") or []
    if not segments:
        return 0
    return max(int(s["end_char"]) for s in segments)


def _validate_span(record: dict[str, Any], start_char: int, end_char: int) -> str | None:
    if start_char < 0 or end_char <= start_char:
        return "Span must have start_char < end_char and start_char >= 0."
    max_end = _response_length(record)
    if max_end and end_char > max_end:
        return f"Span end_char {end_char} exceeds response length {max_end}."
    return None


@dataclass
class ToolRuntime:
    graph_service: GraphService
    record: dict[str, Any]
    judgement_state: dict[str, Any]
    classifier: EvidenceRelationClassifier
    retrieval_service: RetrievalService | None
    data_dir: str
    context: dict[str, Any]
    on_citations: Callable[[list[dict[str, Any]]], None] | None = None

    def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "search_response":
            return self.search_response(args.get("query", ""), int(args.get("top_k") or 5))
        if name == "get_response_context":
            return self.get_response_context(int(args["start_char"]), int(args["end_char"]))
        if name == "get_node_context":
            return self.get_node_context(str(args["node_id"]))
        if name == "find_support":
            return self.find_support(str(args["criterion_id"]))
        if name == "assess_link":
            span = args.get("span") or args
            return self.assess_link(
                int(span["start_char"]),
                int(span["end_char"]),
                str(args["criterion_id"]),
                text=span.get("text"),
            )
        if name == "get_judgement_summary":
            return self.get_judgement_summary()
        if name == "propose_action":
            return self.propose_action(
                goal=str(args.get("goal") or ""),
                targets=args.get("targets") or {},
                steps=args.get("steps") or [],
                label=str(args.get("label") or "Investigation"),
            )
        if name == "resolve_pending_action":
            return self.resolve_pending_action(str(args["action_id"]), str(args.get("decision") or ""))
        return {"error": f"Unknown tool: {name}"}

    def search_response(self, query: str, top_k: int = 5) -> dict[str, Any]:
        lexical = lexical_response_matches(self.record, query, limit=top_k)
        semantic: list[dict[str, Any]] = []
        if self.retrieval_service is not None:
            semantic = self.retrieval_service.search_response(self.record["response_id"], query, top_k=top_k).get("matches", [])
        matches = lexical or semantic
        result = {"query": query, "matches": matches[:top_k]}
        append_working_search(self.context, {"query": query, "match_count": len(matches)})
        if matches and self.on_citations:
            self.on_citations([self._citation_span(matches[0])])
        return result

    def get_response_context(self, start_char: int, end_char: int) -> dict[str, Any]:
        err = _validate_span(self.record, start_char, end_char)
        if err:
            return {"error": err}
        local = build_response_local_context_for_span(self.record, start_char=start_char, end_char=end_char)
        text = ""
        for segment in self.record.get("segments", []):
            if int(segment["start_char"]) <= start_char < int(segment["end_char"]):
                text = segment["text"]
                break
        return {"start_char": start_char, "end_char": end_char, "text": text, "context": local}

    def get_node_context(self, node_id: str) -> dict[str, Any]:
        try:
            info = classify_node(self.graph_service, node_id)
        except KeyError:
            return {"error": f"Unknown node_id: {node_id}"}
        if not info["navigable"]:
            return {"error": "Node is not part of the assessment graph."}
        note_criterion_viewed(self.context, node_id)
        ctx = self.graph_service.get_context(node_id)
        payload: dict[str, Any] = {
            "node_id": node_id,
            "assessable": info["assessable"],
            "node": {
                "id": node_id,
                "text": info["node"].get("text"),
                "node_type": info["node"].get("node_type"),
            },
            "parent": ctx.get("parent"),
            "children": ctx.get("children"),
            "incoming": ctx.get("incoming"),
            "outgoing": ctx.get("outgoing"),
        }
        if info["assessable"]:
            graph_context = build_intervention_context(self.graph_service, node_id)
            payload["guidance"] = (graph_context.get("guidance") or [])[:6]
            payload["question"] = graph_context.get("question")
        else:
            payload["assessable_children"] = _assessable_children(self.graph_service, node_id)
        return payload

    def find_support(self, criterion_id: str) -> dict[str, Any]:
        info = classify_node(self.graph_service, criterion_id)
        if not info["assessable"]:
            return {
                "error": "find_support requires an assessable mark point.",
                "assessable_children": _assessable_children(self.graph_service, criterion_id),
            }
        criterion = info["node"]
        span = find_supporting_span(criterion=criterion, record=self.record, retrieval_service=self.retrieval_service)
        if span is None:
            return {"criterion_id": criterion_id, "span": None, "assessment": None}
        assessment = self._run_assessment(criterion_id, span)
        append_working_assessment(
            self.context,
            {"tool": "find_support", "criterion_id": criterion_id, "span": span, "relation": (assessment or {}).get("relation")},
        )
        return {"criterion_id": criterion_id, "span": span, "assessment": assessment}

    def assess_link(
        self,
        start_char: int,
        end_char: int,
        criterion_id: str,
        *,
        text: str | None = None,
    ) -> dict[str, Any]:
        err = _validate_span(self.record, start_char, end_char)
        if err:
            return {"error": err}
        info = classify_node(self.graph_service, criterion_id)
        if not info["assessable"]:
            return {
                "error": "assess_link requires an assessable mark point.",
                "assessable_children": _assessable_children(self.graph_service, criterion_id),
            }
        span = {"start_char": start_char, "end_char": end_char, "text": text or ""}
        if not span["text"]:
            for segment in self.record.get("segments", []):
                if int(segment["start_char"]) <= start_char < int(segment["end_char"]):
                    span["text"] = segment["text"]
                    span["segment_id"] = segment["id"]
                    break
        assessment = self._run_assessment(criterion_id, span)
        append_working_assessment(
            self.context,
            {"tool": "assess_link", "criterion_id": criterion_id, "span": span, "relation": (assessment or {}).get("relation")},
        )
        return {"criterion_id": criterion_id, "span": span, "assessment": assessment}

    def get_judgement_summary(self) -> dict[str, Any]:
        view = judgement_view(self.judgement_state, self.graph_service, self.data_dir)
        level_ctx = level_context_view(self.judgement_state, self.graph_service, self.data_dir)
        return {
            "codings": view.get("codings", []),
            "tentative_level": view.get("tentative_level"),
            "level_context": level_ctx,
        }

    def _run_assessment(self, criterion_id: str, span: dict[str, Any]) -> dict[str, Any] | None:
        assessment = assess_evidence_link(
            classifier=self.classifier,
            graph_service=self.graph_service,
            record=self.record,
            criterion_id=criterion_id,
            start_char=int(span["start_char"]),
            end_char=int(span["end_char"]),
            text=span.get("text") or "",
            evidence_id=span.get("segment_id"),
            search_additional=False,
        )
        jev = assessment.get("jev") or {}
        compact = {
            "relation": jev.get("relation"),
            "criterion_id": criterion_id,
            "criterion_text": (assessment.get("criterion") or {}).get("text"),
            "evidence_text": (assessment.get("evidence") or {}).get("text"),
            "start_char": span.get("start_char"),
            "end_char": span.get("end_char"),
        }
        if self.on_citations:
            self.on_citations(
                [
                    self._citation_span(assessment["evidence"]),
                    self._citation_criterion(assessment["criterion"]),
                ]
            )
        state = self.context.setdefault("state", {})
        if compact.get("criterion_id"):
            state["focus"] = {
                "criterion_id": compact["criterion_id"],
                "span": {"start_char": span["start_char"], "end_char": span["end_char"]},
            }
        return compact

    def _citation_span(self, span: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "response_span",
            "segment_id": span.get("segment_id") or span.get("evidence_id"),
            "start_char": span.get("start_char"),
            "end_char": span.get("end_char"),
            "text": span.get("text"),
        }

    def _citation_criterion(self, criterion: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "criterion",
            "criterion_id": criterion.get("id"),
            "text": criterion.get("text"),
        }

    def propose_action(
        self,
        *,
        goal: str,
        targets: dict[str, Any],
        steps: list[dict[str, Any]],
        label: str,
    ) -> dict[str, Any]:
        validation = self._validate_action_plan(targets=targets, steps=steps)
        if validation:
            return {"error": validation}
        state = self.context.setdefault("state", {})
        pending = state.setdefault("pending_actions", [])
        node_ids = list(targets.get("node_ids") or [])
        for existing in pending:
            if existing.get("status") in {"declined", "done"} and existing.get("goal") == goal and existing.get("targets", {}).get("node_ids") == node_ids:
                return {"error": "This investigation was already completed or declined in this tab."}
        for existing in pending:
            if existing.get("status") == "offered" and existing.get("targets", {}).get("node_ids") == node_ids:
                existing["status"] = "expired"
        action = {
            "id": _new_id("act"),
            "label": label,
            "status": "offered",
            "goal": goal,
            "targets": targets,
            "steps": steps,
            "offered_turn": int(state.get("turn") or 0),
            "anchor_hash": self.context.get("anchor_hash") or anchor_hash(self.context.get("anchor") or {}),
            "results": [],
        }
        pending.append(action)
        return {"action_id": action["id"], "status": "offered", "label": label}

    def resolve_pending_action(self, action_id: str, decision: str) -> dict[str, Any]:
        state = self.context.setdefault("state", {})
        pending = state.setdefault("pending_actions", [])
        action = next((item for item in pending if item.get("id") == action_id), None)
        if action is None:
            return {"error": f"No pending action with id {action_id}."}
        normalized = _normalize(decision)
        if normalized in {"decline", "declined", "no", "no thanks", "not now"}:
            action["status"] = "declined"
            return {"action_id": action_id, "status": "declined", "results": []}
        if normalized not in {"accept", "accepted", "yes", "yes please", "sure", "ok", "okay", "go ahead", "do it"}:
            return {"error": "decision must be accept or decline"}
        invalid = self._validate_action_accept(action)
        if invalid:
            action["status"] = "invalid"
            return {"action_id": action_id, "status": "invalid", "error": invalid, "results": []}
        results = self._execute_action_steps(action)
        action["results"] = results
        action["status"] = "done"
        return {"action_id": action_id, "status": "done", "results": results}

    def _validate_action_plan(self, *, targets: dict[str, Any], steps: list[dict[str, Any]]) -> str | None:
        if not steps:
            return "At least one step is required."
        if len(steps) > PENDING_ACTION_MAX_STEPS:
            return f"At most {PENDING_ACTION_MAX_STEPS} steps allowed."
        for node_id in targets.get("node_ids") or []:
            try:
                classify_node(self.graph_service, node_id)
            except KeyError:
                return f"Unknown target node: {node_id}"
        for index, step in enumerate(steps):
            tool = step.get("tool")
            if tool in META_TOOLS:
                return "propose_action and resolve_pending_action cannot be action steps."
            if tool not in READ_TOOLS:
                return f"Unsupported step tool: {tool}"
            args = dict(step.get("args") or {})
            if tool in {"find_support", "assess_link"}:
                cid = args.get("criterion_id")
                if cid:
                    info = classify_node(self.graph_service, cid)
                    if not info["assessable"]:
                        return f"Step {index + 1} assesses non-assessable node {cid}."
            if tool == "assess_link":
                span = args.get("span") or args
                if isinstance(span, dict) and "from_step" not in span:
                    err = _validate_span(self.record, int(span.get("start_char", -1)), int(span.get("end_char", -1)))
                    if err:
                        return f"Step {index + 1}: {err}"
        return None

    def _validate_action_accept(self, action: dict[str, Any]) -> str | None:
        if self.context.get("anchor_status") == "coding_removed":
            return "The linked coding was removed; this action is no longer valid."
        expected = action.get("anchor_hash")
        current = self.context.get("anchor_hash")
        if expected and current and expected != current:
            return "The conversation anchor changed since this action was offered."
        plan_err = self._validate_action_plan(targets=action.get("targets") or {}, steps=action.get("steps") or [])
        if plan_err:
            return plan_err
        coding_id = (self.context.get("anchor") or {}).get("coding_id")
        if coding_id and not _coding_exists(self.judgement_state, coding_id):
            return "The coding this tab was anchored to is no longer present."
        return None

    def _execute_action_steps(self, action: dict[str, Any]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for index, step in enumerate(action.get("steps") or []):
            tool = step["tool"]
            args = self._resolve_step_args(step.get("args") or {}, results)
            try:
                result = self.dispatch(tool, args)
            except Exception as exc:  # noqa: BLE001 — surfaced to model as step error
                result = {"error": str(exc)}
            results.append({"step": index, "tool": tool, "args": args, "result": result})
        return results

    def _resolve_step_args(self, args: dict[str, Any], prior: list[dict[str, Any]]) -> dict[str, Any]:
        resolved: dict[str, Any] = {}
        for key, value in args.items():
            resolved[key] = self._resolve_value(value, prior)
        return resolved

    def _resolve_value(self, value: Any, prior: list[dict[str, Any]]) -> Any:
        if isinstance(value, dict) and "from_step" in value:
            step_index = int(value["from_step"])
            field = value.get("field", "")
            if step_index < 0 or step_index >= len(prior):
                return None
            result = prior[step_index].get("result") or {}
            current: Any = result
            for part in str(field).split("."):
                if not part:
                    continue
                if isinstance(current, dict):
                    current = current.get(part)
                else:
                    return None
            if isinstance(current, dict) and value.get("pick") == "span" and "start_char" in current:
                return current
            return current
        if isinstance(value, dict):
            return {k: self._resolve_value(v, prior) for k, v in value.items()}
        if isinstance(value, list):
            return [self._resolve_value(item, prior) for item in value]
        return value


def goal_safe(steps: list[Any]) -> bool:
    return bool(steps)


def _coding_exists(judgement_state: dict[str, Any], coding_id: str) -> bool:
    for item in judgement_state.get("codings", []):
        if item.get("id") == coding_id:
            return True
    for item in judgement_state.get("relations", []):
        if item.get("id") == coding_id:
            return True
    return False


def tool_schemas() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": "search_response",
            "description": "Search the candidate response for text matching a query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
        {
            "type": "function",
            "name": "get_response_context",
            "description": "Local context around a character span in the response.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_char": {"type": "integer"},
                    "end_char": {"type": "integer"},
                },
                "required": ["start_char", "end_char"],
            },
        },
        {
            "type": "function",
            "name": "get_node_context",
            "description": "Navigate mark scheme structure for any assessment node.",
            "parameters": {
                "type": "object",
                "properties": {"node_id": {"type": "string"}},
                "required": ["node_id"],
            },
        },
        {
            "type": "function",
            "name": "find_support",
            "description": "Find supporting evidence in the response and assess link (assessable criteria only).",
            "parameters": {
                "type": "object",
                "properties": {"criterion_id": {"type": "string"}},
                "required": ["criterion_id"],
            },
        },
        {
            "type": "function",
            "name": "assess_link",
            "description": "Assess whether a specific span supports a criterion (assessable only).",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_char": {"type": "integer"},
                    "end_char": {"type": "integer"},
                    "criterion_id": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["start_char", "end_char", "criterion_id"],
            },
        },
        {
            "type": "function",
            "name": "get_judgement_summary",
            "description": "Current examiner codings and tentative level context.",
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "type": "function",
            "name": "propose_action",
            "description": "Offer a validated multi-step investigation for the examiner to accept.",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "label": {"type": "string"},
                    "targets": {"type": "object"},
                    "steps": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["goal", "steps"],
            },
        },
        {
            "type": "function",
            "name": "resolve_pending_action",
            "description": "Accept or decline a pending investigation by action_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action_id": {"type": "string"},
                    "decision": {"type": "string", "description": "accept or decline"},
                },
                "required": ["action_id", "decision"],
            },
        },
    ]
