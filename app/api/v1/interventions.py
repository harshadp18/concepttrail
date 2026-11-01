"""Teacher interventions over HTTP. DISABLED unless INTERVENTIONS_ENABLED=true.

Owner-side module pending teammate sign-off and owner approval of the additive migration
`db/proposals/0002_teacher_intervention.py`. While disabled every route answers
503 `feature_not_enabled`. Access requires a teacher with an active assignment to `{class_id}`.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.dependencies import require_teacher_classroom_assignment
from app.core.config import get_settings
from app.db.models import User
from app.db.proposed_models import TeacherIntervention
from app.db.session import get_db
from app.services import interventions, notifications

router = APIRouter(tags=["teacher-interventions"])


class InterventionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intervention_type: Literal[
        "reteach", "small_group", "individual_support", "practice_assignment", "other"
    ]
    kc_id: str | None = Field(default=None, max_length=200)
    learner_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=2000)


class InterventionStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["in_progress", "completed", "cancelled"]


def _enabled() -> None:
    if not get_settings().interventions_enabled:
        raise HTTPException(
            503,
            {
                "code": "feature_not_enabled",
                "message": "Interventions await approval of the database migration.",
            },
        )


def _view(row: TeacherIntervention) -> dict[str, Any]:
    return {
        "intervention_id": str(row.intervention_id),
        "classroom_id": str(row.classroom_id),
        "kc_id": row.kc_id,
        "learner_id": str(row.learner_id) if row.learner_id else None,
        "intervention_type": row.intervention_type,
        "status": row.status,
        "note": row.note,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


def _fail(exc: interventions.InterventionError) -> HTTPException:
    return HTTPException(exc.status, {"code": exc.code, "message": exc.message})


@router.get("/teacher/classes/{class_id}/interventions")
def list_interventions(
    class_id: uuid.UUID,
    status: Literal["planned", "in_progress", "completed", "cancelled"] | None = Query(
        default=None
    ),
    _user: User = Depends(require_teacher_classroom_assignment),  # noqa: B008
    session: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    _enabled()
    rows = interventions.list_for_class(session, class_id, status)
    return {"count": len(rows), "interventions": [_view(r) for r in rows]}


@router.post("/teacher/classes/{class_id}/interventions", status_code=201)
def create_intervention(
    class_id: uuid.UUID,
    payload: InterventionCreate,
    user: User = Depends(require_teacher_classroom_assignment),  # noqa: B008
    session: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    _enabled()
    try:
        row = interventions.create(session, class_id, user.user_id, **payload.model_dump())
    except interventions.InterventionError as exc:
        raise _fail(exc) from None
    if get_settings().notifications_enabled:
        notifications.notify_intervention(session, row, user.user_id, "created")
    session.commit()
    return _view(row)


@router.post("/teacher/classes/{class_id}/interventions/{intervention_id}/status")
def change_status(
    class_id: uuid.UUID,
    intervention_id: uuid.UUID,
    payload: InterventionStatus,
    user: User = Depends(require_teacher_classroom_assignment),  # noqa: B008
    session: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    _enabled()
    try:
        row = interventions.update_status(session, class_id, intervention_id, payload.status)
    except interventions.InterventionError as exc:
        raise _fail(exc) from None
    if get_settings().notifications_enabled:
        notifications.notify_intervention(session, row, user.user_id, "updated")
    session.commit()
    return _view(row)
