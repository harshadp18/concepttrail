# Frontend integration guide (backend-owned contract only)

The frontend is built separately by the project owner. Claude Code must not create or modify frontend files. This document defines the deliverables the backend must expose for integration.

## Backend deliverables

- REST API under `/api/v1` with request/response schemas in Pydantic.
- OpenAPI JSON generated from the running FastAPI application (expected route `/openapi.json`) and a versioned checked-in export under `docs/openapi/` only after implementation and review.
- Consistent error envelope with stable machine-readable error code and request ID.
- Documented session/authentication mechanism, expiry and logout behavior.
- CORS allowlist configured through environment settings; no wildcard origin with credentials.
- Explicit role and classroom authorization behavior.
- Pagination, filters, sorting, retry/idempotency behavior and timestamps documented per endpoint.

## Minimum API areas

Authentication/session; current-user context; curriculum/class/subject selection; topic/content retrieval; doubts; question delivery; attempt submission; student progress; teacher class dashboard; Bell-Ringer draft and approval where persistence is approved; ingestion job status. Exact route contracts live in `docs/API_CONTRACTS.md`.

## Contract acceptance

1. All API routes have typed request/response models and documented status/error codes.
2. OpenAPI is generated from actual routes, not hand-maintained fiction.
3. Contract tests validate representative success, authorization failure, validation error and idempotent retry.
4. A sample `curl` call is documented for each user-facing route.
5. CORS uses explicit configured origins.
6. No frontend framework or UI implementation is selected in this workspace.
