"""Teacher Bell-Ringer: topic-level analysis and topic-specific cycles; class mastery heatmap.

Every route requires a teacher with an active assignment to `{class_id}`; the analysis and
heatmap only ever read learners actively enrolled in that class. The analysis and heatmap are
read-only and always available. Cycles use the PROPOSED table
`db/proposals/0004_bell_ringer_cycle.py` and answer 503 `feature_not_enabled` unless
BELL_RINGER_ENABLED=true (after owner approval). Owner-added routes pending teammate sign-off.
Logic lives in `app.services.bell_ringer`.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.dependencies import require_teacher_classroom_assignment
from app.core.config import get_settings
from app.db.models import Classroom, User
from app.db.session import get_db
from app.services import bell_ringer

router = APIRouter(tags=["teacher-bell-ringer"])


class CycleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kc_id: str = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=2000)
    window_days: int | None = Field(default=None, ge=1, le=365)


class CycleStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["in_progress", "completed", "cancelled"]


def _classroom(session: Session, class_id: uuid.UUID) -> Classroom:
    classroom = session.get(Classroom, class_id)
    if classroom is None or classroom.active is not True:
        raise HTTPException(
            404,
            {"code": "classroom_not_found", "message": "The requested classroom is unavailable."},
        )
    return classroom


def _enabled() -> None:
    if not get_settings().bell_ringer_enabled:
        raise HTTPException(
            503,
            {
                "code": "feature_not_enabled",
                "message": "Saving Bell-Ringer cycles awaits approval of the database migration.",
            },
        )


def _fail(exc: bell_ringer.BellRingerError) -> HTTPException:
    return HTTPException(exc.status, {"code": exc.code, "message": exc.message})


@router.get("/teacher/classes/{class_id}/bell-ringer/topics")
def get_bell_ringer_topics(
    class_id: uuid.UUID,
    subject_id: str | None = Query(default=None, max_length=100),
    window_days: int | None = Query(default=None, ge=1, le=365),
    _user: User = Depends(require_teacher_classroom_assignment),  # noqa: B008
    session: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    """Every topic of the class level with unique-learner counts; flagged ones carry a card."""
    out = bell_ringer.analyse_topics(
        session, _classroom(session, class_id), subject_id=subject_id, window_days=window_days
    )
    out["cycles_enabled"] = get_settings().bell_ringer_enabled
    return out


@router.get("/teacher/classes/{class_id}/heatmap")
def get_class_heatmap(
    class_id: uuid.UUID,
    subject_id: str | None = Query(default=None, max_length=100),
    item_id: str | None = Query(default=None, max_length=200),
    window_days: int | None = Query(default=None, ge=1, le=365),
    _user: User = Depends(require_teacher_classroom_assignment),  # noqa: B008
    session: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    """Learners x topics of the class level: current estimate, evidence and attempt counts."""
    return bell_ringer.class_heatmap(
        session,
        _classroom(session, class_id),
        subject_id=subject_id,
        item_id=item_id,
        window_days=window_days,
    )


@router.get("/teacher/classes/{class_id}/bell-ringer/cycles")
def list_bell_ringer_cycles(
    class_id: uuid.UUID,
    status: Literal["planned", "in_progress", "completed", "cancelled"] | None = Query(
        default=None
    ),
    _user: User = Depends(require_teacher_classroom_assignment),  # noqa: B008
    session: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    _enabled()
    _classroom(session, class_id)
    rows = bell_ringer.list_cycles(session, class_id, status)
    return {"count": len(rows), "cycles": rows}


@router.post("/teacher/classes/{class_id}/bell-ringer/cycles", status_code=201)
def open_bell_ringer_cycle(
    class_id: uuid.UUID,
    payload: CycleCreate,
    response: Response,
    user: User = Depends(require_teacher_classroom_assignment),  # noqa: B008
    session: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    """Open the topic's cycle; if one is already open it is returned with 200 instead."""
    _enabled()
    try:
        view, created = bell_ringer.open_cycle(
            session,
            _classroom(session, class_id),
            user.user_id,
            payload.kc_id,
            payload.note,
            payload.window_days,
        )
    except bell_ringer.BellRingerError as exc:
        raise _fail(exc) from None
    session.commit()
    if not created:
        response.status_code = 200
    view["created"] = created
    return view


@router.get("/teacher/classes/{class_id}/bell-ringer/cycles/{cycle_id}")
def get_bell_ringer_cycle(
    class_id: uuid.UUID,
    cycle_id: uuid.UUID,
    _user: User = Depends(require_teacher_classroom_assignment),  # noqa: B008
    session: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    _enabled()
    try:
        row = bell_ringer.get_cycle(session, class_id, cycle_id)
    except bell_ringer.BellRingerError as exc:
        raise _fail(exc) from None
    return bell_ringer.cycle_detail(session, row)


@router.post("/teacher/classes/{class_id}/bell-ringer/cycles/{cycle_id}/status")
def change_bell_ringer_status(
    class_id: uuid.UUID,
    cycle_id: uuid.UUID,
    payload: CycleStatus,
    _user: User = Depends(require_teacher_classroom_assignment),  # noqa: B008
    session: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    _enabled()
    try:
        row = bell_ringer.update_status(session, class_id, cycle_id, payload.status)
    except bell_ringer.BellRingerError as exc:
        raise _fail(exc) from None
    session.commit()
    return bell_ringer.cycle_detail(session, row)
