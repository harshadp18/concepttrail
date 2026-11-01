# Version 1 routes

The route module names target auth, curriculum, doubts, attempts, progress, teacher and jobs. Implement a route only after defining its Pydantic contract and service boundary. Route handlers should be short, async where appropriate, and use DB dependencies and authorization dependencies. No direct provider SDK calls, SQL query construction, BKT math or graph traversal inside routes. See `docs/API_CONTRACTS.md`.

## Standard implementation specification

### 1. Module Purpose & Architectural Role

Version 1 route modules for agreed student, teacher and operator API.

### 2. Recent Updates Incorporated in This Module

Use exact route list in `docs/API_CONTRACTS.md`; include `GET /me`, topics, student progress, the teacher heatmap and Bell-Ringer topic analysis (`bell_ringer.py`). Bell-Ringer cycle persistence answers 503 until proposed migration 0004 is approved.

### 3. File Manifest

Proposed routers: `auth.py`, `curriculum.py`, `doubts.py`, `attempts.py`, `progress.py`, `teacher.py`, `jobs.py`; `__init__.py` exports router aggregate.

### 4. Data Structures, Types & Schemas

Prefix `/api/v1`. Attempt payload excludes correctness, learner identity and KC IDs. Doubt payload includes class/subject/curriculum/language and question. Topic route uses KC ID.

### 5. File-by-File Implementation Specification

Use shared request-scoped DB session and auth dependencies; validate role/class assignment before service call; set bounded response timeouts; return 202 only for accepted background jobs.

### 6. Integration Points

Depends on `app/schemas`, `app/core`, `app/services`; API schemas are not ORM models.

### 7. Module Verification Checklist

Test each route's schema/status/security cases; deny unassigned teacher; replay attempts with same idempotency key.
