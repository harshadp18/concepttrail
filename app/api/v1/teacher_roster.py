"""Teacher class list, roster, per-learner progress and class weak areas.

Every route is limited to classes with an active teacher assignment. A learner id in the URL is
only honoured when that learner has an active enrollment in the (authorised) class; otherwise
the learner is reported as not found, never as forbidden.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_role, require_teacher_classroom_assignment
from app.db.models import Attempt, ClassEnrollment, Classroom, Learner, User
from app.db.repositories.auth_repository import AuthRepository
from app.db.session import get_db
from app.services import progress_summary

router = APIRouter(tags=["teacher"])


def _active_learner_ids(session: Session, class_id: uuid.UUID) -> list[uuid.UUID]:
    return sorted(
        set(
            session.scalars(
                select(ClassEnrollment.learner_id).where(
                    ClassEnrollment.classroom_id == class_id,
                    ClassEnrollment.ended_at.is_(None),
                    ClassEnrollment.learner_id.is_not(None),
                )
            )
        )
    )


def _classroom(session: Session, class_id: uuid.UUID) -> Classroom:
    classroom = session.get(Classroom, class_id)
    if classroom is None or classroom.active is not True:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "classroom_not_found",
                "message": "The requested classroom is unavailable.",
            },
        )
    return classroom


@router.get("/teacher/classes")
def list_assigned_classes(
    session: Session = Depends(get_db),  # noqa: B008
    user: User = Depends(require_role("teacher")),  # noqa: B008
) -> dict[str, Any]:
    """The teacher's active classes with learner counts."""
    classes = AuthRepository(session).assigned_classrooms(user.user_id)
    counts = dict(
        session.execute(
            select(
                ClassEnrollment.classroom_id, func.count(func.distinct(ClassEnrollment.learner_id))
            )
            .where(
                ClassEnrollment.classroom_id.in_([c.classroom_id for c in classes]),
                ClassEnrollment.ended_at.is_(None),
            )
            .group_by(ClassEnrollment.classroom_id)
        ).all()
    )
    return {
        "count": len(classes),
        "classes": [
            {
                "classroom_id": str(c.classroom_id),
                "grade_level": c.grade_level,
                "section_label": c.section_label,
                "academic_session": c.academic_session,
                "school_label": c.school_label,
                "learner_count": int(counts.get(c.classroom_id, 0)),
            }
            for c in classes
        ],
    }


@router.get("/teacher/classes/{class_id}/learners")
def list_class_learners(
    class_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _user: User = Depends(require_teacher_classroom_assignment),  # noqa: B008
    session: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    """Enrolled learners with activity and mastery summaries (paginated, ordered by name)."""
    _classroom(session, class_id)
    ids = _active_learner_ids(session, class_id)
    learners = session.scalars(
        select(Learner)
        .where(Learner.learner_id.in_(ids))
        .order_by(Learner.display_name, Learner.learner_id)
    ).all()
    page = learners[offset : offset + limit]
    page_ids = [learner.learner_id for learner in page]
    activity = {
        lid: (int(n), int(c or 0), last)
        for lid, n, c, last in session.execute(
            select(
                Attempt.learner_id,
                func.count(Attempt.attempt_id),
                func.count(Attempt.attempt_id).filter(Attempt.scored_correct.is_(True)),
                func.max(Attempt.attempted_at),
            )
            .where(Attempt.learner_id.in_(page_ids))
            .group_by(Attempt.learner_id)
        )
    }
    states = progress_summary.mastery_by_kc(session, page_ids)
    rows = []
    for learner in page:
        n, c, last = activity.get(learner.learner_id, (0, 0, None))
        values = [
            float(s.mastery_probability)
            for s in states.get(learner.learner_id, {}).values()
            if s.mastery_probability is not None
        ]
        rows.append(
            {
                "learner_id": str(learner.learner_id),
                "display_name": learner.display_name,
                "attempts": n,
                "correct_attempts": c,
                "accuracy": round(c / n, 4) if n else None,
                "topics_started": len(values),
                "average_mastery_probability": (
                    round(sum(values) / len(values), 4) if values else None
                ),
                "last_attempt_at": last.isoformat() if last else None,
            }
        )
    return {
        "count": len(learners),
        "limit": limit,
        "offset": offset,
        "learners": rows,
        "note": progress_summary.PROGRESS_NOTE,
    }


@router.get("/teacher/classes/{class_id}/learners/{learner_id}/progress")
def get_class_learner_progress(
    class_id: uuid.UUID,
    learner_id: uuid.UUID,
    _user: User = Depends(require_teacher_classroom_assignment),  # noqa: B008
    session: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    """One enrolled learner's chapter/subject progress, weak areas and recent activity."""
    classroom = _classroom(session, class_id)
    if learner_id not in _active_learner_ids(session, class_id):
        raise HTTPException(
            status_code=404,
            detail={"code": "learner_not_found", "message": "The learner is not in this class."},
        )
    learner = session.get(Learner, learner_id)
    levels = [int(classroom.grade_level)] if classroom.grade_level is not None else []
    out = progress_summary.learner_chapter_progress(session, learner_id, levels)
    out.update(
        {
            "learner_id": str(learner_id),
            "display_name": learner.display_name if learner else None,
            "weak_areas": progress_summary.weak_areas(session, learner_id),
            "recent_activity": progress_summary.recent_activity(
                session, learner_id, limit=10, offset=0
            ),
        }
    )
    return out


@router.get("/teacher/classes/{class_id}/weak-areas")
def get_class_weak_areas(
    class_id: uuid.UUID,
    limit: int = Query(default=10, ge=1, le=50),
    _user: User = Depends(require_teacher_classroom_assignment),  # noqa: B008
    session: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    """Topics most learners struggle with: share below 0.5 among learners with enough evidence."""
    _classroom(session, class_id)
    ids = _active_learner_ids(session, class_id)
    rows = progress_summary.class_weak_areas(session, ids)
    return {
        "learner_count": len(ids),
        "weak_below": progress_summary.WEAK_BELOW,
        "min_evidence": progress_summary.MIN_EVIDENCE_FOR_WEAK,
        "thresholds_provisional": True,
        "weak_areas": rows[:limit],
        "note": progress_summary.PROGRESS_NOTE,
    }
