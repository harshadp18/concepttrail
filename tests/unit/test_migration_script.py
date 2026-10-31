"""Alembic configuration and the 0001 baseline, checked offline (`--sql`); no database is used."""

from __future__ import annotations

import argparse
import configparser
import io
import re

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core.config import PROJECT_ROOT, Settings
from app.db.migration_settings import (
    BASELINE_REVISION,
    VERSION_TABLE,
    VERSION_TABLE_SCHEMA,
    context_options,
    include_name,
)

ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"
UNREACHABLE_URL = "postgresql+psycopg://ct_user:pw-Sentinel-0c1d@db.invalid:5432/offline_only"


@pytest.fixture
def offline_config(monkeypatch: pytest.MonkeyPatch) -> Config:
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_URL)  # offline mode never connects
    cfg = Config(str(ALEMBIC_INI), output_buffer=io.StringIO())
    cfg.attributes["configure_logger"] = False
    return cfg


def offline_sql(cfg: Config, action: str, revisions: str, *x_args: str) -> str:
    cfg.cmd_opts = argparse.Namespace(x=list(x_args), autogenerate=False)
    getattr(command, action)(cfg, revisions, sql=True)
    return cfg.output_buffer.getvalue()


def test_alembic_ini_holds_no_database_url() -> None:
    parser = configparser.RawConfigParser()
    parser.read(ALEMBIC_INI)
    assert not parser.has_option("alembic", "sqlalchemy.url")
    assert parser.get("alembic", "script_location") == "%(here)s/app/db/migrations"


def test_single_linear_baseline_revision() -> None:
    script = ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))
    assert script.get_heads() == [BASELINE_REVISION]
    baseline = script.get_revision(BASELINE_REVISION)
    assert baseline.down_revision is None
    assert baseline.path.endswith("versions/0001_baseline_26_table_schema.py")


def test_baseline_does_not_import_application_models() -> None:
    source = (
        PROJECT_ROOT / "app/db/migrations/versions/0001_baseline_26_table_schema.py"
    ).read_text(encoding="utf-8")
    assert not re.search(r"^\s*(from|import)\s+app\b", source, re.M)
    assert "from pgvector.sqlalchemy import VECTOR" in source
    assert "VECTOR()" in source and not re.search(r"VECTOR\(\s*\d", source)


def test_offline_upgrade_sql_matches_the_baseline_contract(offline_config: Config) -> None:
    sql = offline_sql(offline_config, "upgrade", "head")
    assert "pw-Sentinel-0c1d" not in sql and "ct_user" not in sql
    assert sql.count("BEGIN;") == 1 and sql.count("COMMIT;") == 1  # one transaction

    version_table = sql.index(f"CREATE TABLE {VERSION_TABLE_SCHEMA}.{VERSION_TABLE}")
    extension = sql.index("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;")
    schema = sql.index("CREATE SCHEMA IF NOT EXISTS concepttrail;")
    first_table = sql.index("CREATE TABLE concepttrail.")
    assert version_table < extension < schema < first_table

    assert len(re.findall(r"^CREATE TABLE concepttrail\.", sql, re.M)) == 26
    assert len(re.findall(r"^CREATE INDEX idx_\w+ ON concepttrail\.", sql, re.M)) == 19
    assert sql.count("FOREIGN KEY") == 35
    assert len(re.findall(r"CONSTRAINT \w+_key UNIQUE", sql)) == 4
    assert re.search(r"^\s+embedding VECTOR,\s*$", sql, re.M)
    assert "VECTOR(" not in sql
    assert "CONSTRAINT fk_note_approved_by FOREIGN KEY" in sql
    assert "DROP " not in sql
    assert f"INSERT INTO public.alembic_version (version_num) VALUES ('{BASELINE_REVISION}')" in sql


def test_offline_downgrade_requires_explicit_opt_in(offline_config: Config) -> None:
    with pytest.raises(RuntimeError, match="allow_baseline_downgrade=yes"):
        offline_sql(offline_config, "downgrade", f"{BASELINE_REVISION}:base")


def test_offline_downgrade_drops_schema_but_keeps_extension(offline_config: Config) -> None:
    sql = offline_sql(
        offline_config, "downgrade", f"{BASELINE_REVISION}:base", "allow_baseline_downgrade=yes"
    )
    assert len(re.findall(r"^DROP TABLE concepttrail\.", sql, re.M)) == 26
    assert len(re.findall(r"^DROP INDEX concepttrail\.idx_", sql, re.M)) == 19
    assert "DROP SCHEMA concepttrail;" in sql  # RESTRICT, never CASCADE
    assert "CASCADE" not in sql
    assert "DROP EXTENSION" not in sql
    assert sql.index("DROP SCHEMA concepttrail;") > sql.rindex("DROP TABLE concepttrail.")


def test_reflection_is_limited_to_the_application_schema() -> None:
    assert include_name("concepttrail", "schema", {}) is True
    assert include_name("public", "schema", {}) is False
    assert include_name(None, "schema", {}) is False
    assert include_name("subject", "table", {"schema_name": "concepttrail"}) is True
    assert include_name(VERSION_TABLE, "table", {"schema_name": "public"}) is False
    assert include_name(VERSION_TABLE, "table", {"schema_name": "concepttrail"}) is False
    assert include_name("idx_note_kc", "index", {"table_name": "note"}) is True


def test_context_options() -> None:
    options = context_options()
    assert options["version_table_schema"] == "public"
    assert options["version_table"] == "alembic_version"
    assert options["include_schemas"] is True
    assert options["compare_type"] is True
    assert options["compare_server_default"] is True
