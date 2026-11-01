"""ORM models for PROPOSED tables that are not in the approved 26-table baseline.

Kept on a separate metadata so the baseline ORM, the schema snapshot and `alembic check` are
unchanged. The matching migrations are `db/proposals/0002_teacher_intervention.py` and
`db/proposals/0003_notifications_and_doubt_history.py` and `db/proposals/0004_bell_ringer_cycle.py`;
until the owner approves and applies them, the features that use these models stay disabled
(`INTERVENTIONS_ENABLED`, `NOTIFICATIONS_ENABLED`, `DOUBT_HISTORY_ENABLED`, `BELL_RINGER_ENABLED`,
all false).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, Boolean, Integer, SmallInteger, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "concepttrail"
INTERVENTION_TYPES = (
    "reteach",
    "small_group",
    "individual_support",
    "practice_assignment",
    "other",
)
INTERVENTION_STATUSES = ("planned", "in_progress", "completed", "cancelled")


class ProposedBase(DeclarativeBase):
    pass


class TeacherIntervention(ProposedBase):
    """Foreign keys are enforced by the database (see the migration); they are not declared
    here because the referenced tables live on the baseline metadata."""

    __tablename__ = "teacher_intervention"
    __table_args__ = {"schema": SCHEMA}

    intervention_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    classroom_id: Mapped[uuid.UUID] = mapped_column()
    created_by: Mapped[uuid.UUID] = mapped_column()
    kc_id: Mapped[str | None] = mapped_column(String)
    learner_id: Mapped[uuid.UUID | None] = mapped_column()
    intervention_type: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, server_default="planned")
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


NOTIFICATION_KINDS = ("class_weak_area", "intervention_update", "review_outcome", "system")


class Notification(ProposedBase):
    __tablename__ = "notification"
    __table_args__ = {"schema": SCHEMA}

    notification_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column()
    classroom_id: Mapped[uuid.UUID | None] = mapped_column()
    kind: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    body: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    dedupe_key: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )
    read_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class DoubtConversation(ProposedBase):
    __tablename__ = "doubt_conversation"
    __table_args__ = {"schema": SCHEMA}

    conversation_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    learner_id: Mapped[uuid.UUID] = mapped_column()
    class_level: Mapped[int] = mapped_column(SmallInteger)
    subject_id: Mapped[str | None] = mapped_column(String)
    kc_id: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )
    archived_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class DoubtMessage(ProposedBase):
    __tablename__ = "doubt_message"
    __table_args__ = {"schema": SCHEMA}

    message_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column()
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    grounding: Mapped[str | None] = mapped_column(String)
    status: Mapped[str | None] = mapped_column(String)
    citations: Mapped[list | None] = mapped_column(JSONB)
    model_id: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )


BELL_RINGER_STATUSES = ("planned", "in_progress", "completed", "cancelled")


class BellRingerCycle(ProposedBase):
    """One topic-specific Bell-Ringer cycle for a class (at most one open per class and topic)."""

    __tablename__ = "bell_ringer_cycle"
    __table_args__ = {"schema": SCHEMA}

    cycle_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    classroom_id: Mapped[uuid.UUID] = mapped_column()
    kc_id: Mapped[str] = mapped_column(String)
    root_kc_id: Mapped[str | None] = mapped_column(String)
    created_by: Mapped[uuid.UUID] = mapped_column()
    status: Mapped[str] = mapped_column(String, server_default="planned")
    board_question_id: Mapped[str | None] = mapped_column(String)
    bridge_question_id: Mapped[str | None] = mapped_column(String)
    teacher_note: Mapped[str | None] = mapped_column(Text)
    baseline: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
