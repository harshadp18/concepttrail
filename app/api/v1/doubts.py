"""`POST /doubts`: an evidence-grounded explanation or hint for the signed-in learner.

Contract (docs/API_CONTRACTS.md): stateless by default (a transcript is stored only when
DOUBT_HISTORY_ENABLED is on, after the owner approves the additive migration); class level
comes from the learner's enrollment (or from the requested KC, which must be in the learner's
scope); citations are built from retrieved database records only; weak evidence, missing
rights, an unavailable local model or an invalid model output are controlled outcomes (HTTP
200 with `grounding: abstained`), never a fabricated answer. Requests are rate-limited per learner.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_learner
from app.core.config import get_settings
from app.core.content_release import demo_enabled
from app.core.rate_limit import RateLimiterUnavailable, get_store, opaque_key
from app.db.models import KnowledgeComponent, Learner, Subject
from app.db.session import get_db
from app.schemas.learning import Citation, DoubtRequest, DoubtResponse
from app.services import conversations, learner_scope, learning
from app.services.ai_generation import PROMPT_VERSION
from app.services.embeddings import OllamaEmbedder
from app.services.llm import LLMNotPermitted, build_llm
from app.services.rights import check_use

router = APIRouter(tags=["doubts"])

MESSAGES = {
    "ok": "Answer grounded in the cited pages.",
    "insufficient_evidence": "The available material does not answer this well enough. "
    "Please ask your teacher.",
    "not_authorized": "The relevant material cannot be used for explanations yet.",
    "model_unavailable": "The explanation service is unavailable right now. Try again later.",
    "model_timeout": "The explanation took too long. Try again later.",
    "invalid_model_output": "A reliable answer could not be produced. Please ask your teacher.",
}


def get_llm():
    try:
        return build_llm()
    except LLMNotPermitted:
        return None


def get_embedder():
    settings = get_settings()
    return OllamaEmbedder(settings.rag_embedding_model, settings.ollama_base_url)


def get_rights_check():
    return check_use


def _error(status: int, code: str, message: str, headers=None) -> HTTPException:
    return HTTPException(
        status_code=status, detail={"code": code, "message": message}, headers=headers
    )


@router.post("/doubts", response_model=DoubtResponse)
def ask_doubt(
    payload: DoubtRequest,
    session: Session = Depends(get_db),  # noqa: B008
    learner: Learner = Depends(get_current_learner),  # noqa: B008
    llm=Depends(get_llm),  # noqa: B008
    embedder=Depends(get_embedder),  # noqa: B008
    rights_check=Depends(get_rights_check),  # noqa: B008
) -> DoubtResponse:
    settings = get_settings()
    access = learner_scope.learner_access(session, learner.learner_id)
    if not access.enrolled:
        raise _error(403, "enrollment_required", "An active class enrollment is required.")

    subject_id = payload.subject_id
    class_level = max(access.class_levels)
    if payload.kc_id is not None:
        kc = session.get(KnowledgeComponent, payload.kc_id)
        if kc is None or not learner_scope.can_access_kc(session, access, payload.kc_id):
            raise _error(404, "topic_not_found", "The requested topic is unavailable.")
        if subject_id is not None and subject_id != kc.subject_id:
            raise _error(422, "invalid_context", "The subject does not match the topic.")
        subject_id = kc.subject_id
        levels = learner_scope.kc_class_levels(session, [payload.kc_id])[payload.kc_id]
        in_class = sorted(lv for lv in levels if lv <= class_level)
        class_level = in_class[-1] if in_class else class_level
    if subject_id is not None:
        subject = session.get(Subject, subject_id)
        if subject is None or subject.active is not True:
            raise _error(404, "subject_not_found", "The subject is unavailable.")

    if not settings.rag_index_generation:
        raise _error(503, "retrieval_not_configured", "Explanations are not available yet.")
    try:
        wait = get_store().hit(
            opaque_key("doubt", str(learner.learner_id)), settings.doubt_requests_per_hour, 3600
        )
    except RateLimiterUnavailable:
        raise _error(503, "rate_limiter_unavailable", "Explanations are unavailable.") from None
    if wait:
        raise _error(
            429,
            "too_many_requests",
            "Too many questions in a short time. Try again later.",
            {"Retry-After": str(wait)},
        )

    release = "demo" if demo_enabled() else "production"
    conversation = None
    context = None
    if settings.doubt_history_enabled:
        try:
            if payload.conversation_id is not None:
                conversation = conversations.owned(
                    session, learner.learner_id, payload.conversation_id
                )
                context = conversations.previous_student_question(
                    session, conversation.conversation_id
                )
            else:
                conversation = conversations.start(
                    session, learner.learner_id, class_level, subject_id, payload.kc_id
                )
        except conversations.ConversationError as exc:
            raise _error(exc.status, exc.code, exc.message) from None
    if llm is None:
        response = DoubtResponse(
            status="model_unavailable",
            grounding="abstained",
            message=MESSAGES["model_unavailable"],
            prompt_version=PROMPT_VERSION,
            content_release=release,
        )
        return _remember(session, conversation, payload.question, response)
    result = learning.explain_for_learner(
        session,
        payload.question,
        llm=llm,
        embedder=embedder,
        index_generation=settings.rag_index_generation,
        check_use=rights_check,
        class_level=class_level,
        subject_id=subject_id,
        hint_only=payload.mode == "hint",
        retrieval_context=context,
    )
    output = result.output if result.status == "ok" else {}
    response = DoubtResponse(
        status=result.status,
        grounding="grounded" if result.status == "ok" else "abstained",
        message=MESSAGES[result.status],
        concept=output.get("concept", ""),
        explanation=output.get("explanation", ""),
        steps=list(output.get("steps", [])),
        hint=output.get("hint", ""),
        citations=[
            Citation(
                label=c["label"],
                source_id=c["source_id"],
                pdf_page_index=c.get("pdf_page_index"),
                printed_page_label=c.get("printed_page_label"),
                item_title=c.get("item_title"),
            )
            for c in result.citations
        ],
        model_id=result.model_id,
        prompt_version=result.prompt_version,
        content_release=release,
    )
    return _remember(session, conversation, payload.question, response)


def _remember(session: Session, conversation, question: str, response: DoubtResponse):
    """Persist the exchange when history is enabled; the response is otherwise unchanged."""
    if conversation is None:
        return response
    answer = response.explanation or response.hint or response.message
    try:
        conversations.append_exchange(
            session,
            conversation,
            question,
            answer,
            status=response.status,
            grounding=response.grounding,
            citations=[c.model_dump() for c in response.citations],
            model_id=response.model_id,
        )
    except conversations.ConversationError as exc:
        raise _error(exc.status, exc.code, exc.message) from None
    session.commit()
    return response.model_copy(update={"conversation_id": str(conversation.conversation_id)})


def _history_enabled() -> None:
    if not get_settings().doubt_history_enabled:
        raise _error(
            503,
            "feature_not_enabled",
            "Conversation history awaits approval of the database migration.",
        )


@router.get("/student/doubts/conversations")
def list_conversations(
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),  # noqa: B008
    learner: Learner = Depends(get_current_learner),  # noqa: B008
) -> dict:
    """The learner's own stored conversations, most recently active first."""
    _history_enabled()
    page = conversations.list_for_learner(session, learner.learner_id, limit=limit, offset=offset)
    return {
        "count": page["count"],
        "limit": limit,
        "offset": offset,
        "conversations": [
            {
                "conversation_id": str(c.conversation_id),
                "class_level": c.class_level,
                "subject_id": c.subject_id,
                "kc_id": c.kc_id,
                "updated_at": c.updated_at.isoformat(),
            }
            for c in page["rows"]
        ],
    }


@router.get("/student/doubts/conversations/{conversation_id}")
def get_conversation(
    conversation_id: uuid.UUID,
    session: Session = Depends(get_db),  # noqa: B008
    learner: Learner = Depends(get_current_learner),  # noqa: B008
) -> dict:
    _history_enabled()
    try:
        conversation = conversations.owned(session, learner.learner_id, conversation_id)
    except conversations.ConversationError as exc:
        raise _error(exc.status, exc.code, exc.message) from None
    return {
        "conversation_id": str(conversation.conversation_id),
        "class_level": conversation.class_level,
        "subject_id": conversation.subject_id,
        "kc_id": conversation.kc_id,
        "messages": [
            {
                "seq": m.seq,
                "role": m.role,
                "content": m.content,
                "grounding": m.grounding,
                "status": m.status,
                "citations": m.citations or [],
                "created_at": m.created_at.isoformat(),
            }
            for m in conversations.messages(session, conversation.conversation_id)
        ],
    }


@router.post("/student/doubts/conversations/{conversation_id}/archive", status_code=204)
def archive_conversation(
    conversation_id: uuid.UUID,
    session: Session = Depends(get_db),  # noqa: B008
    learner: Learner = Depends(get_current_learner),  # noqa: B008
) -> None:
    """Hide a conversation from the learner's list (the row is kept for the retention policy)."""
    _history_enabled()
    try:
        conversations.archive(session, learner.learner_id, conversation_id)
    except conversations.ConversationError as exc:
        raise _error(exc.status, exc.code, exc.message) from None
    session.commit()
