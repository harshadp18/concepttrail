# `deploy/` — local and hosted deployment

## Current local setup

The owner reports using a Windows-installed PostgreSQL 18 server with pgvector 0.8.7 enabled through pgAdmin. The application may connect directly via `DATABASE_URL`; Docker is optional, not a prerequisite. Do not start a second PostgreSQL server/container if the local server is already the intended database.

## Docker

`Dockerfile` and `compose.yaml` are optional templates for a reproducible local or hosted environment. Before using them, decide whether PostgreSQL is managed externally or run in Compose. Never run two competing development databases without documenting which is canonical.

## Production requirements

- Separate production DB and secrets from developer laptop credentials.
- TLS connections, least-privilege DB users, network restrictions, rate limiting and provider spend limits.
- Managed object storage or private file store for source/processed artifacts.
- Durable background job execution for ingestion and scheduled Bell-Ringers.
- Automated DB backups and tested restore procedure.
- Versioned content/index releases and rollback to last known good index.
- Health/readiness checks for API, DB and worker; alerts for failures/quotas/latency.
- No real student pilot until privacy/legal/school review is complete.

Deployment provider and cost are not selected in this pack. Measure load and review current pricing/data terms rather than assuming a free tier is permanent.

## Standard implementation specification

### 1. Module Purpose & Architectural Role

Optional container/deployment assets after local application and tests work.

### 2. Recent Updates Incorporated in This Module

Do not force Docker for local PostgreSQL development; deployment is blocked on privacy, source rights, provider terms and restore/rollback tests.

### 3. File Manifest

`Dockerfile`, `compose.yaml`; use only after validating build/start commands.

### 4. Data Structures, Types & Schemas

Settings from environment/secrets; no keys in image or compose source; health/readiness separated from provider health.

### 5. File-by-File Implementation Specification

Run as non-root, use pinned dependencies, persist PostgreSQL/files safely, isolate ingestion worker, enforce TLS/rate limits at hosting layer.

### 6. Integration Points

Builds FastAPI application; deployment receives environment config and approved DB/index versions.

### 7. Module Verification Checklist

Container build, health smoke test, backup/restore, rollback, secret scan and provider timeout test.
