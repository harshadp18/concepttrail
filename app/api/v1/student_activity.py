"""Own-student chapter/subject progress, activity history, weak areas and retry list."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_learner
from app.db.models import Learner
from app.db.session import get_db
from app.services import learner_scope, progress_summary

router = APIRouter(tags=["student progress"])


@router.get("/student/progress/chapters")
def get_chapter_progress(
    session: Session = Depends(get_db),  # noqa: B008
    learner: Learner = Depends(get_current_learner),  # noqa: B008
) -> dict[str, Any]:
    """Chapter and subject roll-ups of the learner's own estimates over their enrolled classes.

    A chapter with `topics_started: 0` simply has no evidence yet; the average is then null.
    """
    access = learner_scope.learner_access(session, learner.learner_id)
    out = progress_summary.learner_chapter_progress(
        session, learner.learner_id, access.class_levels
    )
    out["learner_id"] = str(learner.learner_id)
    out["class_levels"] = list(access.class_levels)
    return out


@router.get("/student/activity")
def get_activity(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),  # noqa: B008
    learner: Learner = Depends(get_current_learner),  # noqa: B008
) -> dict[str, Any]:
    """The learner's own recent attempts, newest first, paginated. No answer keys."""
    return progress_summary.recent_activity(session, learner.learner_id, limit=limit, offset=offset)


@router.get("/student/weak-areas")
def get_weak_areas(
    limit: int = Query(default=10, ge=1, le=50),
    session: Session = Depends(get_db),  # noqa: B008
    learner: Learner = Depends(get_current_learner),  # noqa: B008
) -> dict[str, Any]:
    """Topics with enough scored answers and a low estimate, weakest first."""
    access = learner_scope.learner_access(session, learner.learner_id)
    from app.services.learner_scope import accessible_kcs

    mastery = progress_summary.mastery_by_kc(session, [learner.learner_id]).get(
        learner.learner_id, {}
    )
    allowed = accessible_kcs(session, access, list(mastery))
    return {
        "weak_below": progress_summary.WEAK_BELOW,
        "min_evidence": progress_summary.MIN_EVIDENCE_FOR_WEAK,
        "thresholds_provisional": True,
        "weak_areas": progress_summary.weak_areas(session, learner.learner_id, allowed, limit),
        "note": progress_summary.PROGRESS_NOTE,
    }


@router.get("/student/review")
def get_retry_list(
    limit: int = Query(default=20, ge=1, le=50),
    session: Session = Depends(get_db),  # noqa: B008
    learner: Learner = Depends(get_current_learner),  # noqa: B008
) -> dict[str, Any]:
    """Questions the learner most recently got wrong, to retry. Resubmit through `/attempts`
    with a new idempotency key."""
    access = learner_scope.learner_access(session, learner.learner_id)
    return {
        "questions": progress_summary.retry_candidates(session, learner.learner_id, access, limit)
    }
