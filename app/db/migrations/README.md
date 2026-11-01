# Alembic migrations

Schema lifecycle for the `concepttrail` PostgreSQL schema. Every schema change goes through a reviewed revision in `versions/`. Nothing in the application calls `create_all()`/`drop_all()`, and `db/schema/001_initial_schema.sql` is never re-run against an existing database.

> **The owner's development database (127.0.0.1:5433/concepttrail_db) is NOT baselined yet.**
>
> It already holds the 26-table schema and has no `alembic_version` table. It must be recorded as revision `0001` with `alembic stamp 0001`, and only after the [safe stamping procedure](#safe-baseline-stamping-owner-approval-required) and the owner's explicit approval.
>
> Do not run `alembic upgrade`, `downgrade`, `stamp` or `revision --autogenerate` against it before then.

## Status (2026-10-31)

| Item | State |
|---|---|
| `alembic.ini`, `env.py`, `script.py.mako` | Implemented and tested |
| `versions/0001_baseline_26_table_schema.py` | Baseline revision `0001`, reviewed by hand. On disposable databases: upgrade, guarded downgrade and re-upgrade all verified. |
| Owner's development database | Unstamped. Read-only comparison shows zero differences from revision `0001`, the ORM and the recorded baseline. |

## Files

| File | Purpose |
|---|---|
| `../../../alembic.ini` | Script location, revision file naming, Ruff post-write hooks and logging. Contains **no database URL**. |
| `env.py` | Gets the URL from validated settings and targets `Base.metadata`. It limits reflection to `concepttrail`, keeps the version table in `public`, skips empty autogenerate revisions, and logs only host:port/database. |
| `script.py.mako` | Revision template, including the mandatory review checklist. |
| `versions/` | Revisions, named `<rev>_<slug>.py` with a zero-padded sequential `--rev-id`. |
| `../migration_settings.py` | Shared `context_options()`, `include_name()`, `VERSION_TABLE_SCHEMA = "public"`, `BASELINE_REVISION = "0001"`. |
| `../schema_snapshot.py` | Read-only catalog snapshot/diff and the `python -m app.db.schema_snapshot` verification CLI. |

## Configuration

**Database URL**
- `env.py` calls `load_settings()`, which reads the root `.env`. A `DATABASE_URL` process environment variable overrides it; this is how disposable test databases are targeted.
- The URL is never written to `alembic.ini` or logs. `hide_parameters=True` keeps bound values out of errors.
- The only target information logged is `Target database: host:port/database`. Read it before confirming any operation.

**Metadata**
- `target_metadata = Base.metadata`, with the 26 tables from `app/db/models.py` (`MetaData(schema="concepttrail")`).
- Naming conventions reproduce PostgreSQL's default constraint names. `fk_note_approved_by` is explicit.

**Reflection**
- `include_schemas=True` is combined with `include_name`, which admits only the `concepttrail` schema.
- `public` is never compared with application metadata. It holds the pgvector extension and Alembic's own table.

**Comparison**
- `compare_type=True` and `compare_server_default=True`. The schema has no server defaults, so any default that appears is reported as drift.

**Version table: `public.alembic_version`**
- On an empty database, the `concepttrail` schema does not exist until revision `0001` creates it. Alembic must create and read its version table before that, so the table cannot live inside `concepttrail`.
- Keeping it in `public` also keeps Alembic bookkeeping out of the 26-table application contract.
- A baseline downgrade can then drop `concepttrail` while Alembic still records that the database is at `base`.

**Transactions**
- PostgreSQL DDL is transactional, and all of revision `0001` (extension, schema, tables, indexes, version row) runs in one transaction. A failed upgrade leaves no partial schema and no version row.

## Revision naming

- Use `--rev-id` with the next zero-padded number (`0002`, `0003`, …) and a short imperative message. The file becomes `0002_<slug>.py`.
- `version_num` is limited to 32 characters by Alembic.
- Keep history linear. One head only; a test asserts this.

## Creating a new migration

1. Change `app/db/models.py`, and record the decision in `docs/PUBLIC_DECISIONS.md` (owner approval is required for any schema change).
2. Start a disposable database (below) and bring it to head:

   ```bash
   DATABASE_URL=<disposable> alembic upgrade head
   ```

3. Autogenerate **against that disposable database only**:

   ```bash
   DATABASE_URL=<disposable> alembic revision --autogenerate --rev-id 0002 -m "short description"
   ```

   Autogenerate is not read-only. It creates `public.alembic_version` if that table is missing.

4. Review the file by hand and complete its checklist. Autogenerate does **not** emit:
   - extensions, schemas, data backfills, or `CHECK` constraints;
   - renames (it emits drop + add instead).

   It can also render third-party types as unimported module paths; this happened for `VECTOR` in `0001`. Make every name, type, nullability and `schema="concepttrail"` explicit.

5. Never import `app.db.models` inside a revision. Revisions are frozen operations.
6. Prove the revision on disposable databases: upgrade, check, downgrade, re-upgrade, plus the automated suite. Run `pytest -m migration_db`.
7. Update `tests/fixtures/concepttrail_schema_baseline.json` only from a read-only capture of a migrated database. Do it only after the change is approved and applied, and never by hand.

## Review requirements

Every revision must satisfy all of these before it is committed:

- **Additive by default.** Drops, type changes and NOT NULL additions need data checks, a backfill plan and explicit owner approval.
- **No silent schema decisions.** `subject_id` stays VARCHAR, and `embedding_chunk` keeps exactly nine columns with an unbounded `VECTOR`, unless an approved decision says otherwise. No Bell-Ringer or doubt tables without approval.
- **Guarded destruction.** A downgrade that would drop data must be guarded by an explicit `-x` opt-in, or be impossible.
- **Rehearsed.** Locking impact has been considered. The offline SQL (`alembic upgrade <rev> --sql`) has been read. Upgrade, downgrade and re-upgrade have passed on a disposable database.

## Revision 0001 (baseline)

**Upgrade.** Runs in one transaction, in this order:
1. A guard refuses to run if `concepttrail` already contains any object.
2. `CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public`. Then it asserts that the extension lives in `public`.
3. `CREATE SCHEMA IF NOT EXISTS concepttrail`.
4. It creates 26 tables (188 columns), 26 PKs (8 composite), 35 FKs, 4 UNIQUE constraints and 19 `idx_*` indexes.
5. `embedding_chunk.embedding` uses `pgvector.sqlalchemy.VECTOR()` with no dimension.

The operations are frozen: the revision does not import application models.

**Downgrade.** It requires `-x allow_baseline_downgrade=yes`. It then:
- drops the 19 indexes and 26 tables;
- runs a plain `DROP SCHEMA concepttrail` (RESTRICT, never CASCADE);
- leaves the `vector` extension installed, because it is shared, database-wide and lives in `public`;
- leaves `public.alembic_version` empty, which means `base`.

**Does not apply to existing databases.** A database that already holds this schema, like the owner's, is never upgraded through `0001`. It is stamped instead.

## pgvector handling

- The extension is created by revision `0001`, before any table, in `public`. Creating an extension needs a superuser or a role allowed to create it. In a hosted environment where the migration role lacks that privilege, a DBA pre-creates it; `IF NOT EXISTS` then makes the statement a no-op.
- The unqualified `VECTOR` type resolves through `public` on the search path, which is the default `"$user", public`. Do not remove `public` from the migration role's search path.
- No vector dimension and no ANN index (HNSW/IVFFlat) exists until an embedding model is benchmarked and approved. Adding either is a separate, reviewed revision.
- Downgrades never drop the extension.

## Upgrade and downgrade procedure (any non-disposable database)

1. Confirm that the owner has approved this specific revision and target.
2. Back up first, using the [backup steps](#backup-requirements).
3. Review the SQL:

   ```bash
   alembic upgrade <rev> --sql
   ```

4. Verify the starting state read-only:

   ```bash
   python -m app.db.schema_snapshot
   alembic current
   ```

5. Apply the revision. Then re-verify with `python -m app.db.schema_snapshot` and `pytest -m live_db`.
6. Downgrades of a non-disposable database are recovery operations. Prefer restoring the backup, and never downgrade past data that would be lost.

## Safe baseline stamping (owner approval required)

`alembic stamp 0001` writes only the version table. It creates `public.alembic_version` and inserts `'0001'`, and it runs **no** DDL on the 26 application tables.

The existing database therefore does not need to be recreated. Once stamped, Alembic treats it as already at the baseline, and future revisions apply on top of it. The disposable-database test `test_existing_unversioned_schema_is_refused_then_stamped` rehearses exactly this. In that test, an upgrade of the unversioned schema is refused, then `stamp 0001` succeeds without changing any application object.

Procedure for the owner's development database. **Do not run it without the owner's explicit approval.**

1. **Back up** as described in the [backup steps](#backup-requirements), and verify the dump can be listed (`pg_restore --list`).
2. **Verify read-only** that the database equals revision `0001`:

   ```bash
   python -m app.db.schema_snapshot                   # must print "no differences" and "absent (database not stamped)"
   python -m pytest -q -rs -m live_db tests/integration
   ```

3. **Confirm the target:**
   - `alembic.ini` has no URL;
   - the `.env` `DATABASE_URL` points at `127.0.0.1:5433/concepttrail_db`;
   - no `DATABASE_URL` override is exported in the shell.

4. **Stamp.** This is the only write:

   ```bash
   alembic stamp 0001
   ```

5. **Verify:**
   - `alembic current` shows `0001 (head)`;
   - `python -m app.db.schema_snapshot` shows `public.alembic_version: ['0001']` and no differences;
   - the `live_db` suite passes.

**Undo**, if stamping was a mistake: `alembic stamp base`. This removes only the version row, never application objects.

## Disposable database testing

These steps use a separate container, volume, port and generated password. They never use `concepttrail-postgres`, `concepttrail_pgdata`, port `5433`, or the root `.env`.

```bash
# 1. Check that the names and port are free (abort if any already exists).
docker ps -a --format '{{.Names}}' | grep -x concepttrail-migtest-postgres
docker volume ls --format '{{.Name}}' | grep -x concepttrail_migtest_pgdata
lsof -nP -iTCP:5434 -sTCP:LISTEN

# 2. Generate credentials into a private file OUTSIDE the repository (never printed).
umask 077
python -c "import secrets; print('POSTGRES_USER=ct_migtest\nPOSTGRES_DB=ct_migtest_admin\nPOSTGRES_PASSWORD=' + secrets.token_hex(32))" > /path/outside/repo/migtest.env

# 3. Start the disposable server.
docker volume create --label concepttrail.purpose=migration-test concepttrail_migtest_pgdata
docker run -d --name concepttrail-migtest-postgres --label concepttrail.purpose=migration-test \
  --env-file /path/outside/repo/migtest.env -p 127.0.0.1:5434:5432 \
  -v concepttrail_migtest_pgdata:/var/lib/postgresql pgvector/pgvector:0.8.7-pg18-trixie

# 4. Export URLs without echoing them; values come from the private file.
set -a; . /path/outside/repo/migtest.env; set +a
export CONCEPTTRAIL_MIGRATION_TEST_ADMIN_URL="postgresql+psycopg://$POSTGRES_USER:$POSTGRES_PASSWORD@127.0.0.1:5434/$POSTGRES_DB"

# 5a. Automated lifecycle suite (creates and drops its own ct_migtest_* databases).
python -m pytest -q -rs -m migration_db tests/integration

# 5b. Manual lifecycle on one throwaway database.
docker exec concepttrail-migtest-postgres createdb -U ct_migtest ct_migtest_manual
export DATABASE_URL="postgresql+psycopg://$POSTGRES_USER:$POSTGRES_PASSWORD@127.0.0.1:5434/ct_migtest_manual"
alembic upgrade head && alembic check && python -m app.db.schema_snapshot
alembic -x allow_baseline_downgrade=yes downgrade base
alembic upgrade head
unset DATABASE_URL CONCEPTTRAIL_MIGRATION_TEST_ADMIN_URL POSTGRES_PASSWORD

# 6. Remove ONLY the resources created above; never prune.
docker rm -f concepttrail-migtest-postgres
docker volume rm concepttrail_migtest_pgdata
rm /path/outside/repo/migtest.env
```

The `migration_db` suite has its own guards. It refuses to run when the admin URL has the same host and port as the `.env` `DATABASE_URL`, or when the server hosts a database named `concepttrail_db`. It only creates and drops databases named `ct_migtest_<random>`.

## Backup requirements

Take a backup before any `upgrade`, `downgrade` or `stamp` on a non-disposable database. Keep backups outside the repository and outside the Docker volume, with restricted permissions, and do not print or commit them.

```bash
docker exec concepttrail-postgres pg_dump -U <db_user> -d concepttrail_db -Fc -f /tmp/concepttrail_<UTC-timestamp>.dump
docker cp concepttrail-postgres:/tmp/concepttrail_<UTC-timestamp>.dump /secure/backups/
docker exec concepttrail-postgres rm /tmp/concepttrail_<UTC-timestamp>.dump
pg_restore --list /secure/backups/concepttrail_<UTC-timestamp>.dump > /dev/null   # dump is readable
```

Before relying on the dump, restore it into a **disposable** database (never over the original) and run `python -m app.db.schema_snapshot` against the restore.

## Recovery and rollback expectations

- **Failed upgrade:** the transaction rolls back, so there is no partial schema and no version change. Fix the revision, re-test it on a disposable database, then retry.
- **Wrong stamp:** `alembic stamp <correct revision>` or `alembic stamp base` changes only the version row.
- **Bad applied revision on a database with data:** restore from the pre-migration backup into a new database, verify it, then switch over. Use a revision's downgrade only if it was proven to preserve data on a disposable copy.
- **Never** drop or recreate the `concepttrail` schema, the database or `concepttrail_pgdata` to "reset" migration state, and never re-run `db/schema/001_initial_schema.sql` against an existing database.

## Verification checklist

```bash
python -m pytest -q tests/unit                                  # includes offline SQL contract of 0001
python -m pytest -q -rs -m live_db tests/integration            # read-only, owner database
python -m pytest -q -rs -m migration_db tests/integration       # disposable server only
python -m app.db.schema_snapshot                                # read-only diff of DATABASE_URL vs ORM
alembic history && alembic heads                                # single linear head: 0001
python -m ruff check app tests && python -m ruff format --check app tests
```
