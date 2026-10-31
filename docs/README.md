# `docs/` — engineering specifications

Read the relevant document before changing its subsystem. Update source traceability and decisions with every cross-layer change.

- `SOURCE_AUDIT.md`: attached README source basis, what was not provided, and implementation evidence boundary. The selection PPT/deck is intentionally excluded from this revision.
- `DECISIONS.md`: confirmed architecture choices, preserved database contract and owner approvals required for changes.
- `ARCHITECTURE.md`: runtime, ingestion, retrieval, BKT and module boundaries.
- `DATABASE_SCHEMA.md`: 26-table ERD contract, relationships, constraints and migration rules.
- `DATA_PIPELINE.md`: one master CSV, rights, PDFs, page-aware JSON, derived CSVs, QC and publishing.
- `AI_AND_PROVIDER_STRATEGY.md`: BKT, deterministic policy, RAG, one-primary-provider posture, fallback gate and embedding selection.
- `API_CONTRACTS.md`: proposed `/api/v1` API paths, request/response/security contracts and schema caveats.
- `IMPLEMENTATION_ROADMAP.md`: ordered phases, exact exit gates and recovery rules.
- `REQUIREMENTS_TRACEABILITY.md`: evidence-bound requirements and acceptance criteria.
- `SECURITY_PRIVACY.md`: student/minor privacy, access control, copyright and operational controls.
- `RISKS_AND_DECISIONS.md`: unresolved blockers and mitigations.
- `TROUBLESHOOTING.md`: local environment, database, extraction, retrieval, BKT and provider failures.

No module is considered implemented merely because a README specifies it.

## Standard implementation specification

### 1. Module Purpose & Architectural Role

Cross-layer architecture, data, AI, API, security and delivery specifications.

### 2. Recent Updates Incorporated in This Module

Source audit explicitly excludes deck; traceability derives from the attached README and owner-confirmed schema decisions.

### 3. File Manifest

See the document index in this README and the root README.

### 4. Data Structures, Types & Schemas

Decision records and traceability tables are authoritative for requirement status and owner approvals.

### 5. File-by-File Implementation Specification

Read the relevant docs before changing a domain; update decision/traceability and module docs in the same change.

### 6. Integration Points

All module READMEs link to these cross-cutting specifications.

### 7. Module Verification Checklist

Check links, table/code fences, phase references and stale source/deck wording.

- `CSV_CLEANING_SPEC.md`: teammate CSV drop-zone, profiling, deterministic cleaning, validation, PDF cross-check, accepted/rejected artifacts and approval workflow.
- `FRONTEND_INTEGRATION.md`: backend API/OpenAPI hand-off for a frontend built separately by the owner; Claude Code must not implement UI code.
