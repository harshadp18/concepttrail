# `app/api/` — API route layout

Keep `/api/v1` modules small and domain-specific. Target modules: `auth.py`, `curriculum.py`, `doubts.py`, `attempts.py`, `progress.py`, `teacher.py`, `jobs.py`. The root `app/README.md` and `docs/API_CONTRACTS.md` define boundaries and proposed routes. Routes should call services and use request-scoped DB dependencies; they must not implement SQL joins, BKT formulas or provider fallback logic inline.

## Standard implementation specification

### 1. Module Purpose & Architectural Role

Transport boundary for versioned REST endpoints; no domain algorithms or direct persistence.

### 2. Recent Updates Incorporated in This Module

All routes derive identity from session; teacher routes enforce assigned classroom; doubt routes abstain without evidence; attempt route owns idempotent submit flow by delegation.

### 3. File Manifest

`v1/` contains domain routers for auth, curriculum/topics, doubts, attempts, progress, teacher and jobs; create only modules needed by approved API contract.

### 4. Data Structures, Types & Schemas

Use `/api/v1` prefix and `docs/API_CONTRACTS.md`; request/response Pydantic types in `app/schemas`; response error shape is `{error:{code,message,request_id}}`.

### 5. File-by-File Implementation Specification

Each handler validates DTO, resolves auth/role/class scope, calls exactly one service operation, maps domain outcomes to HTTP status, and returns DTO. No SQL, BKT formulas, graph traversal, prompt templates or provider SDK in routes.

### 6. Integration Points

Consumes `app/core` dependencies and `app/services`; never import pipeline stage modules.

### 7. Module Verification Checklist

HTTPX tests for valid/invalid body, auth, forbidden class, pagination and error mapping.
