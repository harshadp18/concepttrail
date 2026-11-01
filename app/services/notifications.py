"""Per-user notifications (PROPOSED `notification` table; callers check `notifications_enabled`).

Producers are deterministic: a notification is written because a stored fact changed (an
intervention was created or closed, a class crossed the weak-topic cut-off). A language model
never writes or ranks notifications. `dedupe_key` makes every producer idempotent: running the
same job twice creates nothing new.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import TeacherClassAssignment
from app.db.proposed_models import NOTIFICATION_KINDS, Notification, TeacherIntervention
from app.services import progress_summary

ALERT_MIN_LEARNERS = 3
ALERT_MIN_SHARE = 0.5


class NotificationError(ValueError):
    def __init__(self, code: str, message: str, status: int = 404) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def create(
    session: Session,
    user_id: uuid.UUID,
    kind: str,
    title: str,
    body: str | None = None,
    *,
    classroom_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
    synthetic: bool = False,
) -> Notification | None:
    """Insert one notification; returns None when `dedupe_key` already exists for the user."""
    if kind not in NOTIFICATION_KINDS:
        raise NotificationError("invalid_notification_kind", "Unknown notification kind.", 422)
    if dedupe_key is not None and session.scalar(
        select(Notification.notification_id).where(
            Notification.user_id == user_id, Notification.dedupe_key == dedupe_key
        )
    ):
        return None
    row = Notification(
        notification_id=uuid.uuid4(),
        user_id=user_id,
        classroom_id=classroom_id,
        kind=kind,
        title=title[:200],
        body=body,
        payload=payload,
        dedupe_key=dedupe_key,
        is_synthetic=synthetic,
    )
    session.add(row)
    session.flush()
    return row


def list_for_user(
    session: Session, user_id: uuid.UUID, *, unread_only: bool, limit: int, offset: int
) -> dict[str, Any]:
    query = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    rows = session.scalars(
        query.order_by(Notification.created_at.desc(), Notification.notification_id)
        .limit(limit)
        .offset(offset)
    ).all()
    unread = session.scalar(
        select(func.count(Notification.notification_id)).where(
            Notification.user_id == user_id, Notification.read_at.is_(None)
        )
    )
    return {"count": int(total or 0), "unread_count": int(unread or 0), "rows": list(rows)}


def mark_read(session: Session, user_id: uuid.UUID, notification_id: uuid.UUID) -> Notification:
    row = session.get(Notification, notification_id)
    if row is None or row.user_id != user_id:  # another user's notification is "not found"
        raise NotificationError("notification_not_found", "The notification is unavailable.")
    if row.read_at is None:
        row.read_at = datetime.now(UTC)
        session.flush()
    return row


def mark_all_read(session: Session, user_id: uuid.UUID) -> int:
    now = datetime.now(UTC)
    rows = session.scalars(
        select(Notification).where(Notification.user_id == user_id, Notification.read_at.is_(None))
    ).all()
    for row in rows:
        row.read_at = now
    session.flush()
    return len(rows)


def _teachers(session: Session, classroom_id: uuid.UUID) -> list[uuid.UUID]:
    return sorted(
        session.scalars(
            select(TeacherClassAssignment.user_id).where(
                TeacherClassAssignment.classroom_id == classroom_id,
                TeacherClassAssignment.ended_at.is_(None),
            )
        )
    )


def notify_intervention(
    session: Session, intervention: TeacherIntervention, actor_id: uuid.UUID, event: str
) -> int:
    """Tell the OTHER teachers of the class that an intervention was created or changed."""
    written = 0
    for teacher_id in _teachers(session, intervention.classroom_id):
        if teacher_id == actor_id:
            continue
        made = create(
            session,
            teacher_id,
            "intervention_update",
            f"Intervention {event}",
            f"A {intervention.intervention_type} intervention is now {intervention.status}.",
            classroom_id=intervention.classroom_id,
            payload={
                "intervention_id": str(intervention.intervention_id),
                "kc_id": intervention.kc_id,
                "status": intervention.status,
            },
            dedupe_key=f"intervention:{intervention.intervention_id}:{intervention.status}",
        )
        written += made is not None
    return written


def generate_class_alerts(
    session: Session,
    classroom_id: uuid.UUID,
    learner_ids: list[uuid.UUID],
    *,
    today: datetime,
    synthetic: bool = False,
) -> int:
    """One weekly alert per weak topic per teacher (deterministic, idempotent).

    A topic qualifies when at least ALERT_MIN_LEARNERS learners have enough evidence and at least
    ALERT_MIN_SHARE of them are below the weak cut-off. Cut-offs are provisional.
    """
    iso = today.isocalendar()
    week = f"{iso.year}-W{iso.week:02d}"
    written = 0
    for row in progress_summary.class_weak_areas(session, learner_ids):
        if (
            row["learners_with_evidence"] < ALERT_MIN_LEARNERS
            or row["share_below_threshold"] < ALERT_MIN_SHARE
        ):
            continue
        for teacher_id in _teachers(session, classroom_id):
            made = create(
                session,
                teacher_id,
                "class_weak_area",
                f"Many learners are struggling with {row['name'] or row['kc_id']}",
                f"{row['learners_below_threshold']} of {row['learners_with_evidence']} learners "
                f"with enough answers are below {progress_summary.WEAK_BELOW} estimated mastery "
                "(provisional estimate).",
                classroom_id=classroom_id,
                payload={k: row[k] for k in ("kc_id", "learners_below_threshold")},
                dedupe_key=f"weak:{classroom_id}:{row['kc_id']}:{week}",
                synthetic=synthetic,
            )
            written += made is not None
    return written
