# `app/` — FastAPI application

## Responsibility

`app/` contains the online application. It exposes authenticated APIs and coordinates curriculum lookup, doubt handling, assessments, BKT updates, retrieval, provider calls, verification, and teacher workflows. It is a modular monolith; do not split into microservices in the first release.

## Layer rules

- `api/v1/`: HTTP concerns only: parse/validate request, authenticate/authorize, call service, shape response.
- `schemas/`: Pydantic request/response contracts. Never use ORM entities as public response contracts.
- `services/`: application/domain logic: BKT, graph, policy, retrieval, provider routing, answer verification, caching, Bell-Ringer.
- `db/`: SQLAlchemy models, sessions, repositories and Alembic migrations.
- `core/`: settings, security helpers, logging and typed errors.

## Required implementation order

1. `core/config.py`, `db/session.py`, health endpoint.
2. SQLAlchemy models matching the existing `concepttrail` PostgreSQL schema after introspection.
3. Repositories for subjects/curriculum/source documents.
4. Read-only curriculum endpoints.
5. Question/attempt flow and BKT transaction.
6. Retrieval/LLM/verification flow.
7. Teacher analytics and Bell-Ringer jobs.

## Critical rules

- No direct SQL in route modules; use repositories/services.
- Never trust a client-submitted learner ID, answer correctness, KC mapping, or mastery value.
- Use request-scoped DB sessions and explicit transaction boundaries.
- Attempt insertion, idempotency check, and current BKT state update must be transactionally consistent.
- Use typed domain errors and stable API error responses.
- Keep LLM prompts outside API route files.
- Every teacher endpoint must enforce assignment/classroom authorization.

See `api/README.md`, `core/README.md`, `db/README.md`, `schemas/README.md`, and `services/README.md`.

## Standard implementation specification

### 1. Module Purpose & Architectural Role

Online FastAPI modular monolith; owns authenticated APIs and online learning workflows, not offline PDF ingestion or a separate microservice fleet.

### 2. Recent Updates Incorporated in This Module

Use source-grounded RAG; BKT and policy remain deterministic; multi-KC evidence is explicit; Bell-Ringer is a draft and durable state requires an approved migration.

### 3. File Manifest

`main.py` (FastAPI app/factory and health/readiness routes); `api/` (HTTP routers); `core/` (settings/security/logging/errors); `db/` (sessions/models/repositories/migrations); `schemas/` (Pydantic DTOs); `services/` (domain services).

### 4. Data Structures, Types & Schemas

Routes depend on `schemas`, `core` dependencies and `services`; services depend on repositories and pure domain functions; ORM models never escape as API payloads. Identity is session-derived.

### 5. File-by-File Implementation Specification

Initialize settings and logging, expose health route, configure lifespan and DB dependency, register versioned routers, map typed domain errors, then wire each workflow through schema → service → repository → route.

### 6. Integration Points

Consumes published PostgreSQL curriculum/content and `embedding_chunk`; called by student/teacher clients; external provider calls only through `llm_provider`.

### 7. Module Verification Checklist

`pytest -q tests/unit tests/integration`; `ruff check app`; smoke-test health, auth boundary, DB dependency and route registration.


## Frontend boundary

This workspace implements the backend only. Do not add frontend code. Keep all request/response contracts typed and expose OpenAPI for the separately developed client.
