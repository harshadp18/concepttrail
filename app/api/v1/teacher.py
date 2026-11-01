"""Teacher dashboard endpoints scoped to active class assignments."""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_teacher_classroom_assignment
from app.db.models import (
    Attempt,
    ClassEnrollment,
    Classroom,
    KnowledgeComponent,
    StudentKcState,
    User,
)
from app.db.session import get_db

router = APIRouter(tags=["teacher"])


@router.get("/teacher/classes/{class_id}/dashboard")
def get_class_dashboard(
    class_id: uuid.UUID,
    _authorized_user: User = Depends(require_teacher_classroom_assignment),  # noqa: B008
    session: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    """Return class-scoped aggregates, never cross-class learner records."""
    classroom = session.get(Classroom, class_id)
    if classroom is None or classroom.active is not True:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "classroom_not_found",
                "message": "The requested classroom is unavailable.",
            },
        )

    learner_ids = session.scalars(
        select(ClassEnrollment.learner_id).where(
            ClassEnrollment.classroom_id == class_id,
            ClassEnrollment.ended_at.is_(None),
            ClassEnrollment.learner_id.is_not(None),
        )
    ).all()
    unique_learner_ids = list(set(learner_ids))

    if not unique_learner_ids:
        return {
            "classroom": {
                "classroom_id": str(classroom.classroom_id),
                "grade_level": classroom.grade_level,
                "section_label": classroom.section_label,
                "academic_session": classroom.academic_session,
            },
            "learner_count": 0,
            "attempt_summary": {"total_attempts": 0, "correct_attempts": 0},
            "topic_signals": [],
        }

    state_rows = session.execute(
        select(StudentKcState, KnowledgeComponent)
        .join(KnowledgeComponent, KnowledgeComponent.kc_id == StudentKcState.kc_id)
        .where(StudentKcState.learner_id.in_(unique_learner_ids))
    ).all()
    grouped: dict[str, list[float]] = defaultdict(list)
    names: dict[str, str | None] = {}
    for state, kc in state_rows:
        if state.mastery_probability is not None:
            grouped[state.kc_id].append(float(state.mastery_probability))
            names[state.kc_id] = kc.name

    attempt_count, correct_count = session.execute(
        select(
            func.count(Attempt.attempt_id),
            func.coalesce(func.sum(case((Attempt.scored_correct.is_(True), 1), else_=0)), 0),
        ).where(Attempt.learner_id.in_(unique_learner_ids))
    ).one()

    topic_signals = []
    for kc_id, values in grouped.items():
        average = sum(values) / len(values)
        topic_signals.append(
            {
                "kc_id": kc_id,
                "topic_name": names.get(kc_id),
                "students_with_estimate": len(values),
                "average_mastery_probability": round(average, 4),
                "below_0_5_count": sum(value < 0.5 for value in values),
            }
        )
    topic_signals.sort(key=lambda row: row["average_mastery_probability"])

    return {
        "classroom": {
            "classroom_id": str(classroom.classroom_id),
            "grade_level": classroom.grade_level,
            "section_label": classroom.section_label,
            "academic_session": classroom.academic_session,
        },
        "learner_count": len(unique_learner_ids),
        "attempt_summary": {
            "total_attempts": int(attempt_count or 0),
            "correct_attempts": int(correct_count or 0),
        },
        "topic_signals": topic_signals,
        "note": "Aggregates are limited to learners with active enrollment in this classroom.",
    }
