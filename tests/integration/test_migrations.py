"""Alembic baseline lifecycle on throwaway databases of a DISPOSABLE PostgreSQL server.

Requires CONCEPTTRAIL_MIGRATION_TEST_ADMIN_URL: a superuser URL for the maintenance database
of a disposable server (app/db/migrations/README.md, "Disposable database testing"). Each
test creates its own `ct_migtest_<random>` databases and drops only those afterwards.

The suite refuses to run against a server that hosts the development database
(`concepttrail_db`) or that has the same host and port as DATABASE_URL in the root `.env`.

Run: python -m pytest -q -rs -m migration_db tests/integration
"""

from __future__ import annotations

import argparse
import json
import os
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from sqlalchemy import Engine, create_engine, pool, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import OperationalError

from app.core.config import ENV_FILE, PROJECT_ROOT
from app.db.migration_settings import BASELINE_REVISION
from app.db.schema_snapshot import (
    catalog_snapshot,
    read_catalog,
    rule_violations,
    snapshot_totals,
)

pytestmark = pytest.mark.migration_db

ADMIN_URL_ENV = "CONCEPTTRAIL_MIGRATION_TEST_ADMIN_URL"
DEV_DATABASE_NAME = "concepttrail_db"
TEST_DB_PREFIX = "ct_migtest_"
BASELINE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "concepttrail_schema_baseline.json").read_text(
        encoding="utf-8"
    )
)["tables"]
EXPECTED_TOTALS = {
    "tables": 26,
    "columns": 188,
    "primary_keys": 26,
    "composite_primary_keys": 8,
    "foreign_keys": 35,
    "unique_constraints": 4,
    "indexes": 19,
}
DOWNGRADE_OPT_IN = "allow_baseline_downgrade=yes"


def _engine(url: URL, **kwargs: Any) -> Engine:
    return create_engine(url, poolclass=pool.NullPool, hide_parameters=True, **kwargs)


@pytest.fixture(scope="module")
def admin_url() -> Iterator[URL]:
    raw = os.environ.get(ADMIN_URL_ENV)
    if not raw:
        pytest.skip(f"{ADMIN_URL_ENV} is not set; no disposable migration server configured")
    url = make_url(raw)

    dev_raw = dotenv_values(ENV_FILE).get("DATABASE_URL") if ENV_FILE.exists() else None
    if dev_raw:
        dev = make_url(dev_raw)
        if (dev.host, dev.port or 5432) == (url.host, url.port or 5432):
            pytest.fail("refusing to run: admin URL points at the development database server")

    engine = _engine(url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            hosts_dev_db = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": DEV_DATABASE_NAME},
            ).scalar()
    except OperationalError:
        pytest.skip("disposable migration server is unreachable")
    finally:
        engine.dispose()
    if hosts_dev_db:
        pytest.fail(f"refusing to run: server hosts '{DEV_DATABASE_NAME}' (not disposable)")
    yield url


@pytest.fixture
def fresh_database(admin_url: URL) -> Iterator[Callable[[], URL]]:
    """Factory for empty databases on the disposable server; drops only what it created."""
    admin = _engine(admin_url, isolation_level="AUTOCOMMIT")
    created: list[str] = []

    def make() -> URL:
        name = f"{TEST_DB_PREFIX}{uuid.uuid4().hex[:12]}"
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
        created.append(name)
        return admin_url.set(database=name)

    yield make
    with admin.connect() as conn:
        for name in created:
            assert name.startswith(TEST_DB_PREFIX)
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture
def alembic(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Config]:
    """Alembic config aimed at one disposable database through the DATABASE_URL override."""

    def configure(target: URL, *x_args: str) -> Config:
        monkeypatch.setenv("DATABASE_URL", target.render_as_string(hide_password=False))
        cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
        cfg.attributes["configure_logger"] = False
        cfg.cmd_opts = argparse.Namespace(x=list(x_args), autogenerate=False)
        return cfg

    return configure


def inspect_database(target: URL) -> dict[str, Any]:
    engine = _engine(target)
    try:
        with engine.connect() as conn:
            catalog = read_catalog(conn)
            state = {
                "catalog": catalog,
                "snapshot": catalog_snapshot(catalog),
                "schema_exists": conn.execute(
                    text("SELECT to_regnamespace('concepttrail') IS NOT NULL")
                ).scalar(),
                "concepttrail_objects": conn.execute(
                    text(
                        "SELECT count(*) FROM pg_class c JOIN pg_namespace n"
                        " ON n.oid = c.relnamespace WHERE n.nspname = 'concepttrail'"
                    )
                ).scalar(),
                "vector": conn.execute(
                    text(
                        "SELECT e.extversion, n.nspname FROM pg_extension e"
                        " JOIN pg_namespace n ON n.oid = e.extnamespace"
                        " WHERE e.extname = 'vector'"
                    )
                ).one_or_none(),
                "public_tables": conn.execute(
                    text(
                        "SELECT array_agg(tablename ORDER BY tablename) FROM pg_tables"
                        " WHERE schemaname = 'public'"
                    )
                ).scalar(),
                "versions": None,
            }
            if conn.execute(text("SELECT to_regclass('public.alembic_version')")).scalar():
                state["versions"] = list(
                    conn.execute(text("SELECT version_num FROM public.alembic_version")).scalars()
                )
    finally:
        engine.dispose()
    return state


def assert_is_baseline(state: dict[str, Any]) -> None:
    assert state["snapshot"] == BASELINE
    assert snapshot_totals(state["snapshot"]) == EXPECTED_TOTALS
    assert rule_violations(state["catalog"]) == []
    assert tuple(state["vector"]) == ("0.8.7", "public")
    assert state["versions"] == [BASELINE_REVISION]
    assert state["public_tables"] == ["alembic_version"]
    columns = {c[0]: c[1] for c in state["snapshot"]["embedding_chunk"]["columns"]}
    assert len(columns) == 9 and columns["embedding"] == "vector"  # no dimension


def test_a_fresh_upgrade_builds_the_exact_baseline(fresh_database, alembic) -> None:
    target = fresh_database()
    cfg = alembic(target)
    assert inspect_database(target)["schema_exists"] is False

    command.upgrade(cfg, "head")

    assert_is_baseline(inspect_database(target))
    command.check(cfg)  # raises if autogenerate sees any ORM-vs-database difference


def test_b_downgrade_base_removes_the_application_schema(fresh_database, alembic) -> None:
    target = fresh_database()
    command.upgrade(alembic(target), "head")

    command.downgrade(alembic(target, DOWNGRADE_OPT_IN), "base")

    state = inspect_database(target)
    assert state["schema_exists"] is False
    assert state["concepttrail_objects"] == 0
    assert state["snapshot"] == {}
    assert state["versions"] == []  # Alembic's table remains, at base (no revision row)
    assert state["public_tables"] == ["alembic_version"]
    assert tuple(state["vector"]) == ("0.8.7", "public")  # shared extension is kept


def test_c_second_fresh_database_upgrades_identically(fresh_database, alembic) -> None:
    first, second = fresh_database(), fresh_database()
    command.upgrade(alembic(first), "head")
    command.upgrade(alembic(second), "head")

    first_state, second_state = inspect_database(first), inspect_database(second)
    assert_is_baseline(second_state)
    assert first_state["snapshot"] == second_state["snapshot"]


def test_upgrade_downgrade_upgrade_round_trip(fresh_database, alembic) -> None:
    target = fresh_database()
    command.upgrade(alembic(target), "head")
    command.downgrade(alembic(target, DOWNGRADE_OPT_IN), "base")
    command.upgrade(alembic(target), "head")
    assert_is_baseline(inspect_database(target))


def test_downgrade_without_opt_in_is_refused_and_changes_nothing(fresh_database, alembic) -> None:
    target = fresh_database()
    command.upgrade(alembic(target), "head")

    with pytest.raises(RuntimeError, match="allow_baseline_downgrade=yes"):
        command.downgrade(alembic(target), "base")

    assert_is_baseline(inspect_database(target))


def test_existing_unversioned_schema_is_refused_then_stamped(fresh_database, alembic) -> None:
    """Rehearses the owner's situation: the 26 tables exist but no Alembic version table."""
    target = fresh_database()
    command.upgrade(alembic(target), "head")
    engine = _engine(target)
    with engine.begin() as conn:  # disposable database only
        conn.execute(text("DROP TABLE public.alembic_version"))
    engine.dispose()
    before = inspect_database(target)
    assert before["versions"] is None and before["snapshot"] == BASELINE

    with pytest.raises(RuntimeError, match="alembic stamp 0001"):
        command.upgrade(alembic(target), "head")
    after_refusal = inspect_database(target)
    assert after_refusal["versions"] is None  # the failed transaction rolled back entirely
    assert after_refusal["snapshot"] == BASELINE

    command.stamp(alembic(target), BASELINE_REVISION)
    stamped = inspect_database(target)
    assert stamped["versions"] == [BASELINE_REVISION]
    assert stamped["snapshot"] == BASELINE  # stamping changes no application object

    command.upgrade(alembic(target), "head")  # already at head: a no-op
    assert_is_baseline(inspect_database(target))
