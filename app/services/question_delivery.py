"""Student question delivery: servable, in scope, scorable, answer keys never exposed.

Option order is shuffled deterministically per (learner, question) so a stored answer-position
pattern (for example most keys on "B") is not visible to students, while a reload shows the
same order. True/false keeps its stored order. `option_key` stays the answer identifier; clients
label options by `display_order`, not by key.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.content_release import servable_review_statuses
from app.db.models import KnowledgeComponent, Question, QuestionKc, QuestionOption
from app.services.attempt_service import is_deliverable

ANSWER_SHAPES = {
    "single_choice": "option_key",
    "mcq": "option_key",
    "mcq_single": "option_key",
    "true_false": "option_key",
    "multiple_select": "option_keys",
    "numeric": "value",
}


def _shuffled(options: list[QuestionOption], learner_id: uuid.UUID, question_id: str):
    def rank(o: QuestionOption) -> str:
        return hashlib.sha256(f"{learner_id}|{question_id}|{o.option_key}".encode()).hexdigest()

    return sorted(options, key=rank)


def servable_kc(session: Session, kc_id: str) -> KnowledgeComponent | None:
    kc = session.get(KnowledgeComponent, kc_id)
    return kc if kc is not None and kc.review_status in servable_review_statuses() else None


def deliverable_questions(
    session: Session, kc_id: str, learner_id: uuid.UUID
) -> list[dict[str, Any]]:
    questions = session.scalars(
        select(Question)
        .join(QuestionKc, QuestionKc.question_id == Question.question_id)
        .where(
            QuestionKc.kc_id == kc_id,
            QuestionKc.review_status.in_(servable_review_statuses()),
            Question.review_status.in_(servable_review_statuses()),
            Question.active.is_(True),
        )
        .order_by(Question.difficulty, Question.question_id)
    ).all()
    out = []
    for question in questions:
        options = list(
            session.scalars(
                select(QuestionOption)
                .where(QuestionOption.question_id == question.question_id)
                .order_by(QuestionOption.display_order, QuestionOption.option_key)
            )
        )
        if not is_deliverable(question, options):
            continue
        ordered = (
            options
            if question.item_type == "true_false"
            else _shuffled(options, learner_id, question.question_id)
        )
        out.append(
            {
                "question_id": question.question_id,
                "version": question.version,
                "item_type": question.item_type,
                "answer_shape": ANSWER_SHAPES[question.item_type],
                "stem": question.stem,
                "difficulty": question.difficulty,
                "options": [
                    {
                        "option_key": option.option_key,
                        "option_text": option.option_text,
                        "display_order": position,
                    }
                    for position, option in enumerate(ordered, start=1)
                ],
            }
        )
    return out
