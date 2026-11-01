"""The signed-in user's own notifications. DISABLED unless NOTIFICATIONS_ENABLED=true.

Owner-side module pending teammate sign-off and owner approval of the additive migration
`db/proposals/0003_notifications_and_doubt_history.py`. While disabled every route answers
503 `feature_not_enabled`. A user can only ever read or mark their own notifications.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.config import get_settings
from app.db.models import User
from app.db.proposed_models import Notification
from app.db.session import get_db
from app.services import notifications

router = APIRouter(tags=["notifications"])


def _enabled() -> None:
    if not get_settings().notifications_enabled:
        raise HTTPException(
            503,
            {
                "code": "feature_not_enabled",
                "message": "Notifications await approval of the database migration.",
            },
        )


def _view(row: Notification) -> dict[str, Any]:
    return {
        "notification_id": str(row.notification_id),
        "kind": row.kind,
        "title": row.title,
        "body": row.body,
        "classroom_id": str(row.classroom_id) if row.classroom_id else None,
        "payload": row.payload,
        "is_synthetic": row.is_synthetic,
        "created_at": row.created_at.isoformat(),
        "read_at": row.read_at.isoformat() if row.read_at else None,
    }


@router.get("/notifications")
def list_notifications(
    unread_only: bool = False,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),  # noqa: B008
    session: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    _enabled()
    page = notifications.list_for_user(
        session, user.user_id, unread_only=unread_only, limit=limit, offset=offset
    )
    return {
        "count": page["count"],
        "unread_count": page["unread_count"],
        "limit": limit,
        "offset": offset,
        "notifications": [_view(r) for r in page["rows"]],
    }


@router.post("/notifications/read-all")
def read_all(
    user: User = Depends(get_current_user),  # noqa: B008
    session: Session = Depends(get_db),  # noqa: B008
) -> dict[str, int]:
    _enabled()
    marked = notifications.mark_all_read(session, user.user_id)
    session.commit()
    return {"marked_read": marked}


@router.post("/notifications/{notification_id}/read")
def read_one(
    notification_id: uuid.UUID,
    user: User = Depends(get_current_user),  # noqa: B008
    session: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    _enabled()
    try:
        row = notifications.mark_read(session, user.user_id, notification_id)
    except notifications.NotificationError as exc:
        raise HTTPException(exc.status, {"code": exc.code, "message": exc.message}) from None
    session.commit()
    return _view(row)
