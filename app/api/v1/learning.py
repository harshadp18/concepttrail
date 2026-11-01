"""Chapter topics and the adaptive next step for the signed-in learner.

Scope comes from the learner's active enrollment, never from client-supplied class values.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_learner, get_current_user
from app.db.models import Learner, Subject, User
from app.db.repositories.auth_repository import AuthRepository
from app.db.session import get_db
from app.schemas.learning import ChapterTopics, Recommendation
from app.services import learning

router = APIRouter(tags=["learning"])


@router.get("/curriculum/items/{item_id}/topics", response_model=ChapterTopics)
def get_chapter_topics(
    item_id: str,
    session: Session = Depends(get_db),  # noqa: B008
    user: User = Depends(get_current_user),  # noqa: B008
) -> ChapterTopics:
    """Knowledge components of a chapter. Students see only KCs in their enrolled scope, with
    their own mastery estimate and evidence count."""
    learner = AuthRepository(session).learner_for_user(user.user_id)
    result = learning.chapter_topics(session, item_id, learner.learner_id if learner else None)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "item_not_found", "message": "The requested chapter is unavailable."},
        )
    return ChapterTopics(**result)


@router.get("/student/recommendation", response_model=Recommendation)
def get_recommendation(
    subject_id: str | None = Query(default=None, min_length=1, max_length=100),
    session: Session = Depends(get_db),  # noqa: B008
    learner: Learner = Depends(get_current_learner),  # noqa: B008
) -> Recommendation:
    """The deterministic next learning step (graph, mastery and question availability).

    `status: insufficient_data` with a `reason` is a normal outcome (for example no active
    enrollment, no released graph, everything in scope mastered). Thresholds are provisional.
    """
    if subject_id is not None:
        subject = session.get(Subject, subject_id)
        if subject is None or subject.active is not True:
            raise HTTPException(
                status_code=404,
                detail={"code": "subject_not_found", "message": "The subject is unavailable."},
            )
    out = learning.recommend_for_learner(session, learner.learner_id, subject_id)
    return Recommendation(**out)
