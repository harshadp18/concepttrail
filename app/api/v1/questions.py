"""Read-only delivery of servable questions for a knowledge component in the learner's scope."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_learner
from app.db.models import Learner
from app.db.session import get_db
from app.services import learner_scope
from app.services.question_delivery import deliverable_questions, servable_kc

router = APIRouter(tags=["questions"])


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": "topic_not_found", "message": "The requested topic is unavailable."},
    )


@router.get("/topics/{kc_id}/questions")
def list_topic_questions(
    kc_id: str,
    limit: int = Query(default=10, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),  # noqa: B008
    learner: Learner = Depends(get_current_learner),  # noqa: B008
) -> dict[str, Any]:
    """Return active, servable questions without answer keys.

    Student-only. The KC must be in the learner's enrolled scope (an out-of-scope KC is
    reported as not found). Only questions the server can score are listed; `answer_shape`
    names the `submitted_answer` field to send. Options are listed in `display_order`.
    """
    if servable_kc(session, kc_id) is None:
        raise _not_found()
    access = learner_scope.learner_access(session, learner.learner_id)
    if not access.enrolled:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "enrollment_required",
                "message": "An active class enrollment is required.",
            },
        )
    if not learner_scope.can_access_kc(session, access, kc_id):
        raise _not_found()
    questions = deliverable_questions(session, kc_id, learner.learner_id)
    return {
        "kc_id": kc_id,
        "count": len(questions),
        "limit": limit,
        "offset": offset,
        "questions": questions[offset : offset + limit],
    }
