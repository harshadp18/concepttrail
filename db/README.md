# `db/` — database bootstrap and schema lifecycle

## Canonical schema

The user reports creating the 26-table schema under PostgreSQL 18 and enabling pgvector 0.8.7. The SQL in `schema/001_initial_schema.sql` is a clean-database bootstrap/reference for the schema that was supplied and run in the conversation.

## Important: existing database already created

Do **not** run `001_initial_schema.sql` again against the populated `concepttrail` schema. It uses `CREATE TABLE` statements and is not an idempotent migration. First inspect:

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'concepttrail' AND table_type = 'BASE TABLE'
ORDER BY table_name;
```

Expected count: 26. Compare columns, types, constraints, indexes and extension version using the introspection queries in `docs/DATABASE_SCHEMA.md`.

## Naming and search path

The script creates a PostgreSQL schema named `concepttrail`, with lowercase table names. Application SQLAlchemy models must explicitly target `schema="concepttrail"` or configure the search path carefully. Do not assume tables are in `public`.

## Alembic adoption

1. Introspect real database and compare against bootstrap SQL.
2. Create SQLAlchemy models matching the real schema.
3. Configure Alembic `target_metadata` and schema handling.
4. Generate an autogenerate diff against a disposable test database and inspect it.
5. Create an initial baseline migration representing the existing schema.
6. After independent verification, use `alembic stamp` to mark the live DB as at that baseline if appropriate; do not run the initial create migration on already existing tables.
7. Make future changes only through reviewed migrations.

Never drop/recreate the production or owner database to make Alembic easier.

Status (2026-10-31): steps 1–5 are done. The baseline is revision `0001` (`app/db/migrations/versions/0001_baseline_26_table_schema.py`), with the version table in `public.alembic_version`. Step 6 (`alembic stamp 0001` on the owner's database) is **pending owner approval**; follow the safe stamping procedure in `app/db/migrations/README.md`. Read-only verification at any time: `python -m app.db.schema_snapshot`.

## Standard implementation specification

### 1. Module Purpose & Architectural Role

Database entry point for the current 26-table PostgreSQL `concepttrail` contract and safe verification scripts.

### 2. Recent Updates Incorporated in This Module

Initial schema is already user-run; bootstrap is clean-install reference only. Use read-only inspection and Alembic for future approved changes.

### 3. File Manifest

`schema/001_initial_schema.sql` clean-schema snapshot; `verify_schema.sql` read-only introspection; `schema/README.md` detailed contract.

### 4. Data Structures, Types & Schemas

Preserve all 26 table names/relationships, `subject_id VARCHAR`, exact nine-column `embedding_chunk` design, unbounded `VECTOR`.

### 5. File-by-File Implementation Specification

Connect with a restricted account, run read-only introspection first, compare actual columns/types/constraints; do not run bootstrap or destructive SQL.

### 6. Integration Points

App DB mappings and Alembic baseline depend on this contract; data importer writes through repositories.

### 7. Module Verification Checklist

Execute only `verify_schema.sql` read-only queries against the target DB; compare results to `docs/DATABASE_SCHEMA.md`.
