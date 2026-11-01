"""PROPOSED, NOT ACTIVE: add `bell_ringer_cycle` (additive; needs owner approval).

Like 0002 and 0003, this lives outside `app/db/migrations/versions`, so `alembic upgrade head`
never applies it. It is exercised only on throwaway databases (tests add this directory to
Alembic's `version_locations`). To adopt after owner approval and a verified backup: move it (with
0002 and 0003) into `app/db/migrations/versions/`, then `alembic upgrade 0004`.

Why a table is needed: the 26-table baseline has no entity for a Bell-Ringer (the API contract
forbids overloading unrelated records, and CLAUDE.md forbids adding one silently). Design notes:
- additive only: one new table, foreign keys to existing tables, nothing existing changes;
- one row is one topic-specific cycle for one class: the flagged topic (`kc_id`), the traced
  root prerequisite (`root_kc_id`, NULL when the topic itself is the target), the board and bridge
  questions chosen by the deterministic card builder, and a JSON `baseline` captured at creation
  (counts, window, thresholds, the affected learners' estimates) so the follow-up can compare;
- a partial unique index allows at most one open (`planned`/`in_progress`) cycle per class and
  topic, so a repeated request cannot create duplicates; several topics may be open at once;
- `teacher_note` is teacher-written and must not hold student personal data; it is never sent to
  a model provider;
- rollback (`downgrade`) drops only this table and its indexes.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "concepttrail"
STATUSES = ("planned", "in_progress", "completed", "cancelled")


def upgrade() -> None:
    op.create_table(
        "bell_ringer_cycle",
        sa.Column("cycle_id", sa.UUID(), nullable=False),
        sa.Column("classroom_id", sa.UUID(), nullable=False),
        sa.Column("kc_id", sa.String(), nullable=False),
        sa.Column("root_kc_id", sa.String(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="planned"),
        sa.Column("board_question_id", sa.String(), nullable=True),
        sa.Column("bridge_question_id", sa.String(), nullable=True),
        sa.Column("teacher_note", sa.Text(), nullable=True),
        sa.Column("baseline", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("cycle_id", name="bell_ringer_cycle_pkey"),
        sa.ForeignKeyConstraint(
            ["classroom_id"],
            [f"{SCHEMA}.classroom.classroom_id"],
            name="bell_ringer_cycle_classroom_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["kc_id"], [f"{SCHEMA}.knowledge_component.kc_id"], name="bell_ringer_cycle_kc_id_fkey"
        ),
        sa.ForeignKeyConstraint(
            ["root_kc_id"],
            [f"{SCHEMA}.knowledge_component.kc_id"],
            name="bell_ringer_cycle_root_kc_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], [f"{SCHEMA}.users.user_id"], name="bell_ringer_cycle_created_by_fkey"
        ),
        sa.ForeignKeyConstraint(
            ["board_question_id"],
            [f"{SCHEMA}.questions.question_id"],
            name="bell_ringer_cycle_board_question_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["bridge_question_id"],
            [f"{SCHEMA}.questions.question_id"],
            name="bell_ringer_cycle_bridge_question_fkey",
        ),
        sa.CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in STATUSES)})",
            name="bell_ringer_cycle_status_check",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "bell_ringer_cycle_one_open_per_topic",
        "bell_ringer_cycle",
        ["classroom_id", "kc_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("status IN ('planned', 'in_progress')"),
    )
    op.create_index(
        "bell_ringer_cycle_classroom_idx",
        "bell_ringer_cycle",
        ["classroom_id", sa.text("created_at DESC")],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("bell_ringer_cycle_classroom_idx", "bell_ringer_cycle", schema=SCHEMA)
    op.drop_index("bell_ringer_cycle_one_open_per_topic", "bell_ringer_cycle", schema=SCHEMA)
    op.drop_table("bell_ringer_cycle", schema=SCHEMA)
