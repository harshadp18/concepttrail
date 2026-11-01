"""Teacher interventions (planned actions for a class, group or learner on a knowledge component).

Uses the PROPOSED `teacher_intervention` table (`app.db.proposed_models`). Callers must check
`Settings.interventions_enabled`; the table exists only after the owner approves and applies
`db/proposals/0002_teacher_intervention.py`. Authorization (teacher assigned to the class) is done
by the route dependency; this service additionally checks that a named learner is actively enrolled
in that class and that a named KC exists. Notes are teacher-written and must not hold student
personal data beyond the class context; they are never sent to any model.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ClassEnrollment, KnowledgeComponent
from app.db.proposed_models import INTERVENTION_STATUSES, INTERVENTION_TYPES, TeacherIntervention

TRANSITIONS = {
    "planned": {"in_progress", "completed", "cancelled"},
    "in_progress": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


class InterventionError(ValueError):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def create(
    session: Session,
    classroom_id: uuid.UUID,
    teacher_id: uuid.UUID,
    *,
    intervention_type: str,
    kc_id: str | None = None,
    learner_id: uuid.UUID | None = None,
    note: str | None = None,
) -> TeacherIntervention:
    if intervention_type not in INTERVENTION_TYPES:
        raise InterventionError("invalid_intervention_type", "Unknown intervention type.")
    if kc_id is not None and session.get(KnowledgeComponent, kc_id) is None:
        raise InterventionError("topic_not_found", "The topic is unavailable.", 404)
    if learner_id is not None:
        enrolled = session.scalar(
            select(ClassEnrollment.enrollment_id).where(
                ClassEnrollment.classroom_id == classroom_id,
                ClassEnrollment.learner_id == learner_id,
                ClassEnrollment.ended_at.is_(None),
            )
        )
        if enrolled is None:
            raise InterventionError(
                "learner_not_in_class", "The learner is not actively enrolled in this class.", 404
            )
    row = TeacherIntervention(
        intervention_id=uuid.uuid4(),
        classroom_id=classroom_id,
        created_by=teacher_id,
        kc_id=kc_id,
        learner_id=learner_id,
        intervention_type=intervention_type,
        status="planned",
        note=(note or "").strip() or None,
    )
    session.add(row)
    session.flush()
    return row


def list_for_class(
    session: Session, classroom_id: uuid.UUID, status: str | None = None
) -> list[TeacherIntervention]:
    query = select(TeacherIntervention).where(TeacherIntervention.classroom_id == classroom_id)
    if status is not None:
        query = query.where(TeacherIntervention.status == status)
    return list(
        session.scalars(
            query.order_by(TeacherIntervention.created_at, TeacherIntervention.intervention_id)
        )
    )


def update_status(
    session: Session, classroom_id: uuid.UUID, intervention_id: uuid.UUID, status: str
) -> TeacherIntervention:
    if status not in INTERVENTION_STATUSES:
        raise InterventionError("invalid_status", "Unknown status.")
    row = session.get(TeacherIntervention, intervention_id)
    if row is None or row.classroom_id != classroom_id:
        raise InterventionError("intervention_not_found", "The intervention is unavailable.", 404)
    if status not in TRANSITIONS[row.status]:
        raise InterventionError(
            "invalid_transition", f"Cannot move from {row.status} to {status}.", 409
        )
    now = datetime.now(UTC)
    row.status, row.updated_at = status, now
    row.completed_at = now if status == "completed" else None
    session.flush()
    return row
