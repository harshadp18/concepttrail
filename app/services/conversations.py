"""Tutor conversation history (PROPOSED tables; callers check `doubt_history_enabled`).

Stores the student's question and the tutor's grounded answer or abstention with its citations
(database-derived), per learner. It is history only: it never updates mastery, and prior turns
are used to disambiguate a follow-up question for retrieval, never as evidence for an answer.
Every read is limited to the owning learner; another learner's conversation is "not found".
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.proposed_models import DoubtConversation, DoubtMessage

MAX_TURNS = 40  # messages per conversation; keeps history bounded
CONTEXT_CHARS = 300


class ConversationError(ValueError):
    def __init__(self, code: str, message: str, status: int = 404) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def start(
    session: Session,
    learner_id: uuid.UUID,
    class_level: int,
    subject_id: str | None,
    kc_id: str | None,
) -> DoubtConversation:
    row = DoubtConversation(
        conversation_id=uuid.uuid4(),
        learner_id=learner_id,
        class_level=class_level,
        subject_id=subject_id,
        kc_id=kc_id,
        updated_at=datetime.now(UTC),
    )
    session.add(row)
    session.flush()
    return row


def owned(session: Session, learner_id: uuid.UUID, conversation_id: uuid.UUID) -> DoubtConversation:
    row = session.get(DoubtConversation, conversation_id)
    if row is None or row.learner_id != learner_id or row.archived_at is not None:
        raise ConversationError("conversation_not_found", "The conversation is unavailable.")
    return row


def messages(session: Session, conversation_id: uuid.UUID) -> list[DoubtMessage]:
    return list(
        session.scalars(
            select(DoubtMessage)
            .where(DoubtMessage.conversation_id == conversation_id)
            .order_by(DoubtMessage.seq)
        )
    )


def previous_student_question(session: Session, conversation_id: uuid.UUID) -> str | None:
    """The latest earlier student question, used only to disambiguate a follow-up."""
    text = session.scalar(
        select(DoubtMessage.content)
        .where(DoubtMessage.conversation_id == conversation_id, DoubtMessage.role == "student")
        .order_by(DoubtMessage.seq.desc())
        .limit(1)
    )
    return text[:CONTEXT_CHARS] if text else None


def append_exchange(
    session: Session,
    conversation: DoubtConversation,
    question: str,
    answer_text: str,
    *,
    status: str,
    grounding: str,
    citations: list[dict[str, Any]],
    model_id: str | None,
) -> None:
    # Lock the parent row so concurrent requests cannot take the same sequence numbers.
    session.execute(
        select(DoubtConversation.conversation_id)
        .where(DoubtConversation.conversation_id == conversation.conversation_id)
        .with_for_update()
    )
    last = (
        session.scalar(
            select(func.max(DoubtMessage.seq)).where(
                DoubtMessage.conversation_id == conversation.conversation_id
            )
        )
        or 0
    )
    if last + 2 > MAX_TURNS:
        raise ConversationError(
            "conversation_full", "This conversation is full. Start a new one.", 409
        )
    session.add_all(
        [
            DoubtMessage(
                message_id=uuid.uuid4(),
                conversation_id=conversation.conversation_id,
                seq=last + 1,
                role="student",
                content=question,
            ),
            DoubtMessage(
                message_id=uuid.uuid4(),
                conversation_id=conversation.conversation_id,
                seq=last + 2,
                role="tutor",
                content=answer_text,
                grounding=grounding,
                status=status,
                citations=citations,
                model_id=model_id,
            ),
        ]
    )
    conversation.updated_at = datetime.now(UTC)
    session.flush()


def list_for_learner(
    session: Session, learner_id: uuid.UUID, *, limit: int, offset: int
) -> dict[str, Any]:
    base = select(DoubtConversation).where(
        DoubtConversation.learner_id == learner_id, DoubtConversation.archived_at.is_(None)
    )
    total = session.scalar(select(func.count()).select_from(base.subquery()))
    rows = session.scalars(
        base.order_by(DoubtConversation.updated_at.desc(), DoubtConversation.conversation_id)
        .limit(limit)
        .offset(offset)
    ).all()
    return {"count": int(total or 0), "rows": list(rows)}


def archive(session: Session, learner_id: uuid.UUID, conversation_id: uuid.UUID) -> None:
    row = owned(session, learner_id, conversation_id)
    row.archived_at = datetime.now(UTC)
    session.flush()
