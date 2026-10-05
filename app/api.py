from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator

from app.classifier import EvidenceRelationClassifier, JevEvidenceRelationClassifier
from app.conversation import (
    ConversationLLM,
    ConversationStore,
    PromptLoader,
    get_conversation_llm,
    launch_conversation,
    public_conversation,
    send_conversation_message,
    _find_interpretation_for_coding,
)
from app.graph_service import EdgeKindFilter, GraphService
from app.intervention import (
    AIInterpretationStore,
    active_interpretations,
    public_interpretation,
    run_evidence_check,
    update_interpretation_status,
)
from app.judgement import (
    JudgementStore,
    create_coding,
    judgement_view,
    level_context_view,
    remove_coding,
    set_tentative_level,
    update_coding,
)
from app.responses import load_response
from app.stages import resolve_stage
from app.views import (
    assessment_summary,
    candidate_detail_view,
    candidates_list_view,
    dev_responses_list,
    indicative_content_view,
    levels_view,
    list_assessment_ids,
    question_view,
    candidate_view,
    candidate_aliases,
    resolve_response_id,
    _list_response_ids_for_assessment,
)

DATA_DIR = os.getenv("VEA_DATA_DIR", "data")
RESPONSES_DIR = Path(DATA_DIR) / "responses"
JUDGEMENTS_DIR = Path(os.getenv("VEA_JUDGEMENTS_DIR", str(Path(DATA_DIR) / "judgements")))
AI_INTERPRETATIONS_DIR = Path(
    os.getenv("VEA_AI_INTERPRETATIONS_DIR", str(Path(DATA_DIR) / "ai_interpretations"))
)
CONVERSATIONS_DIR = Path(
    os.getenv("VEA_CONVERSATIONS_DIR", str(Path(DATA_DIR) / "conversations"))
)
DEFAULT_ASSESSMENT_ID = os.getenv("VEA_ASSESSMENT_ID", "C-JUN25-8464C1H-02_3")
_evidence_classifier_instance: EvidenceRelationClassifier | None = None
_conversation_llm_instance: ConversationLLM | None = None
_prompt_loader_instance: PromptLoader | None = None

_app_log = logging.getLogger("app")
if not _app_log.handlers:
    _app_log.setLevel(getattr(logging, os.getenv("VEA_LOG_LEVEL", "INFO").upper(), logging.INFO))
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    _app_log.addHandler(_handler)

app = FastAPI(title="VEA Graph API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


@lru_cache(maxsize=8)
def _graph_service(assessment_id: str) -> GraphService:
    if assessment_id not in list_assessment_ids(DATA_DIR):
        raise KeyError(assessment_id)
    return GraphService.from_data_dir(data_dir=DATA_DIR, assessment_id=assessment_id)


@lru_cache(maxsize=8)
def _evidence_pipeline(assessment_id: str):
    from app.evidence import EvidencePipeline

    return EvidencePipeline(data_dir=DATA_DIR, assessment_id=assessment_id)


def _judgement_store() -> JudgementStore:
    return JudgementStore(JUDGEMENTS_DIR)


def _ai_store() -> AIInterpretationStore:
    return AIInterpretationStore(AI_INTERPRETATIONS_DIR)


def _conversation_store() -> ConversationStore:
    return ConversationStore(CONVERSATIONS_DIR)


def _prompt_loader() -> PromptLoader:
    global _prompt_loader_instance
    if _prompt_loader_instance is None:
        _prompt_loader_instance = PromptLoader()
    return _prompt_loader_instance


def _conversation_llm() -> ConversationLLM:
    global _conversation_llm_instance
    if _conversation_llm_instance is None:
        _conversation_llm_instance = get_conversation_llm()
    return _conversation_llm_instance


def _evidence_classifier() -> EvidenceRelationClassifier:
    global _evidence_classifier_instance
    if _evidence_classifier_instance is None:
        _evidence_classifier_instance = JevEvidenceRelationClassifier()
    return _evidence_classifier_instance


def _require_assessment(assessment_id: str) -> GraphService:
    try:
        return _graph_service(assessment_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Assessment not found: {assessment_id}") from None


def _not_found(node_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Node not found: {node_id}")


def _require_session(marking_session_id: str) -> dict:
    try:
        return _judgement_store().get_session(marking_session_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Marking session not found: {marking_session_id}",
        ) from None


def _load_judgement_context(
    marking_session_id: str,
    assessment_id: str,
    candidate_id: str,
) -> tuple[GraphService, dict, dict, dict]:
    _require_session(marking_session_id)
    service = _require_assessment(assessment_id)
    try:
        response_id = resolve_response_id(DATA_DIR, assessment_id, candidate_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Candidate not found: {candidate_id}") from None
    try:
        record = load_response(response_id, responses_dir=RESPONSES_DIR)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Response not found: {response_id}") from None
    store = _judgement_store()
    state = store.load(marking_session_id, assessment_id, response_id)
    return service, record, state, store


def _save_and_view(
    store: JudgementStore,
    state: dict,
    graph_service: GraphService,
) -> dict:
    store.save(state)
    return judgement_view(state, graph_service, DATA_DIR)


def _resolve_evidence(
    assessment_id: str,
    response_id: str,
    segment_id: str | None,
    start_char: int | None,
    end_char: int | None,
):
    try:
        return _evidence_pipeline(assessment_id).resolve_evidence(
            response_id=response_id,
            segment_id=segment_id,
            start_char=start_char,
            end_char=end_char,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Not found: {exc}") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


class EvidenceSelector(BaseModel):
    segment_id: str | None = None
    start_char: int | None = None
    end_char: int | None = None

    @model_validator(mode="after")
    def validate_selector(self) -> EvidenceSelector:
        has_segment = self.segment_id is not None
        has_span = self.start_char is not None or self.end_char is not None
        if has_segment and has_span:
            raise ValueError("Provide either segment_id or start_char/end_char, not both")
        if not has_segment and (self.start_char is None or self.end_char is None):
            raise ValueError("Provide segment_id or both start_char and end_char")
        return self


class CandidatesRequest(EvidenceSelector):
    top_k: int = Field(default=5, ge=1, le=50)
    scope: Literal["criteria", "commentary", "question", "all"] = "criteria"


class ClassifyRequest(EvidenceSelector):
    response_id: str
    criterion_id: str
    save: bool = False


class ClassifyTopRequest(EvidenceSelector):
    response_id: str
    top_k: int = Field(default=3, ge=1, le=20)
    scope: Literal["criteria", "commentary", "question", "all"] = "criteria"
    save: bool = False


class CreateMarkingSessionRequest(BaseModel):
    examiner_id: str
    label: str | None = None


class CreateCodingRequest(BaseModel):
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=1)
    text: str
    criterion_id: str


class UpdateCodingRequest(BaseModel):
    criterion_id: str | None = None
    start_char: int | None = Field(default=None, ge=0)
    end_char: int | None = Field(default=None, ge=1)
    text: str | None = None

    @model_validator(mode="after")
    def validate_update(self) -> UpdateCodingRequest:
        span_fields = [self.start_char, self.end_char, self.text]
        if any(value is not None for value in span_fields) and not all(
            value is not None for value in span_fields
        ):
            raise ValueError("Provide start_char, end_char, and text together")
        if self.criterion_id is None and not all(value is not None for value in span_fields):
            raise ValueError("Provide criterion_id and/or a complete span update")
        return self


class TentativeLevelRequest(BaseModel):
    level: int | None = None


class AiCheckRequest(BaseModel):
    stage: str | None = None
    last_action: str | None = None


class AiInterpretationStatusRequest(BaseModel):
    status: Literal["dismissed", "explore"]


class ConversationLaunchRequest(BaseModel):
    source: Literal["explore", "verify", "general"]
    coding_id: str | None = None
    interpretation_id: str | None = None
    stage: str | None = None
    last_action: str | None = None


class ConversationMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


@app.get("/health")
def health() -> dict:
    service = _require_assessment(DEFAULT_ASSESSMENT_ID)
    summary = service.summary()
    return {
        "status": "ok",
        "assessment_id": summary["assessment_id"],
        "node_count": summary["node_count"],
        "edge_count": summary["edge_count"],
        "jev_labels": summary["jev_labels"],
        "assessments": list_assessment_ids(DATA_DIR),
    }


@app.get("/assessments")
def list_assessments() -> dict:
    items = []
    for assessment_id in list_assessment_ids(DATA_DIR):
        service = _graph_service(assessment_id)
        response_ids = _list_response_ids_for_assessment(RESPONSES_DIR, assessment_id)
        items.append(assessment_summary(service, DATA_DIR, response_ids))
    return {"assessments": items}


@app.get("/assessments/{assessment_id}")
def get_assessment(assessment_id: str) -> dict:
    service = _require_assessment(assessment_id)
    response_ids = _list_response_ids_for_assessment(
        RESPONSES_DIR,
        assessment_id,
    )
    overview = service.assessment_overview()
    summary = assessment_summary(service, DATA_DIR, response_ids)
    return {**overview, **summary}


@app.get("/assessments/{assessment_id}/question")
def get_assessment_question(assessment_id: str) -> dict:
    service = _require_assessment(assessment_id)
    return question_view(service, DATA_DIR)


@app.get("/assessments/{assessment_id}/levels")
def get_assessment_levels(assessment_id: str) -> dict:
    service = _require_assessment(assessment_id)
    return levels_view(service, DATA_DIR)


@app.get("/assessments/{assessment_id}/indicative-content")
def get_assessment_indicative_content(assessment_id: str) -> dict:
    service = _require_assessment(assessment_id)
    return indicative_content_view(service)


@app.get("/assessments/{assessment_id}/candidates")
def list_candidates(assessment_id: str) -> dict:
    _require_assessment(assessment_id)
    return {"candidates": candidates_list_view(DATA_DIR, assessment_id)}


@app.get("/assessments/{assessment_id}/candidates/{candidate_id}")
def get_candidate(assessment_id: str, candidate_id: str) -> dict:
    _require_assessment(assessment_id)
    try:
        return candidate_detail_view(DATA_DIR, assessment_id, candidate_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Candidate not found: {candidate_id}") from None


@app.post("/marking-sessions")
def post_marking_session(body: CreateMarkingSessionRequest) -> dict:
    session = _judgement_store().create_session(body.examiner_id, body.label)
    return session


@app.get("/marking-sessions/{marking_session_id}")
def get_marking_session(marking_session_id: str) -> dict:
    return _require_session(marking_session_id)


@app.get(
    "/marking-sessions/{marking_session_id}/assessments/{assessment_id}/candidates/{candidate_id}/judgement"
)
def get_judgement(marking_session_id: str, assessment_id: str, candidate_id: str) -> dict:
    service, _record, state, _store = _load_judgement_context(
        marking_session_id,
        assessment_id,
        candidate_id,
    )
    return judgement_view(state, service, DATA_DIR)


@app.post(
    "/marking-sessions/{marking_session_id}/assessments/{assessment_id}/candidates/{candidate_id}/judgement/codings"
)
def post_judgement_coding(
    marking_session_id: str,
    assessment_id: str,
    candidate_id: str,
    body: CreateCodingRequest,
) -> dict:
    session = _require_session(marking_session_id)
    service, record, state, store = _load_judgement_context(
        marking_session_id,
        assessment_id,
        candidate_id,
    )
    try:
        create_coding(
            state,
            record,
            service,
            start_char=body.start_char,
            end_char=body.end_char,
            text=body.text,
            criterion_id=body.criterion_id,
            examiner_id=session["examiner_id"],
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Criterion not found: {exc}") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return _save_and_view(store, state, service)


@app.patch(
    "/marking-sessions/{marking_session_id}/assessments/{assessment_id}/candidates/{candidate_id}/judgement/codings/{coding_id}"
)
def patch_judgement_coding(
    marking_session_id: str,
    assessment_id: str,
    candidate_id: str,
    coding_id: str,
    body: UpdateCodingRequest,
) -> dict:
    session = _require_session(marking_session_id)
    service, record, state, store = _load_judgement_context(
        marking_session_id,
        assessment_id,
        candidate_id,
    )
    try:
        update_coding(
            state,
            record,
            service,
            coding_id,
            criterion_id=body.criterion_id,
            start_char=body.start_char,
            end_char=body.end_char,
            text=body.text,
            examiner_id=session["examiner_id"],
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Coding not found: {coding_id}") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return _save_and_view(store, state, service)


@app.delete(
    "/marking-sessions/{marking_session_id}/assessments/{assessment_id}/candidates/{candidate_id}/judgement/codings/{coding_id}"
)
def delete_judgement_coding(
    marking_session_id: str,
    assessment_id: str,
    candidate_id: str,
    coding_id: str,
) -> dict:
    session = _require_session(marking_session_id)
    service, _record, state, store = _load_judgement_context(
        marking_session_id,
        assessment_id,
        candidate_id,
    )
    try:
        remove_coding(state, coding_id, examiner_id=session["examiner_id"])
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Coding not found: {coding_id}") from None
    return _save_and_view(store, state, service)


@app.put(
    "/marking-sessions/{marking_session_id}/assessments/{assessment_id}/candidates/{candidate_id}/judgement/tentative-level"
)
def put_tentative_level(
    marking_session_id: str,
    assessment_id: str,
    candidate_id: str,
    body: TentativeLevelRequest,
) -> dict:
    session = _require_session(marking_session_id)
    service, _record, state, store = _load_judgement_context(
        marking_session_id,
        assessment_id,
        candidate_id,
    )
    levels = levels_view(service, DATA_DIR)["levels"]
    try:
        set_tentative_level(
            state,
            levels,
            body.level,
            examiner_id=session["examiner_id"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return _save_and_view(store, state, service)


@app.get(
    "/marking-sessions/{marking_session_id}/assessments/{assessment_id}/candidates/{candidate_id}/ai-interpretations"
)
def list_ai_interpretations(
    marking_session_id: str,
    assessment_id: str,
    candidate_id: str,
) -> dict:
    _require_session(marking_session_id)
    service, record, state, _store = _load_judgement_context(
        marking_session_id,
        assessment_id,
        candidate_id,
    )
    payload = _ai_store().load(marking_session_id, record["response_id"])
    interpretations = [
        public_interpretation(item)
        for item in active_interpretations(payload, state)
    ]
    return {
        "marking_session_id": marking_session_id,
        "assessment_id": assessment_id,
        "interpretations": interpretations,
    }


@app.post(
    "/marking-sessions/{marking_session_id}/assessments/{assessment_id}/candidates/{candidate_id}/judgement/codings/{coding_id}/ai-check"
)
def post_ai_check(
    marking_session_id: str,
    assessment_id: str,
    candidate_id: str,
    coding_id: str,
    body: AiCheckRequest,
) -> dict:
    _require_session(marking_session_id)
    service, record, state, _store = _load_judgement_context(
        marking_session_id,
        assessment_id,
        candidate_id,
    )
    stage, stage_source = resolve_stage(state, body.stage, body.last_action)
    try:
        interpretation = run_evidence_check(
            classifier=_evidence_classifier(),
            graph_service=service,
            record=record,
            judgement_state=state,
            coding_id=coding_id,
            stage=stage,
            stage_source=stage_source,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Coding not found: {coding_id}") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    ai_store = _ai_store()
    payload = ai_store.load(marking_session_id, record["response_id"])
    ai_store.add(payload, interpretation)
    ai_store.save(payload)
    return public_interpretation(interpretation)


@app.patch(
    "/marking-sessions/{marking_session_id}/assessments/{assessment_id}/candidates/{candidate_id}/ai-interpretations/{ai_id}"
)
def patch_ai_interpretation(
    marking_session_id: str,
    assessment_id: str,
    candidate_id: str,
    ai_id: str,
    body: AiInterpretationStatusRequest,
) -> dict:
    _require_session(marking_session_id)
    _service, record, state, _store = _load_judgement_context(
        marking_session_id,
        assessment_id,
        candidate_id,
    )
    ai_store = _ai_store()
    payload = ai_store.load(marking_session_id, record["response_id"])
    try:
        interpretation = update_interpretation_status(
            payload,
            ai_id,
            body.status,
            state,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Interpretation not found: {ai_id}") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    ai_store.save(payload)
    return public_interpretation(interpretation)


@app.get(
    "/marking-sessions/{marking_session_id}/assessments/{assessment_id}/candidates/{candidate_id}/conversation"
)
def get_conversation(
    marking_session_id: str,
    assessment_id: str,
    candidate_id: str,
) -> dict:
    _require_session(marking_session_id)
    _service, record, _state, _store = _load_judgement_context(
        marking_session_id,
        assessment_id,
        candidate_id,
    )
    payload = _conversation_store().load(marking_session_id, record["response_id"])
    payload["assessment_id"] = assessment_id
    return public_conversation(payload)


@app.post(
    "/marking-sessions/{marking_session_id}/assessments/{assessment_id}/candidates/{candidate_id}/conversation/launch"
)
def post_conversation_launch(
    marking_session_id: str,
    assessment_id: str,
    candidate_id: str,
    body: ConversationLaunchRequest,
) -> dict:
    _require_session(marking_session_id)
    service, record, state, _store = _load_judgement_context(
        marking_session_id,
        assessment_id,
        candidate_id,
    )
    interpretation = None
    if body.source != "general":
        if not body.coding_id:
            raise HTTPException(status_code=422, detail="coding_id is required for explore/verify launch.")
        ai_store = _ai_store()
        ai_payload = ai_store.load(marking_session_id, record["response_id"])

        if body.interpretation_id:
            interpretation = next(
                (
                    item
                    for item in ai_payload.get("interpretations", [])
                    if item.get("id") == body.interpretation_id
                ),
                None,
            )
            if interpretation is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Interpretation not found: {body.interpretation_id}",
                )
        else:
            interpretation = _find_interpretation_for_coding(ai_payload, body.coding_id)

        if interpretation is None:
            raise HTTPException(
                status_code=422,
                detail="No AI interpretation available for this coding. Run the evidence check first.",
            )
        if interpretation.get("coding_id") != body.coding_id:
            raise HTTPException(status_code=422, detail="Interpretation does not match coding.")
        if interpretation.get("status") == "error" or interpretation.get("jev") is None:
            raise HTTPException(
                status_code=422,
                detail="AI interpretation is unavailable for conversation.",
            )

    if body.source == "explore":
        try:
            interpretation = update_interpretation_status(
                ai_payload,
                interpretation["id"],
                "explore",
                state,
            )
            ai_store.save(ai_payload)
        except KeyError:
            raise HTTPException(
                status_code=404,
                detail=f"Interpretation not found: {interpretation['id']}",
            ) from None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None

    stage, stage_source = resolve_stage(state, body.stage, body.last_action)
    try:
        return launch_conversation(
            conversation_store=_conversation_store(),
            llm=_conversation_llm(),
            prompt_loader=_prompt_loader(),
            graph_service=service,
            record=record,
            judgement_state=state,
            assessment_id=assessment_id,
            source=body.source,
            coding_id=body.coding_id,
            interpretation=interpretation,
            stage=stage,
            stage_source=stage_source,
            data_dir=str(DATA_DIR),
        )
    except KeyError:
        detail = f"Coding not found: {body.coding_id}" if body.coding_id else "Conversation launch failed."
        raise HTTPException(status_code=404, detail=detail) from None
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None


@app.post(
    "/marking-sessions/{marking_session_id}/assessments/{assessment_id}/candidates/{candidate_id}/conversation/messages"
)
def post_conversation_message(
    marking_session_id: str,
    assessment_id: str,
    candidate_id: str,
    body: ConversationMessageRequest,
) -> dict:
    _require_session(marking_session_id)
    service, record, state, _store = _load_judgement_context(
        marking_session_id,
        assessment_id,
        candidate_id,
    )
    pipeline = _evidence_pipeline(assessment_id)
    retrieval_service = pipeline.retrieval_for_response(record["response_id"])
    try:
        return send_conversation_message(
            conversation_store=_conversation_store(),
            llm=_conversation_llm(),
            prompt_loader=_prompt_loader(),
            marking_session_id=marking_session_id,
            response_id=record["response_id"],
            content=body.content.strip(),
            graph_service=service,
            record=record,
            judgement_state=state,
            classifier=_evidence_classifier(),
            retrieval_service=retrieval_service,
            assessment_id=assessment_id,
            data_dir=str(DATA_DIR),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None


@app.get("/assessments/{assessment_id}/levels/{level}/context")
def get_level_context(
    assessment_id: str,
    level: int,
    marking_session_id: str | None = Query(default=None),
    candidate_id: str | None = Query(default=None),
) -> dict:
    service = _require_assessment(assessment_id)
    state = None
    if marking_session_id is not None and candidate_id is not None:
        _require_session(marking_session_id)
        try:
            response_id = resolve_response_id(DATA_DIR, assessment_id, candidate_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Candidate not found: {candidate_id}") from None
        state = _judgement_store().load(marking_session_id, assessment_id, response_id)
    try:
        return level_context_view(service, DATA_DIR, level, state=state)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.get("/responses")
def list_responses(assessment_id: str | None = Query(default=None)) -> dict:
    aid = assessment_id or DEFAULT_ASSESSMENT_ID
    _require_assessment(aid)
    if assessment_id:
        return {"assessment_id": aid, "responses": dev_responses_list(DATA_DIR, aid)}
    pipeline = _evidence_pipeline(DEFAULT_ASSESSMENT_ID)
    return pipeline.list_responses()


@app.get("/responses/{response_id}")
def get_response(response_id: str) -> dict:
    try:
        record = load_response(response_id, responses_dir=RESPONSES_DIR)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Response not found: {response_id}") from None
    assessment_id = record["assessment_id"]
    response_ids = _list_response_ids_for_assessment(
        RESPONSES_DIR,
        assessment_id,
    )
    aliases = candidate_aliases(response_ids)
    candidate_id = aliases.get(response_id)
    if candidate_id is None:
        raise HTTPException(status_code=404, detail=f"Response not found: {response_id}")
    return candidate_view(record, candidate_id, include_dev=True)


@app.post("/responses/{response_id}/candidates")
def post_candidates(response_id: str, body: CandidatesRequest) -> dict:
    try:
        record = load_response(response_id, responses_dir=RESPONSES_DIR)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Response not found: {response_id}") from None
    assessment_id = record["assessment_id"]
    evidence = _resolve_evidence(assessment_id, response_id, body.segment_id, body.start_char, body.end_char)
    try:
        return _evidence_pipeline(assessment_id).candidates(evidence, top_k=body.top_k, scope=body.scope)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None


@app.get("/criteria/{criterion_id}/context")
def get_criterion_context(criterion_id: str) -> dict:
    try:
        return _evidence_pipeline(DEFAULT_ASSESSMENT_ID).criterion_context(criterion_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Criterion not found: {criterion_id}") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.post("/classify")
def post_classify(body: ClassifyRequest) -> dict:
    try:
        record = load_response(body.response_id, responses_dir=RESPONSES_DIR)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Response not found: {body.response_id}") from None
    evidence = _resolve_evidence(
        record["assessment_id"],
        body.response_id,
        body.segment_id,
        body.start_char,
        body.end_char,
    )
    try:
        return _evidence_pipeline(record["assessment_id"]).classify(
            evidence, body.criterion_id, save=body.save
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Not found: {exc}") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None


@app.post("/classify-top")
def post_classify_top(body: ClassifyTopRequest) -> dict:
    try:
        record = load_response(body.response_id, responses_dir=RESPONSES_DIR)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Response not found: {body.response_id}") from None
    evidence = _resolve_evidence(
        record["assessment_id"],
        body.response_id,
        body.segment_id,
        body.start_char,
        body.end_char,
    )
    try:
        return _evidence_pipeline(record["assessment_id"]).classify_top(
            evidence,
            top_k=body.top_k,
            scope=body.scope,
            save=body.save,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Not found: {exc}") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None


@app.get("/responses/{response_id}/hypotheses")
def get_hypotheses(response_id: str) -> dict:
    try:
        record = load_response(response_id, responses_dir=RESPONSES_DIR)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Response not found: {response_id}") from None
    return _evidence_pipeline(record["assessment_id"]).list_hypotheses(response_id)


@app.get("/graph/nodes/{node_id}")
def get_node(node_id: str) -> dict:
    service = _require_assessment(DEFAULT_ASSESSMENT_ID)
    try:
        return service.get_node(node_id)
    except KeyError:
        raise _not_found(node_id) from None


@app.get("/graph/nodes/{node_id}/neighbors")
def get_neighbors(
    node_id: str,
    relation: str | None = Query(default=None),
    kind: EdgeKindFilter = Query(default="all"),
) -> dict:
    service = _require_assessment(DEFAULT_ASSESSMENT_ID)
    try:
        return {"node_id": node_id, "neighbors": service.get_neighbors(node_id, relation=relation, kind=kind)}
    except KeyError:
        raise _not_found(node_id) from None


@app.get("/graph/nodes/{node_id}/context")
def get_context(
    node_id: str,
    include_structural: bool = Query(default=False),
) -> dict:
    service = _require_assessment(DEFAULT_ASSESSMENT_ID)
    try:
        return service.get_context(node_id, include_structural=include_structural)
    except KeyError:
        raise _not_found(node_id) from None


@app.get("/graph/path")
def find_path(
    source: str = Query(...),
    target: str = Query(...),
    relation: str | None = Query(default=None),
    kind: EdgeKindFilter = Query(default="all"),
) -> dict:
    service = _require_assessment(DEFAULT_ASSESSMENT_ID)
    try:
        path = service.find_path(source, target, relation=relation, kind=kind)
    except KeyError as exc:
        raise _not_found(str(exc)) from None
    return {"source": source, "target": target, "path": path}
