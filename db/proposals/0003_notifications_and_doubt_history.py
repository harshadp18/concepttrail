"""PROPOSED, NOT ACTIVE: add `notification`, `doubt_conversation`, `doubt_message` (additive).

Like 0002, this lives outside `app/db/migrations/versions`, so `alembic upgrade head` never
applies it. It is exercised only on throwaway databases (tests add this directory to Alembic's
`version_locations`). To adopt after owner approval and a verified backup: move it (and 0002)
into `app/db/migrations/versions/`, then `alembic upgrade 0003`.

Why tables are needed: the 26-table baseline has no entity for per-user notifications and no
entity for the tutor conversation history (`docs/API_CONTRACTS.md` forbids overloading
unrelated records). Design notes:
- additive only: three new tables, foreign keys to existing tables, nothing existing changes;
- `notification.dedupe_key` is unique per user so a batch job can re-run without duplicates;
  `is_synthetic` labels demo rows so they can never be mistaken for real activity;
- `doubt_message.content` is student-written text: retention and deletion are owner decisions
  (documented in docs/SECURITY_PRIVACY.md); messages cascade-delete with their conversation;
  no row is ever sent to a model provider outside the single-request prompt;
- rollback (`downgrade`) drops only these tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "concepttrail"
KINDS = ("class_weak_area", "intervention_update", "review_outcome", "system")
ROLES = ("student", "tutor")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _now() -> sa.TextClause:
    return sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "notification",
        sa.Column("notification_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("classroom_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("dedupe_key", sa.String(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=_now()),
        sa.Column("read_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("notification_id", name="notification_pkey"),
        sa.ForeignKeyConstraint(
            ["user_id"], [f"{SCHEMA}.users.user_id"], name="notification_user_id_fkey"
        ),
        sa.ForeignKeyConstraint(
            ["classroom_id"],
            [f"{SCHEMA}.classroom.classroom_id"],
            name="notification_classroom_id_fkey",
        ),
        sa.CheckConstraint(_in("kind", KINDS), name="notification_kind_check"),
        sa.UniqueConstraint("user_id", "dedupe_key", name="notification_user_dedupe_key"),
        schema=SCHEMA,
    )
    op.create_index(
        "notification_user_created_idx",
        "notification",
        ["user_id", sa.text("created_at DESC")],
        schema=SCHEMA,
    )
    op.create_index(
        "notification_user_unread_idx",
        "notification",
        ["user_id"],
        schema=SCHEMA,
        postgresql_where=sa.text("read_at IS NULL"),
    )

    op.create_table(
        "doubt_conversation",
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("learner_id", sa.UUID(), nullable=False),
        sa.Column("class_level", sa.SmallInteger(), nullable=False),
        sa.Column("subject_id", sa.String(), nullable=True),
        sa.Column("kc_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=_now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=_now()),
        sa.Column("archived_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("conversation_id", name="doubt_conversation_pkey"),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            [f"{SCHEMA}.learners.learner_id"],
            name="doubt_conversation_learner_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"], [f"{SCHEMA}.subject.subject_id"], name="doubt_conversation_subject_fkey"
        ),
        sa.ForeignKeyConstraint(
            ["kc_id"], [f"{SCHEMA}.knowledge_component.kc_id"], name="doubt_conversation_kc_fkey"
        ),
        sa.CheckConstraint(
            "class_level BETWEEN 6 AND 10", name="doubt_conversation_class_level_check"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "doubt_conversation_learner_idx",
        "doubt_conversation",
        ["learner_id", sa.text("updated_at DESC")],
        schema=SCHEMA,
    )

    op.create_table(
        "doubt_message",
        sa.Column("message_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("grounding", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("citations", postgresql.JSONB(), nullable=True),
        sa.Column("model_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=_now()),
        sa.PrimaryKeyConstraint("message_id", name="doubt_message_pkey"),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            [f"{SCHEMA}.doubt_conversation.conversation_id"],
            name="doubt_message_conversation_fkey",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(_in("role", ROLES), name="doubt_message_role_check"),
        sa.CheckConstraint(
            "grounding IS NULL OR grounding IN ('grounded', 'abstained')",
            name="doubt_message_grounding_check",
        ),
        sa.CheckConstraint("seq >= 1", name="doubt_message_seq_check"),
        sa.UniqueConstraint("conversation_id", "seq", name="doubt_message_conversation_seq_key"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("doubt_message", schema=SCHEMA)
    op.drop_index("doubt_conversation_learner_idx", "doubt_conversation", schema=SCHEMA)
    op.drop_table("doubt_conversation", schema=SCHEMA)
    op.drop_index("notification_user_unread_idx", "notification", schema=SCHEMA)
    op.drop_index("notification_user_created_idx", "notification", schema=SCHEMA)
    op.drop_table("notification", schema=SCHEMA)
