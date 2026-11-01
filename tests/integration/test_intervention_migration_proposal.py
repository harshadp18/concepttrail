"""The PROPOSED intervention migration (db/proposals) on throwaway databases only.

Same disposable-server guard as test_migrations.py. Verifies: upgrade from the baseline adds
exactly one table, existing tables and rows are untouched, constraints reject bad values, and
downgrade restores the exact baseline. The active migration chain is not changed by this test.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from test_migrations import (  # noqa: F401  (fixtures)
    _engine,
    admin_url,
    alembic,
    assert_is_baseline,
    fresh_database,
    inspect_database,
)

pytestmark = pytest.mark.migration_db

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROPOSALS = PROJECT_ROOT / "db/proposals"
VERSIONS = PROJECT_ROOT / "app/db/migrations/versions"


def with_proposals(cfg):
    cfg.set_main_option("version_locations", os.pathsep.join([str(VERSIONS), str(PROPOSALS)]))
    return cfg


def test_active_chain_does_not_include_the_proposal(alembic, fresh_database) -> None:  # noqa: F811
    cfg = alembic(fresh_database())
    assert ScriptDirectory.from_config(cfg).get_heads() == ["0001"]


def test_proposal_is_additive_and_reversible(alembic, fresh_database) -> None:  # noqa: F811
    target = fresh_database()
    command.upgrade(alembic(target), "0001")
    baseline = inspect_database(target)
    engine = _engine(target)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO concepttrail.role (role_code) VALUES ('teacher')"))
    command.upgrade(with_proposals(alembic(target)), "0002")
    upgraded = inspect_database(target)
    assert set(upgraded["snapshot"]) - set(baseline["snapshot"]) == {"teacher_intervention"}
    for name, table in baseline["snapshot"].items():
        assert upgraded["snapshot"][name] == table  # nothing existing changed
    room, user = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM concepttrail.role")).scalar() == 1
        conn.execute(
            text("INSERT INTO concepttrail.classroom (classroom_id) VALUES (:c)"), {"c": room}
        )
        conn.execute(text("INSERT INTO concepttrail.users (user_id) VALUES (:u)"), {"u": user})
        conn.execute(
            text(
                "INSERT INTO concepttrail.teacher_intervention (intervention_id, classroom_id,"
                " created_by, intervention_type) VALUES (:i, :c, :u, 'reteach')"
            ),
            {"i": uuid.uuid4(), "c": room, "u": user},
        )
    for bad in (
        "intervention_type, status) VALUES (:i, :c, :u, 'shame', 'planned')",
        "intervention_type, status) VALUES (:i, :c, :u, 'reteach', 'completed')",
    ):
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO concepttrail.teacher_intervention (intervention_id,"
                    " classroom_id, created_by, " + bad
                ),
                {"i": uuid.uuid4(), "c": room, "u": user},
            )
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM concepttrail.teacher_intervention"))
        conn.execute(text("DELETE FROM concepttrail.users"))
        conn.execute(text("DELETE FROM concepttrail.classroom"))
        conn.execute(text("DELETE FROM concepttrail.role"))
    engine.dispose()
    command.downgrade(with_proposals(alembic(target)), "0001")
    assert_is_baseline(inspect_database(target))
