# `app/db/` — PostgreSQL, SQLAlchemy and Alembic

## Database facts reported by the owner

- Windows laptop; official PostgreSQL installer; PostgreSQL 18.
- pgvector 0.8.7 compiled and installed; `CREATE EXTENSION vector` and vector similarity smoke tests succeeded.
- User reports running the 26-table bootstrap and receiving expected verification results.
- This package cannot inspect the laptop's live database. Claude must introspect before changing anything.

## Files

- `session.py`: SQLAlchemy engine, session factory, request-scoped dependency.
- `models.py` or a `models/` package: SQLAlchemy ORM mappings that match the real `concepttrail` schema.
- `repositories/`: focused queries and persistence functions.
- `migrations/`: Alembic migration environment and reviewed revisions.
- `../db/schema/001_initial_schema.sql`: clean-schema bootstrap snapshot corresponding to the user-run table design.

## Do not rerun bootstrap on the user's populated schema

The SQL bootstrap is not an upgrade script. Before using it, verify the target DB/schema. On the user's existing database, use `information_schema`/`pg_catalog` to inspect all 26 tables, column types, nullability, PKs, FKs, unique constraints, indexes, and pgvector extension. Compare against `docs/DATABASE_SCHEMA.md`.

If Alembic has not been configured yet, create ORM models and Alembic environment, compare autogenerate output carefully, and baseline only after the schema matches. `alembic stamp <revision>` marks an existing schema as being at a revision; it does not run DDL. Do not stamp until independently verified. A normal `alembic upgrade` against a schema whose initial tables already exist may fail with “relation already exists” if not baselined properly.

## ID and type caveat

The owner discussed switching `subject_id` to INTEGER, but the ERD/bootstrap that the owner asked to follow and executed uses `VARCHAR` IDs. Keep the live type until an approved migration is designed for `subject.subject_id` and every referencing column. Do not mix INTEGER and VARCHAR FKs.

## Transaction and delete rules

- Do not add cascading deletes casually. Attempts, notes, questions, sources and curriculum data need retention/audit semantics.
- Use explicit transactions for attempt insert + state update.
- Foreign keys alone do not enforce total participation. Verify nullability and add `NOT NULL` through reviewed migrations if required.
- Keep JSONB for flexible payloads shown in the ERD; keep relationally queried identifiers as columns/FKs.

## pgvector

The `embedding_chunk.embedding` column is `VECTOR` without fixed dimension in the current schema. Do not set an arbitrary dimension. First select and evaluate an embedding model; then decide whether to use a dimension-specific type/index or an approved migration. Build vector indexes only after representative data and query tests exist.

## Standard implementation specification

### 1. Module Purpose & Architectural Role

Persistence boundary for the existing PostgreSQL `concepttrail` schema.

### 2. Recent Updates Incorporated in This Module

Preserve 26 tables, `subject_id VARCHAR`, exact `embedding_chunk` fields and unbounded `VECTOR`; introspect before Alembic; no schema bootstrap reruns.

### 3. File Manifest

`models.py` SQLAlchemy 2.x mappings; `session.py` engine/session factory; `repositories/` data access; `migrations/` Alembic environment and revisions.

### 4. Data Structures, Types & Schemas

Use `docs/DATABASE_SCHEMA.md` and `db/schema/001_initial_schema.sql` as reference snapshot only. `embedding_chunk`: nine fields exactly; page provenance comes via `content_unit`/`source_document`.

### 5. File-by-File Implementation Specification

Read-only introspection first; map only confirmed columns/nullability/indexes; request-scoped session; transaction for attempt + BKT update; migrations must be reviewed and reversible.

### 6. Integration Points

Services consume repository interfaces; API dependencies provide session; pipeline publish uses explicit repository/import services.

### 7. Module Verification Checklist

Compare information_schema to approved baseline; test transaction rollback, unique idempotency, FKs and repository scope. Never test against production-like user data.

## Implementation status (2026-10-31)

| File | Status |
|---|---|
| `session.py` | Implemented and tested. `Base` uses `MetaData(schema="concepttrail")` with a naming convention that reproduces PostgreSQL's default constraint names. `create_db_engine(settings, read_only=False)` is lazy and sets `pool_pre_ping` and `hide_parameters`; `read_only=True` sets `default_transaction_read_only=on`. `get_engine()`/`get_sessionmaker()` are cached (`expire_on_commit=False`). `get_db()` never commits, rolls back on exception and always closes. `dispose_engine()` resets the caches. |
| `models.py` | Implemented and tested. 26 mappings equal to the live schema: 188 columns, 26 PKs (8 composite), 35 FKs, 4 UNIQUE, 19 explicit `idx_*` indexes, unbounded `VECTOR`. No ORM relationships yet; repositories add them when needed. |
| `migrations/` + root `alembic.ini` | Implemented and tested. Baseline revision `0001` was verified on disposable databases (upgrade, guarded downgrade, re-upgrade). The version table is `public.alembic_version`. See `migrations/README.md`. **The owner's database is not stamped yet**; that requires explicit approval. |
| `migration_settings.py` | Shared Alembic context options: reflection limited to `concepttrail`, version table in `public`, type and server-default comparison. |
| `schema_snapshot.py` | Read-only catalog snapshot/diff used by the tests and the `python -m app.db.schema_snapshot` pre-stamp verification CLI. |
| `repositories/` | Not started. |

Drift guard: `tests/fixtures/concepttrail_schema_baseline.json` is a read-only catalog snapshot of the live schema. `tests/unit/test_models_metadata.py` compares the ORM with it offline. `tests/integration/test_live_schema.py` (`-m live_db`) compares the live catalog with both, over a read-only connection. Regenerate the baseline only after an approved migration has been applied; never edit it to make a test pass.
