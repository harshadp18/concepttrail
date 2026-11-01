"""PROPOSED, NOT ACTIVE: add `teacher_intervention` (additive; needs owner approval).

This file lives outside `app/db/migrations/versions`, so `alembic upgrade head` never applies it.
It is exercised only on throwaway databases by
`tests/integration/test_intervention_migration_proposal.py`, which adds this directory to
Alembic's `version_locations`. To adopt it after approval and a verified backup: move it into
`app/db/migrations/versions/`, add the matching ORM model, and run `alembic upgrade 0002`.

Why a table is needed: the 26-table baseline has no entity for a teacher's planned action on a
class, group or learner for a knowledge component, and the API contract forbids overloading
unrelated records. Design notes:
- additive only: one new table, foreign keys to existing tables, no change to any existing
  column, constraint or row;
- `learner_id` NULL means the whole class; `kc_id` NULL means not tied to one KC;
- `note` is teacher-written free text: the API must state that it must not contain student
  personal data beyond what the class context already holds;
- rollback (`downgrade`) drops only this table and its indexes; no existing data is touched.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "concepttrail"
TYPES = ("reteach", "small_group", "individual_support", "practice_assignment", "other")
STATUSES = ("planned", "in_progress", "completed", "cancelled")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.create_table(
        "teacher_intervention",
        sa.Column("intervention_id", sa.UUID(), nullable=False),
        sa.Column("classroom_id", sa.UUID(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("kc_id", sa.String(), nullable=True),
        sa.Column("learner_id", sa.UUID(), nullable=True),
        sa.Column("intervention_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="planned"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("intervention_id", name="teacher_intervention_pkey"),
        sa.ForeignKeyConstraint(
            ["classroom_id"],
            [f"{SCHEMA}.classroom.classroom_id"],
            name="teacher_intervention_classroom_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            [f"{SCHEMA}.users.user_id"],
            name="teacher_intervention_created_by_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["kc_id"],
            [f"{SCHEMA}.knowledge_component.kc_id"],
            name="teacher_intervention_kc_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            [f"{SCHEMA}.learners.learner_id"],
            name="teacher_intervention_learner_id_fkey",
        ),
        sa.CheckConstraint(_in("intervention_type", TYPES), name="teacher_intervention_type_check"),
        sa.CheckConstraint(_in("status", STATUSES), name="teacher_intervention_status_check"),
        sa.CheckConstraint(
            "(status = 'completed') = (completed_at IS NOT NULL)",
            name="teacher_intervention_completed_check",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "teacher_intervention_classroom_status_idx",
        "teacher_intervention",
        ["classroom_id", "status"],
        schema=SCHEMA,
    )
    op.create_index(
        "teacher_intervention_learner_idx", "teacher_intervention", ["learner_id"], schema=SCHEMA
    )


def downgrade() -> None:
    op.drop_index("teacher_intervention_learner_idx", "teacher_intervention", schema=SCHEMA)
    op.drop_index(
        "teacher_intervention_classroom_status_idx", "teacher_intervention", schema=SCHEMA
    )
    op.drop_table("teacher_intervention", schema=SCHEMA)
