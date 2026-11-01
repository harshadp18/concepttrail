"""Student answer submission: deterministic server-side scoring and eligible BKT updates."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_learner
from app.db.models import Attempt, Learner
from app.db.session import get_db
from app.schemas.attempts import AttemptCreate, AttemptResponse, BKTUpdateResult
from app.services.attempt_service import AttemptError, AttemptOutcome, submit_attempt

router = APIRouter(tags=["assessments"])


def _response(outcome: AttemptOutcome) -> AttemptResponse:
    attempt: Attempt = outcome.attempt
    update = outcome.mastery
    bkt = (
        BKTUpdateResult(updated=False, reason="idempotent_replay_not_reapplied")
        if outcome.duplicate_replay or update is None
        else BKTUpdateResult(
            updated=update.updated,
            reason=update.reason,
            kc_id=update.kc_id,
            mastery_probability=update.mastery_probability,
            config_version=update.config_version,
        )
    )
    return AttemptResponse(
        attempt_id=attempt.attempt_id,
        question_id=attempt.question_id or "",
        question_version=attempt.question_version or 1,
        scored_correct=bool(attempt.scored_correct),
        score=float(attempt.score or 0),
        score_method=attempt.score_method or "unknown",
        bkt=bkt,
        duplicate_replay=outcome.duplicate_replay,
    )


@router.post("/attempts", response_model=AttemptResponse, status_code=status.HTTP_201_CREATED)
def post_attempt(
    payload: AttemptCreate,
    session: Session = Depends(get_db),  # noqa: B008
    learner: Learner = Depends(get_current_learner),  # noqa: B008
) -> AttemptResponse:
    """Score an answer server-side and persist the attempt exactly once.

    Answer shapes by question type: single choice `{"option_key": "C"}`; multiple select
    `{"option_keys": ["A", "D"]}` (exact set, all-or-nothing); true/false `{"option_key": "A"}`
    or `{"value": true}`; numeric `{"value": 3.5}` (stored tolerance). The question must be in
    the learner's enrolled scope. BKT is updated only for a question with exactly one servable
    KC mapping and an active versioned configuration; a correct answer with hint tier >= 2 is
    observed as incorrect.
    """
    try:
        outcome = submit_attempt(
            session,
            learner.learner_id,
            question_id=payload.question_id,
            question_version=payload.question_version,
            submitted_answer=payload.submitted_answer,
            hint_tier=payload.hint_tier,
            idempotency_key=payload.idempotency_key,
        )
    except AttemptError as exc:
        raise HTTPException(
            status_code=exc.status, detail={"code": exc.code, "message": exc.message}
        ) from None
    return _response(outcome)
