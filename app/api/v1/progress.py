"""Own-student progress endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_learner
from app.db.models import Attempt, KnowledgeComponent, Learner, StudentKcState
from app.db.session import get_db

router = APIRouter(tags=["student progress"])


@router.get("/student/progress")
def get_student_progress(
    session: Session = Depends(get_db),  # noqa: B008
    learner: Learner = Depends(get_current_learner),  # noqa: B008
) -> dict[str, Any]:
    """Return the authenticated learner's own BKT estimates and attempt totals."""
    state_rows = session.execute(
        select(StudentKcState, KnowledgeComponent)
        .join(KnowledgeComponent, KnowledgeComponent.kc_id == StudentKcState.kc_id)
        .where(StudentKcState.learner_id == learner.learner_id)
        .order_by(StudentKcState.mastery_probability.asc(), KnowledgeComponent.name.asc())
    ).all()
    attempt_count, correct_count = session.execute(
        select(
            func.count(Attempt.attempt_id),
            func.coalesce(func.sum(case((Attempt.scored_correct.is_(True), 1), else_=0)), 0),
        ).where(Attempt.learner_id == learner.learner_id)
    ).one()

    return {
        "learner_id": str(learner.learner_id),
        "attempt_summary": {
            "total_attempts": int(attempt_count or 0),
            "correct_attempts": int(correct_count or 0),
            "incorrect_attempts": int((attempt_count or 0) - (correct_count or 0)),
        },
        "mastery_estimates": [
            {
                "kc_id": state.kc_id,
                "topic_name": kc.name,
                "mastery_probability": state.mastery_probability,
                "evidence_count": state.evidence_count or 0,
                "bkt_config_version": state.bkt_config_version,
                "updated_at": state.updated_at.isoformat() if state.updated_at else None,
            }
            for state, kc in state_rows
        ],
        "note": "Mastery values are model estimates, not grades or fixed ability labels.",
    }
