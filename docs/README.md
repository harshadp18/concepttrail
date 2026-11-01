# `docs/` — engineering specifications

Read the relevant document before changing its subsystem. Update source traceability and decisions with every cross-layer change.

- `PUBLIC_DECISIONS.md`: the public decision register: preserved database contract, authentication model, provider selection, deterministic-versus-AI boundary, rights rule and migration approval.
- `ARCHITECTURE.md`: runtime, ingestion, retrieval, BKT and module boundaries.
- `DATABASE_SCHEMA.md`: 26-table ERD contract, relationships, constraints and migration rules.
- `DATA_PIPELINE.md`: one master CSV, rights, PDFs, page-aware JSON, derived CSVs, QC and publishing.
- `AI_AND_PROVIDER_STRATEGY.md`: BKT, deterministic policy, RAG, provider posture (Ollama/Qwen primary, disabled Groq fallback), fallback gate and embedding selection.
- `PUBLICATION_AND_REPRODUCIBILITY.md`: what a public checkout contains, which files stay private, fresh-clone runtime dependencies on private records, and how the private owner attestation is supplied and verified.
- `PHASE_5_CSV_CONTRACT.md` and `PHASE_5_REVIEW_GUIDELINES.md`: proposed KC and prerequisite CSV contracts, validation rules, database mapping and the human review procedure (awaiting owner approval).
- `PHASE_5_IMPLEMENTATION_HANDOFF.md`: the exact build order for the KC and prerequisite CSV loader (milestones M1–M6), dry-run behaviour, the import-ready plan and what is ready, blocked or needs separate approval.
- `PHASE_5_OWNER_DECISION_CHECKLIST.md`: every outstanding Phase 5 owner decision (D1–D18, R1–R7) in one sheet: proposal, recommendation, what it blocks and the exact owner action.
- `PHASE_5_PROGRESS.md`: authoritative Phase 5 scope (KCs and the prerequisite graph), what is built, what is blocked and the owner decisions needed.
- `PROVIDER_READINESS.md`: what exists for the LLM providers (no adapter yet), environment variables, error handling, telemetry, local-versus-remote deployment and the synthetic smoke-test plan (D-055).
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
