"""Alembic settings shared by `app/db/migrations/env.py` and the migration tests.

`alembic_version` lives in `public`, not in `concepttrail`:

- On an empty database the `concepttrail` schema does not exist until the baseline
  revision creates it, but Alembic must create and read its version table first.
- Keeping Alembic bookkeeping out of the application schema means the 26-table
  contract (and its read-only catalog comparisons) never contain a non-application table.
- A baseline downgrade can drop `concepttrail` without dropping Alembic's own record.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from app.db.session import DB_SCHEMA

VERSION_TABLE = "alembic_version"
VERSION_TABLE_SCHEMA = "public"
BASELINE_REVISION = "0001"

NameType = Literal[
    "schema",
    "table",
    "column",
    "index",
    "unique_constraint",
    "foreign_key_constraint",
]


def include_name(name: str | None, type_: NameType, parent_names: Mapping[str, str | None]) -> bool:
    """Limit reflection to the application schema during autogenerate and `alembic check`.

    Objects in `public` (the pgvector extension and Alembic's own version table) and any
    other schema are never compared against the ORM metadata.
    """
    if type_ == "schema":
        return name == DB_SCHEMA
    if type_ == "table":
        return parent_names.get("schema_name") == DB_SCHEMA and name != VERSION_TABLE
    return True


def context_options() -> dict[str, Any]:
    """Keyword arguments for `alembic.context.configure()` (online, offline and tests)."""
    return {
        "include_schemas": True,
        "include_name": include_name,
        "version_table": VERSION_TABLE,
        "version_table_schema": VERSION_TABLE_SCHEMA,
        "compare_type": True,
        "compare_server_default": True,
    }
