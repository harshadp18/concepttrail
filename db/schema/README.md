# SQL schema snapshots

`001_initial_schema.sql` is the 26-table baseline bootstrap for a clean `concepttrail` schema. It is included for reproducibility and reference. The owner reports having already created the tables; do not rerun this file on the existing database. Future schema changes belong in Alembic migrations after the database is introspected and baselined.

## Standard implementation specification

### 1. Module Purpose & Architectural Role

Canonical reference for a clean schema build, not a repeatable migration for the owner's existing database.

### 2. Recent Updates Incorporated in This Module

26 tables; subject IDs remain VARCHAR; embedding column is unbounded VECTOR; no extra Bell-Ringer or doubt-thread tables.

### 3. File Manifest

`001_initial_schema.sql` contains the 26-table bootstrap; `docs/DATABASE_SCHEMA.md` explains relationships and participation.

### 4. Data Structures, Types & Schemas

Treat the SQL file as immutable baseline snapshot. All live changes go through approved Alembic migration after introspection and backup.

### 5. File-by-File Implementation Specification

Do not edit snapshot to patch production; create separately numbered migration; inspect FKs, nullability, unique/check constraints and index compatibility.

### 6. Integration Points

Used by new isolated test DBs only; live application ORM is based on inspected schema.

### 7. Module Verification Checklist

Count 26 CREATE TABLE statements; verify extension separately; no execution against populated DB.
