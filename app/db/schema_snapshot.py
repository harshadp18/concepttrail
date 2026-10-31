"""Comparable snapshots of the `concepttrail` schema from ORM metadata or the live catalog.

The same normalised shape is built offline from SQLAlchemy metadata and, read-only,
from PostgreSQL system catalogs, so the ORM, a migration-built database and the
owner's database can be compared exactly:

    {table: {"columns": [[name, pg_type, nullable], ...],      # ordinal order
             "primary_key": {"name": str, "columns": [...]},
             "foreign_keys": [{"name", "columns", "referred_table", "referred_columns"}],
             "unique_constraints": [{"name", "columns"}],
             "indexes": [{"name", "columns", "unique"}]}}       # explicit, non-constraint

Types use PostgreSQL `format_type()` spellings, for example `character varying`.

Read-only CLI (exit 0 = no differences, 1 = differences, 2 = connection not read-only):

    python -m app.db.schema_snapshot
"""

from __future__ import annotations

import sys
from typing import Any

from sqlalchemy import Connection, ForeignKeyConstraint, MetaData, UniqueConstraint, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url

from app.db.session import DB_SCHEMA

Snapshot = dict[str, dict[str, Any]]
Catalog = dict[str, list[dict[str, Any]]]

SNAPSHOT_PARTS = ("columns", "primary_key", "foreign_keys", "unique_constraints", "indexes")

# SQLAlchemy's PostgreSQL DDL spelling -> PostgreSQL format_type() spelling.
COMPILED_TO_FORMAT_TYPE = {
    "BOOLEAN": "boolean",
    "DOUBLE PRECISION": "double precision",
    "INTEGER": "integer",
    "JSONB": "jsonb",
    "NUMERIC": "numeric",
    "SMALLINT": "smallint",
    "TEXT": "text",
    "TIMESTAMP WITH TIME ZONE": "timestamp with time zone",
    "UUID": "uuid",
    "VARCHAR": "character varying",
    "VECTOR": "vector",
}

COLUMNS_SQL = text(
    """
    SELECT c.relname AS table_name, a.attname AS column_name,
           format_type(a.atttypid, a.atttypmod) AS type, NOT a.attnotnull AS nullable,
           a.atthasdef AS has_default, a.attidentity AS identity, a.attgenerated AS generated
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = :schema AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped
    ORDER BY c.relname, a.attnum
    """
)

CONSTRAINTS_SQL = text(
    """
    SELECT c.relname AS table_name, con.conname AS name, con.contype AS type,
           ARRAY(SELECT a.attname FROM unnest(con.conkey) WITH ORDINALITY k(attnum, ord)
                 JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum
                 ORDER BY k.ord) AS columns,
           rn.nspname AS referred_schema, rc.relname AS referred_table,
           ARRAY(SELECT a.attname FROM unnest(con.confkey) WITH ORDINALITY k(attnum, ord)
                 JOIN pg_attribute a ON a.attrelid = con.confrelid AND a.attnum = k.attnum
                 ORDER BY k.ord) AS referred_columns,
           con.confdeltype AS on_delete, con.confupdtype AS on_update,
           con.condeferrable AS deferrable, con.convalidated AS validated
    FROM pg_constraint con
    JOIN pg_class c ON c.oid = con.conrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    LEFT JOIN pg_class rc ON rc.oid = con.confrelid
    LEFT JOIN pg_namespace rn ON rn.oid = rc.relnamespace
    WHERE n.nspname = :schema AND con.contype IN ('p', 'f', 'u', 'c', 'x')
    ORDER BY c.relname, con.conname
    """
)

# Explicit indexes only: indexes that back a PK/UNIQUE constraint are covered above.
INDEXES_SQL = text(
    """
    SELECT t.relname AS table_name, i.relname AS name, ix.indisunique AS unique,
           ARRAY(SELECT a.attname FROM unnest(ix.indkey::int2[]) WITH ORDINALITY k(attnum, ord)
                 JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum
                 ORDER BY k.ord) AS columns,
           am.amname AS method, ix.indpred IS NOT NULL AS partial,
           ix.indexprs IS NOT NULL AS expression
    FROM pg_index ix
    JOIN pg_class i ON i.oid = ix.indexrelid
    JOIN pg_class t ON t.oid = ix.indrelid
    JOIN pg_namespace n ON n.oid = t.relnamespace
    JOIN pg_am am ON am.oid = i.relam
    WHERE n.nspname = :schema
      AND NOT EXISTS (SELECT 1 FROM pg_constraint con WHERE con.conindid = ix.indexrelid)
    ORDER BY t.relname, i.relname
    """
)


def metadata_snapshot(metadata: MetaData, schema: str = DB_SCHEMA) -> Snapshot:
    """Snapshot of every table in `metadata` that belongs to `schema` (no connection)."""
    dialect = postgresql.dialect()
    snapshot: Snapshot = {}
    for table in metadata.sorted_tables:
        if table.schema != schema:
            continue
        columns = []
        for column in table.columns:
            compiled = column.type.compile(dialect=dialect)
            pg_type = COMPILED_TO_FORMAT_TYPE.get(compiled, compiled)
            columns.append([column.name, pg_type, column.nullable])
        foreign_keys = [
            {
                "name": str(fk.name),
                "columns": [c.name for c in fk.columns],
                "referred_table": fk.referred_table.name,
                "referred_columns": [element.column.name for element in fk.elements],
            }
            for fk in table.constraints
            if isinstance(fk, ForeignKeyConstraint)
        ]
        uniques = [
            {"name": str(uq.name), "columns": [c.name for c in uq.columns]}
            for uq in table.constraints
            if isinstance(uq, UniqueConstraint)
        ]
        indexes = [
            {
                "name": str(ix.name),
                "columns": [c.name for c in ix.columns],
                "unique": bool(ix.unique),
            }
            for ix in table.indexes
        ]
        snapshot[table.name] = {
            "columns": columns,
            "primary_key": {
                "name": str(table.primary_key.name),
                "columns": [c.name for c in table.primary_key.columns],
            },
            "foreign_keys": sorted(foreign_keys, key=lambda item: item["name"]),
            "unique_constraints": sorted(uniques, key=lambda item: item["name"]),
            "indexes": sorted(indexes, key=lambda item: item["name"]),
        }
    return dict(sorted(snapshot.items()))


def read_catalog(conn: Connection, schema: str = DB_SCHEMA) -> Catalog:
    """Read column, constraint and index metadata for `schema`. Selects no table rows."""
    params = {"schema": schema}
    return {
        name: [dict(row._mapping) for row in conn.execute(sql, params)]
        for name, sql in (
            ("columns", COLUMNS_SQL),
            ("constraints", CONSTRAINTS_SQL),
            ("indexes", INDEXES_SQL),
        )
    }


def catalog_snapshot(catalog: Catalog) -> Snapshot:
    tables: Snapshot = {}
    for col in catalog["columns"]:
        entry = tables.setdefault(
            col["table_name"],
            {
                "columns": [],
                "primary_key": None,
                "foreign_keys": [],
                "unique_constraints": [],
                "indexes": [],
            },
        )
        entry["columns"].append([col["column_name"], col["type"], col["nullable"]])
    for con in catalog["constraints"]:
        entry = tables[con["table_name"]]
        if con["type"] == "p":
            entry["primary_key"] = {"name": con["name"], "columns": list(con["columns"])}
        elif con["type"] == "f":
            entry["foreign_keys"].append(
                {
                    "name": con["name"],
                    "columns": list(con["columns"]),
                    "referred_table": con["referred_table"],
                    "referred_columns": list(con["referred_columns"]),
                }
            )
        elif con["type"] == "u":
            entry["unique_constraints"].append(
                {"name": con["name"], "columns": list(con["columns"])}
            )
    for ix in catalog["indexes"]:
        tables[ix["table_name"]]["indexes"].append(
            {"name": ix["name"], "columns": list(ix["columns"]), "unique": ix["unique"]}
        )
    return dict(sorted(tables.items()))


def rule_violations(catalog: Catalog, schema: str = DB_SCHEMA) -> list[str]:
    """Database rules the ORM does not declare: defaults, CHECKs, FK actions, index kinds."""
    problems: list[str] = []
    for col in catalog["columns"]:
        if col["has_default"] or col["identity"] or col["generated"]:
            problems.append(f"{col['table_name']}.{col['column_name']}: default/identity/generated")
    for con in catalog["constraints"]:
        where = f"{con['table_name']}.{con['name']}"
        if con["type"] in ("c", "x"):
            problems.append(f"{where}: unexpected CHECK/EXCLUDE constraint")
        if con["type"] == "f":
            if con["referred_schema"] != schema:
                problems.append(f"{where}: references schema {con['referred_schema']}")
            if (con["on_delete"], con["on_update"]) != ("a", "a"):
                problems.append(f"{where}: FK action is not NO ACTION")
            if con["deferrable"] or not con["validated"]:
                problems.append(f"{where}: FK is deferrable or not validated")
    for ix in catalog["indexes"]:
        if (ix["method"], ix["partial"], ix["expression"]) != ("btree", False, False):
            problems.append(f"{ix['table_name']}.{ix['name']}: not a plain btree index")
    return problems


def _by_name(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["name"]: item for item in items}


def diff_snapshots(expected: Snapshot, actual: Snapshot) -> list[str]:
    """Human-readable differences; an empty list means the snapshots are identical."""
    diffs = [f"missing table: {t}" for t in sorted(expected.keys() - actual.keys())]
    diffs += [f"unexpected table: {t}" for t in sorted(actual.keys() - expected.keys())]
    for table in sorted(expected.keys() & actual.keys()):
        exp, act = expected[table], actual[table]
        exp_cols = {c[0]: c for c in exp["columns"]}
        act_cols = {c[0]: c for c in act["columns"]}
        diffs += [f"{table}: missing column {c}" for c in sorted(exp_cols.keys() - act_cols)]
        diffs += [f"{table}: unexpected column {c}" for c in sorted(act_cols.keys() - exp_cols)]
        for name in sorted(exp_cols.keys() & act_cols.keys()):
            if exp_cols[name] != act_cols[name]:
                diffs.append(
                    f"{table}.{name}: expected {exp_cols[name][1]} nullable={exp_cols[name][2]},"
                    f" found {act_cols[name][1]} nullable={act_cols[name][2]}"
                )
        common = exp_cols.keys() & act_cols.keys()
        if [c for c in exp_cols if c in common] != [c for c in act_cols if c in common]:
            diffs.append(f"{table}: column order differs")
        if exp["primary_key"] != act["primary_key"]:
            diffs.append(
                f"{table}: primary key expected {exp['primary_key']}, found {act['primary_key']}"
            )
        for part, label in (
            ("foreign_keys", "foreign key"),
            ("unique_constraints", "unique constraint"),
            ("indexes", "index"),
        ):
            exp_items, act_items = _by_name(exp[part]), _by_name(act[part])
            for name in sorted(exp_items.keys() - act_items.keys()):
                diffs.append(f"{table}: missing {label} {name}")
            for name in sorted(act_items.keys() - exp_items.keys()):
                diffs.append(f"{table}: unexpected {label} {name}")
            for name in sorted(exp_items.keys() & act_items.keys()):
                if exp_items[name] != act_items[name]:
                    diffs.append(
                        f"{table}: {label} {name} expected {exp_items[name]},"
                        f" found {act_items[name]}"
                    )
    return diffs


def snapshot_totals(snapshot: Snapshot) -> dict[str, int]:
    return {
        "tables": len(snapshot),
        "columns": sum(len(t["columns"]) for t in snapshot.values()),
        "primary_keys": sum(1 for t in snapshot.values() if t["primary_key"]),
        "composite_primary_keys": sum(
            1
            for t in snapshot.values()
            if t["primary_key"] and len(t["primary_key"]["columns"]) > 1
        ),
        "foreign_keys": sum(len(t["foreign_keys"]) for t in snapshot.values()),
        "unique_constraints": sum(len(t["unique_constraints"]) for t in snapshot.values()),
        "indexes": sum(len(t["indexes"]) for t in snapshot.values()),
    }


def main() -> int:
    """Compare the database in DATABASE_URL with the ORM over a read-only connection."""
    from app.core.config import load_settings
    from app.db import models  # noqa: F401  (registers the mapped tables)
    from app.db.migration_settings import VERSION_TABLE, VERSION_TABLE_SCHEMA
    from app.db.session import Base, create_db_engine

    settings = load_settings()
    url = make_url(settings.database_url.get_secret_value())
    engine = create_db_engine(settings, read_only=True)
    try:
        with engine.connect() as conn:
            if conn.execute(text("SHOW transaction_read_only")).scalar() != "on":
                print("refusing to continue: connection is not read-only", file=sys.stderr)
                return 2
            catalog = read_catalog(conn)
            vector = conn.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            ).scalar()
            version_table = f"{VERSION_TABLE_SCHEMA}.{VERSION_TABLE}"
            has_version_table = conn.execute(
                text("SELECT to_regclass(:name) IS NOT NULL"), {"name": version_table}
            ).scalar()
            versions = (
                conn.execute(
                    text(f"SELECT version_num FROM {VERSION_TABLE_SCHEMA}.{VERSION_TABLE}")
                )
                .scalars()
                .all()
                if has_version_table
                else None
            )
            conn.rollback()
    finally:
        engine.dispose()

    live = catalog_snapshot(catalog)
    diffs = diff_snapshots(metadata_snapshot(Base.metadata), live) + rule_violations(catalog)
    print(f"target: {url.host}:{url.port or 5432}/{url.database} (read-only)")
    print(f"live totals: {snapshot_totals(live)}")
    print(f"pgvector extension: {vector or 'not installed'}")
    if versions is None:
        print(f"{version_table}: absent (database not stamped)")
    else:
        print(f"{version_table}: {versions or 'empty'}")
    if diffs:
        print(f"{len(diffs)} difference(s) from the ORM metadata:")
        for line in diffs:
            print(f"  - {line}")
        return 1
    print("no differences from the ORM metadata")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
