"""Attempt submission: one deterministic scoring path for every deliverable question type.

Order: idempotent replay → canonical question/version (servable, active) → learner scope →
type-aware evaluation (`app.services.evaluation`) → immutable attempt row → BKT update for an
eligible single-KC question → one commit. Nothing is written for an invalid or unscorable
answer. True/false questions stored with True/False options accept `{"option_key": ...}` (the
existing client contract) as well as `{"value": bool}`; both are scored against the stored key,
and the key must agree with the options or the question is refused.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.content_release import servable_review_statuses
from app.db.models import Attempt, Question, QuestionOption
from app.services import evaluation, learner_scope
from app.services.mastery import (
    MasteryUpdate,
    lock_learning_state,
    process_attempt,
    single_approved_kc,
)

# Item types a student can be served and scored end to end. `numeric` is deliverable only
# with a verifiable expected answer; free-text types are never auto-scored.
DELIVERABLE_TYPES = (
    "single_choice",
    "mcq",
    "mcq_single",
    "multiple_select",
    "true_false",
    "numeric",
)


class AttemptError(Exception):
    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(code)
        self.code, self.message, self.status = code, message, status


@dataclass(frozen=True)
class AttemptOutcome:
    attempt: Attempt
    mastery: MasteryUpdate | None
    duplicate_replay: bool = False


def _existing(session: Session, key: str) -> Attempt | None:
    return session.scalar(select(Attempt).where(Attempt.idempotency_key == key))


def _replay(existing: Attempt, learner_id: uuid.UUID, question_id: str) -> AttemptOutcome:
    if existing.learner_id != learner_id:
        raise AttemptError("duplicate_attempt", "This idempotency key is already in use.", 409)
    if existing.question_id != question_id:
        raise AttemptError(
            "duplicate_attempt", "This idempotency key belongs to another question.", 409
        )
    return AttemptOutcome(existing, None, duplicate_replay=True)


def question_key(question: Question, options: list[QuestionOption]) -> evaluation.QuestionKey:
    return evaluation.QuestionKey(
        question_id=question.question_id,
        version=question.version or 1,
        item_type=question.item_type or "",
        options=tuple(
            evaluation.Option(o.option_key, o.is_correct is True, o.option_id) for o in options
        ),
        expected_answer=question.expected_answer,
        rubric=question.rubric,
    )


def true_false_key_consistent(question: Question, options: list[QuestionOption]) -> bool:
    """Stored True/False options (if any) must agree with `expected_answer`."""
    expected = (question.expected_answer or {}).get("value")
    if not isinstance(expected, bool):
        return False
    if not options:
        return True
    correct = [o for o in options if o.is_correct is True]
    return (
        len(correct) == 1
        and {o.option_text.strip().casefold() for o in options} == {"true", "false"}
        and (correct[0].option_text.strip().casefold() == "true") is expected
    )


def _normalise(question: Question, options: list[QuestionOption], answer: dict[str, Any]) -> Any:
    if question.item_type == "true_false" and set(answer) == {"option_key"}:
        chosen = [o for o in options if o.option_key == answer["option_key"]]
        if len(chosen) != 1:
            raise AttemptError(
                "invalid_answer_option", "The selected answer option is unavailable.", 422
            )
        return {"value": chosen[0].option_text.strip().casefold() == "true"}
    return answer


def is_deliverable(question: Question, options: list[QuestionOption]) -> bool:
    """A question is served only when this service can score it deterministically."""
    kind = question.item_type
    if kind not in DELIVERABLE_TYPES:
        return False
    if kind == "true_false":
        return true_false_key_consistent(question, options)
    if kind == "numeric":
        key = question_key(question, options)
        probe = evaluation.evaluate_answer(key, {"value": 0})
        return probe.status != "review_required"
    correct = sum(o.is_correct is True for o in options)
    if kind == "multiple_select":
        return correct >= 1 and len(options) >= 2
    return correct == 1 and len(options) >= 2


def submit_attempt(
    session: Session,
    learner_id: uuid.UUID,
    *,
    question_id: str,
    question_version: int,
    submitted_answer: dict[str, Any],
    hint_tier: int,
    idempotency_key: str,
) -> AttemptOutcome:
    existing = _existing(session, idempotency_key)
    if existing is not None:
        return _replay(existing, learner_id, question_id)

    question = session.get(Question, question_id)
    if (
        question is None
        or question.active is not True
        or question.review_status not in servable_review_statuses()
        or question.version != question_version
    ):
        raise AttemptError("question_unavailable", "The requested question is unavailable.", 404)
    access = learner_scope.learner_access(session, learner_id)
    if not access.enrolled:
        raise AttemptError("enrollment_required", "An active class enrollment is required.", 403)
    if not learner_scope.can_access_question(session, access, question_id):
        # Same response as a missing question: do not reveal out-of-scope content.
        raise AttemptError("question_unavailable", "The requested question is unavailable.", 404)

    options = list(
        session.scalars(select(QuestionOption).where(QuestionOption.question_id == question_id))
    )
    if not is_deliverable(question, options):
        if question.item_type not in DELIVERABLE_TYPES:
            raise AttemptError(
                "unsupported_scoring_method",
                "This question type cannot be scored automatically.",
                422,
            )
        raise AttemptError(
            "answer_verification_failed", "The question does not have a verified answer key.", 409
        )

    result = evaluation.evaluate_answer(
        question_key(question, options), _normalise(question, options, submitted_answer)
    )
    if result.status == "invalid":
        code = (
            "invalid_answer_option"
            if result.reason == "unknown_option_key"
            else "invalid_answer_format"
        )
        raise AttemptError(
            code, f"The answer is not valid for this question ({result.reason}).", 422
        )
    if not result.scored:
        raise AttemptError(
            "answer_verification_failed", "The question does not have a verified answer key.", 409
        )

    # Serialise attempts on the same (learner, KC) before timestamping (see mastery module).
    kc_id, kc_count = single_approved_kc(session, question_id)
    if kc_id is not None and kc_count == 1:
        lock_learning_state(session, learner_id, kc_id)
    attempted_at = session.scalar(select(func.clock_timestamp()))
    attempt = Attempt(
        attempt_id=uuid.uuid4(),
        learner_id=learner_id,
        question_id=question.question_id,
        question_version=question.version,
        submitted_answer=submitted_answer,
        scored_correct=result.correct,
        score=result.score,
        score_method=result.score_method,
        hint_tier=hint_tier,
        attempted_at=attempted_at,
        idempotency_key=idempotency_key,
    )
    session.add(attempt)
    try:
        session.flush()
        update = process_attempt(session, attempt)
        session.commit()
    except IntegrityError:
        session.rollback()
        duplicate = _existing(session, idempotency_key)
        if duplicate is not None:
            return _replay(duplicate, learner_id, question_id)
        raise AttemptError(
            "duplicate_attempt", "The attempt could not be recorded with this idempotency key.", 409
        ) from None
    return AttemptOutcome(attempt, update)
