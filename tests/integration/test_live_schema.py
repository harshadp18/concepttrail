"""Read-only comparison of the live `concepttrail` schema with the ORM and recorded baseline.

Run with: python -m pytest -q -rs -m live_db tests/integration

Skipped when DATABASE_URL is not configured or the server is unreachable. Connections
are opened with `default_transaction_read_only=on`, so PostgreSQL rejects any write.
Only system-catalog metadata is read; no application table rows are selected.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, text
from sqlalchemy.exc import OperationalError

from app.core.config import ConfigurationError, load_settings
from app.db import session as db_session
from app.db.migration_settings import VERSION_TABLE, VERSION_TABLE_SCHEMA, context_options
from app.db.schema_snapshot import catalog_snapshot, read_catalog

pytestmark = pytest.mark.live_db

SCHEMA = "concepttrail"
BASELINE_PATH = Path(__file__).parents[1] / "fixtures" / "concepttrail_schema_baseline.json"
TABLE_NAMES = sorted(json.loads(BASELINE_PATH.read_text(encoding="utf-8"))["tables"])


@pytest.fixture(scope="module")
def read_only_engine():
    try:
        settings = load_settings()
    except ConfigurationError as exc:
        pytest.skip(f"live database not configured: {exc}")
    engine = db_session.create_db_engine(settings, read_only=True)
    try:
        with engine.connect():
            pass
    except OperationalError:
        engine.dispose()
        pytest.skip("live database unreachable at the configured DATABASE_URL")
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def live_conn(read_only_engine) -> Iterator[Connection]:
    with read_only_engine.connect() as conn:
        yield conn
        conn.rollback()


@pytest.fixture(scope="module")
def catalog(live_conn: Connection) -> dict[str, list[dict[str, Any]]]:
    return read_catalog(live_conn, SCHEMA)


@pytest.fixture(scope="module")
def live(catalog: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return catalog_snapshot(catalog)


def test_connection_is_read_only(live_conn: Connection) -> None:
    assert live_conn.execute(text("SHOW default_transaction_read_only")).scalar() == "on"
    assert live_conn.execute(text("SHOW transaction_read_only")).scalar() == "on"


def test_vector_extension_is_installed(live_conn: Connection) -> None:
    version = live_conn.execute(
        text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    ).scalar()
    assert version == "0.8.7"


def test_schema_contains_exactly_the_26_mapped_tables(
    live_conn: Connection, orm_tables: dict[str, Any]
) -> None:
    rows = live_conn.execute(
        text(
            "SELECT c.relname, c.relkind FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = :schema AND c.relkind IN ('r', 'p', 'v', 'm', 'f')"
        ),
        {"schema": SCHEMA},
    ).all()
    assert {kind for _, kind in rows} == {"r"}, "unexpected views or foreign/partitioned tables"
    live_tables = {name for name, _ in rows}
    assert len(live_tables) == 26
    assert live_tables == set(orm_tables)


@pytest.mark.parametrize("table", TABLE_NAMES)
def test_live_table_matches_orm(table: str, live: dict[str, Any], orm_snapshot: dict) -> None:
    for part in ("columns", "primary_key", "foreign_keys", "unique_constraints", "indexes"):
        assert live[table][part] == orm_snapshot[table][part], f"{table}.{part} differs"


def test_live_schema_matches_recorded_baseline(live: dict[str, Any], schema_baseline: dict) -> None:
    assert live == schema_baseline["tables"]


def test_no_unmapped_database_rules(catalog: dict[str, list[dict[str, Any]]]) -> None:
    """The ORM declares no defaults, CHECKs or FK actions because the database has none."""
    assert [
        c for c in catalog["columns"] if c["has_default"] or c["identity"] or c["generated"]
    ] == []
    assert [c for c in catalog["constraints"] if c["type"] in ("c", "x")] == []
    for fk in (c for c in catalog["constraints"] if c["type"] == "f"):
        assert fk["referred_schema"] == SCHEMA
        assert (fk["on_delete"], fk["on_update"]) == ("a", "a"), fk["name"]  # NO ACTION
        assert not fk["deferrable"] and fk["validated"], fk["name"]
    for ix in catalog["indexes"]:
        assert (ix["method"], ix["partial"], ix["expression"]) == ("btree", False, False)


def test_embedding_chunk_is_exactly_nine_columns_with_unbounded_vector(live: dict) -> None:
    assert live["embedding_chunk"]["columns"] == [
        ["chunk_id", "uuid", False],
        ["content_unit_id", "character varying", True],
        ["chunk_order", "integer", True],
        ["chunk_text", "text", True],
        ["token_count", "integer", True],
        ["embedding_model_id", "character varying", True],
        ["embedding", "vector", True],
        ["index_generation", "character varying", True],
        ["created_at", "timestamp with time zone", True],
    ]


def test_alembic_autogenerate_detects_no_differences(live_conn: Connection) -> None:
    """Alembic's own comparator (as used by `revision --autogenerate`) finds no drift.

    `MigrationContext.configure` + `compare_metadata` only reflect; nothing is written.
    """
    from app.db import models  # noqa: F401  (registers the mapped tables)

    migration_context = MigrationContext.configure(live_conn, opts=context_options())
    assert compare_metadata(migration_context, db_session.Base.metadata) == []


def test_version_table_if_present_holds_only_known_revisions(live_conn: Connection) -> None:
    """Unstamped (no version table) is valid until the owner approves `alembic stamp`."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from app.core.config import PROJECT_ROOT

    version_table = f"{VERSION_TABLE_SCHEMA}.{VERSION_TABLE}"
    exists = live_conn.execute(text("SELECT to_regclass(:t)"), {"t": version_table}).scalar()
    if exists is None:
        return
    script = ScriptDirectory.from_config(Config(str(PROJECT_ROOT / "alembic.ini")))
    known = {rev.revision for rev in script.walk_revisions()}
    stamped = set(live_conn.execute(text(f"SELECT version_num FROM {version_table}")).scalars())
    assert stamped <= known


def test_get_db_session_lifecycle_on_live_database(read_only_engine, monkeypatch) -> None:
    factory = db_session.sessionmaker(bind=read_only_engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "get_sessionmaker", lambda: factory)
    checked_out_before = read_only_engine.pool.checkedout()

    dependency = db_session.get_db()
    session = next(dependency)
    assert session.execute(text("SELECT 1")).scalar() == 1
    assert session.in_transaction()
    dependency.close()

    assert not session.in_transaction()
    assert read_only_engine.pool.checkedout() == checked_out_before
