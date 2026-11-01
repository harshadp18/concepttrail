# Implementation roadmap and phase gates

The following sequence is adapted from the user-designated attached README. Execute in order. The Phase 0–7 grouping in the root README is a compact view; this detailed roadmap is authoritative. Start with inspection and a small rights-cleared pilot. Do not begin by fine-tuning an LLM or ingesting every textbook.

## Status (updated 2026-10-31)

| Item | Status |
|---|---|
| Extraction pilot (roadmap Phases 3–4 executed on 10 documents, 222 pages: extraction, selective OCR, cleaning, structuring, validation and human page review) | **Completed.** The project owner approved the pilot and its recorded quality-gate results on 2026-10-31. Scope is the pilot only; the full corpus has not been extracted. |
| Teacher validation of generated objectives and topic lists | Completed through an owner attestation. Individual approval outcomes are not recorded and are kept distinct from completion. |
| Human page-quality review | Completed through an owner attestation for the 22 reviewed pages. Individual findings are not recorded. |
| Phase 5: knowledge components and prerequisite graph | **Engineering complete; not formally closed.** Loader, source resolution, review log and anchors, lifecycle, released snapshots, coverage, import tooling and pilot tooling are built and tested on synthetic data. Closure waits on owner decisions (D1–D18, R1–R7), real reviewers, the D4 and D11 pilots and curated data. See `PHASE_5_PROGRESS.md`. |
| Provider adapters, embeddings, full-corpus extraction | Not started. Phase 5 is the next phase; its prerequisites have not been validated. |

Approvals and attestations are private records; see `PUBLICATION_AND_REPRODUCIBILITY.md`. Open items from the pilot remain open and are not hidden by this status.

## Phase 0 — Inspect the actual backend repository and environment (read-only)

**Objective:** identify what exists and avoid rebuilding it.

**Read first:** root `CLAUDE.md`, root `README.md`, `docs/PUBLIC_DECISIONS.md`, relevant module READMEs, `docs/DATABASE_SCHEMA.md`.

**Actions:** capture tree/branch/commit; inspect backend dependencies, `.env.example`, routes, models, Alembic, tests and deployment; inspect any existing frontend only to record its location and API integration needs, without editing it; run existing backend tests; introspect PostgreSQL `concepttrail` schema read-only; classify features by evidence. Do not expose secrets.

**Pass:** code-backed status report, DB introspection snapshot and smallest-change plan. Never rerun `001_initial_schema.sql` on the user's database.

## Phase 1 — Reproducible environment

Create isolated Python 3.11+ environment; install pinned phase-appropriate dependencies; validate settings; configure structured redacted logging and health endpoint; test DB connection.

**Commands (after corresponding code exists):**

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev,pipeline]"
pytest -q
ruff check .
ruff format --check .
```

**Pass:** app startup/config validation and one smoke test pass.

## Phase 2 — Resource intake, teammate CSV cleaning and master curriculum/source inventory

**Read first:** `resources/README.md`, `resources/textbook_pdfs/README.md`, `resources/teammate_csv/README.md`, `resources/teammate_csv/incoming/README.md`, `docs/CSV_CLEANING_SPEC.md`, `data_pipeline/README.md`, `data_pipeline/stages/README.md`.

**User hand-off:** the user copies original textbook PDFs into `resources/textbook_pdfs/` and the teammate's CSV file(s) into `resources/teammate_csv/incoming/`. Do not request the user to pre-clean or rename files.

**CSV tasks:** inspect each CSV's headers, encoding, delimiter, row count, data types, missingness, duplicates and anomalies; create a byte-identical hash snapshot; produce a profile; identify dataset purpose; define explicit cleaning/schema/mapping rules; generate accepted/rejected outputs and a row-reconciled quality report. Preserve original columns/order and leading-zero IDs; no factual auto-correction. Cross-check against PDFs only after source match and local-processing rights are confirmed.

Create/update only `data_pipeline/curriculum.csv` for the canonical inventory. This is exactly 29 columns in the agreed order. A teammate export is not automatically the master inventory. Include every class 6–10 × five agreed subjects and explicit course/language variants. Verify each source against current official curriculum records; record exact source title, version/session, URL, date, checksum and purpose-specific rights. Missing/blocked items remain rows.

**Pass:** all 25 combinations have explicit statuses; teammate CSV input, accepted/rejected rows and quality report reconcile; the 29-column canonical inventory remains unique; no PDF content is processed when rights are unknown/insufficient.

## Phase 3 — Acquisition and extraction

Build idempotent acquisition and SHA-256 manifest. PyMuPDF text-native extraction first; record page count, page index, text length, images and tool version. Use Tesseract only for low/empty-text or scanned pages and permitted language packs. Keep raw page JSON immutable. Preserve printed page labels separately from PDF page indices.

**Pass:** source hash and page count reconcile; low-text/OCR pages are flagged; a sample Maths and non-Maths PDF has reviewed extraction.

## Phase 4 — Clean, structure and validate content

Clean headers/footers and line wraps using reversible tested transforms. Preserve scripts, symbols, equations, units, tables, figures, maps, question numbering, page locators and chapter/section boundaries. Generate structured textbook JSON; apply human overrides after machine stages; quarantine malformed or uncertain content.

**Pass:** provenance and schema are complete; human reviewer validates representative original pages against output.

## Phase 5 — Knowledge components and prerequisite graph

Generate candidate KCs from reviewed curriculum/content. Use stable subject-neutral keys; add objectives, skill types, misconceptions and source refs. Propose edges only with pedagogical evidence; validate endpoint existence, self-edge rejection and directed acyclicity; human-review all released edges. Do not assume roots must be in Class 6.

**Pass:** unique IDs, no orphan endpoints/cycles, reviewed edges and coverage reports by class/subject.

## Phase 6 — Notes, questions and verification

Generate drafts only from approved contexts and constrained recipes. Validate Pydantic schemas; retry invalid model output once then quarantine. Keep question version, type, answer/rubric, KC mapping, provenance, prompt/model version and verification record. Use deterministic checks for supported arithmetic/algebra; use reviewed rubrics for language/open responses/maps/interpretation.

**Pass:** no unverified note/question becomes active; human-reviewed sample per subject/content type.

## Phase 7 — Storage, embeddings and retrieval

Publish canonical data transactionally to PostgreSQL. Chunk by semantic structure; preserve provenance via `content_unit`. Benchmark one multilingual embedding model; record exact ID/revision/dimension/normalization/licence; keep `embedding_chunk.embedding` as unbounded `VECTOR` until model is selected. Build a versioned pgvector index from rights-approved chunks only.

**Pass:** retrieval benchmark, citation resolution and class/subject/course/version/rights filter tests pass.

## Phase 8 — Synchronous student flow and LLM integration

Implement auth/authorization, curriculum/topic lookup and doubt API. Use retrieval, provider adapter, Pydantic output contract, deterministic citation checks, bounded timeouts and abstention. One approved primary provider first; enable fallback only after its own privacy, schema and outage tests. Cache by content/KC/recipe/language/provider/model/prompt/schema version.

**Pass:** supported questions answer from approved sources; low-evidence or ambiguous requests clarify/abstain/escalate; provider outage is controlled.

## Phase 9 — Attempts, BKT and deterministic policy

Define item scoring method and KC evidence mapping. Implement pure BKT formula and hand-calculated tests. Persist attempts idempotently and update state transactionally. Keep quiz percentage and BKT probability separate. Implement configurable quiz bands, mastery bands, practice ladder, retest scheduling and priority breakdown. Synthetic cohort is labelled simulation.

**Pass:** repeated attempt ID changes mastery once; expected next action is reproducible and LLM-independent.

## Phase 10 — Teacher dashboard and Bell-Ringer

Enforce classroom assignment at backend. Calculate reproducible class-level aggregates and explainable root-gap ranking. Gate Bell-Ringer on recent-response coverage (around 60% proposed) and minimum group size (around five proposed). Low coverage returns insufficient data and the 3-question paper-check alternative. Generate draft, verify answer key and require teacher approval/edit/reject.

**Schema gate:** the current 26-table schema has no Bell-Ringer activity/audit table. Do not implement durable approval state until the owner approves a migration.

**Pass:** unassigned teachers are denied; low coverage blocks; teacher action is auditable in approved persistence design.

## Phase 11 — Expand across agreed classes and subjects

Process sources only as rights permit. Add subject-specific extraction, scoring and evaluation fixtures. Track inventory chapters, approved KCs/questions, indexed chunks and retrieval benchmarks independently.

**Pass:** all five classes and five subject families appear in coverage report; each release slice meets its own quality/rights gate.

## Phase 12 — Security, deployment and operations

Pin dependencies, configure production secrets/TLS/rate limits/backups/retention/deletion, isolate file processing, set provider budgets/timeouts, redact logs, exercise index rollback/source withdrawal and test backup restore. Deployment topology is selected only after local tests work.

**Pass:** unit/integration/E2E/security/restore/rollback gates pass; privacy/legal and school/vendor checks are complete before real student data.

## Frontend exclusion

The user is developing the frontend separately. Claude Code must not create, scaffold, design or modify frontend pages, components, styling, state stores, PWA screens or browser code. Phase 0 may inspect an existing frontend read-only to note its location and derive integration constraints. Backend delivery includes exact REST contracts, OpenAPI output, CORS configuration and `docs/FRONTEND_INTEGRATION.md`; a missing frontend is not a failed backend phase.

## Self-healing rules for every phase

1. On test failure, reproduce with the smallest focused test and inspect the failing input/output before editing.
2. Never weaken assertions, remove tests or mark a phase complete just to move forward.
3. When a spec conflicts with the live DB, stop before DDL; export read-only introspection, identify exact delta and prepare a reviewed reversible migration.
4. When source rights are unknown, quarantine/block the source stage; do not substitute an unlicensed source silently.
5. When provider output fails validation, retry at most once for recoverable schema errors, then quarantine/abstain; do not loosen the schema.
6. When retrieval filters fail, fail closed and add a regression test before publishing the index.
7. Do not implement frontend code. Inspect existing UI only read-only if present; document API integration points for the separately built frontend.
