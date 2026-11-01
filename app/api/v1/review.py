"""Teacher question review over HTTP (thin layer on `app.services.question_bank`).

Owner-side integration module pending teammate sign-off (teacher routes are teammate-owned; these
paths did not exist). A teacher sees only questions for the class levels of their active class
assignments and records attributable decisions through `record_question_review`, which enforces:
teacher role, written rationale, no self-review, and approval only of a validated draft. AI-reviewed
demo content therefore cannot be approved by a click: it must first be revalidated as a draft.
Students and unassigned teachers are refused.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.roles import RoleCode
from app.db.models import KnowledgeComponent, Question, QuestionKc, QuestionOption, User
from app.db.repositories.auth_repository import AuthRepository
from app.db.session import get_db
from app.services import learner_scope
from app.services.question_bank import ReviewRefused, record_question_review

router = APIRouter(tags=["teacher-review"])
REVIEWABLE = ("validated_draft", "in_review", "demo_release")


class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approved", "rejected", "revision_required"]
    rationale: str = Field(min_length=5, max_length=2000)


def _teacher_levels(session: Session, user: User) -> set[int]:
    repo = AuthRepository(session)
    if RoleCode.TEACHER.value not in repo.roles_for_user(user.user_id):
        raise HTTPException(
            403, {"code": "forbidden_role", "message": "A teacher account is required."}
        )
    levels = {
        c.grade_level for c in repo.assigned_classrooms(user.user_id) if c.grade_level is not None
    }
    if not levels:
        raise HTTPException(
            403, {"code": "forbidden_classroom", "message": "No active class assignment."}
        )
    return levels


def _question_levels(session: Session, question_id: str) -> set[int]:
    kcs = session.scalars(
        select(QuestionKc.kc_id).where(QuestionKc.question_id == question_id)
    ).all()
    levels: set[int] = set()
    for values in learner_scope.kc_class_levels_any_status(session, kcs).values():
        levels |= values
    return levels


def _view(session: Session, q: Question) -> dict[str, Any]:
    v = q.verification or {}
    kc_ids = session.scalars(
        select(QuestionKc.kc_id).where(QuestionKc.question_id == q.question_id)
    ).all()
    options = sorted(
        session.scalars(select(QuestionOption).where(QuestionOption.question_id == q.question_id)),
        key=lambda o: o.option_key,
    )
    return {
        "question_id": q.question_id,
        "version": q.version,
        "item_type": q.item_type,
        "stem": q.stem,
        "review_status": q.review_status,
        "active": q.active,
        "difficulty": q.difficulty,
        "expected_answer": q.expected_answer,
        "options": [
            {
                "option_key": o.option_key,
                "option_text": o.option_text,
                "is_correct": bool(o.is_correct),
                "explanation": o.explanation,
            }
            for o in options
        ],
        "explanation": (v.get("provenance") or {}).get("explanation"),
        "origin": (v.get("provenance") or {}).get("origin"),
        "source_refs": q.source_refs or [],
        "knowledge_components": [
            {"kc_id": k, "name": getattr(session.get(KnowledgeComponent, k), "name", None)}
            for k in kc_ids
        ],
        "ai_review": v.get("ai_review"),
        "human_reviews": v.get("reviews", []),
    }


@router.get("/teacher/review/questions")
def list_review_queue(
    status: Literal["validated_draft", "in_review", "demo_release"] | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),  # noqa: B008
    user: User = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    """Questions awaiting human review for the class levels the teacher is assigned to.

    Includes answer keys, explanations, sources, KCs, the AI review verdict and prior human reviews
    (teachers only). AI review is shown as such; it is not a human review.
    """
    levels = _teacher_levels(session, user)
    statuses = (status,) if status else REVIEWABLE
    rows = session.scalars(
        select(Question).where(Question.review_status.in_(statuses)).order_by(Question.question_id)
    ).all()
    visible = [q for q in rows if _question_levels(session, q.question_id) & levels]
    page = visible[offset : offset + limit]
    return {
        "count": len(visible),
        "limit": limit,
        "offset": offset,
        "questions": [_view(session, q) for q in page],
    }


@router.post("/teacher/review/questions/{question_id}")
def submit_review(
    question_id: str,
    payload: ReviewDecision,
    session: Session = Depends(get_db),  # noqa: B008
    user: User = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    """Record one attributable review decision. Approval requires a validated draft."""
    levels = _teacher_levels(session, user)
    question = session.get(Question, question_id)
    if question is None or not (_question_levels(session, question_id) & levels):
        raise HTTPException(
            404, {"code": "question_not_found", "message": "The question is unavailable."}
        )
    try:
        new_status = record_question_review(
            session, question_id, user.user_id, payload.decision, payload.rationale
        )
    except ReviewRefused as exc:
        # Refusals happen before any write, so there is nothing to roll back here.
        raise HTTPException(409, {"code": "review_refused", "message": str(exc)}) from None
    session.commit()
    return {
        "question_id": question_id,
        "review_status": new_status,
        "human_reviews": len(
            (session.get(Question, question_id).verification or {}).get("reviews", [])
        ),
    }
