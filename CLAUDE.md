# Claude Code instructions — ConceptTrail

## Mission and source hierarchy

**Execution-scope override:** Claude Code owns the backend, database integration, curriculum/resource ingestion, teammate CSV cleaning, AI/RAG services, BKT/graph/policy logic, tests, evaluation, operations and deployment. The user will build the frontend separately. Do not create, scaffold, redesign or modify frontend code, UI components, pages, styling, browser state, PWA screens or service workers. During Phase 0 only, inspect any existing frontend read-only to document its location and integration needs. The absence of frontend code is not a backend phase failure. Produce a complete OpenAPI contract and a frontend integration guide instead.



Implement ConceptTrail as a maintainable FastAPI modular monolith for CBSE Classes 6–10 across English, Hindi, Mathematics, Science and Social Science. The user-designated attached ConceptTrail `README.md` is the primary product/engineering context for this package. The selection PPT/deck is intentionally excluded and must not be used to introduce requirements. The root `README.md` is the executable workspace blueprint; `docs/` and module READMEs define cross-layer contracts.

Read the root `README.md` completely before coding. Then read `docs/PUBLIC_DECISIONS.md`, `docs/REQUIREMENTS_TRACEABILITY.md`, and the exact target directory's `README.md`. Do not assume the project docs prove implementation status.

## Mandatory first actions (Phase 0)

1. Capture repository tree, Git status/branch/commit, Python version, dependencies, environment files (never print secrets), tests, API routes, SQLAlchemy models, Alembic history and deployment files. If a frontend is present, inspect it read-only and do not modify it.
2. Inspect PostgreSQL `concepttrail` schema read-only. Owner reports PostgreSQL 18, pgvector 0.8.7 and 26 existing tables. Do not rerun `db/schema/001_initial_schema.sql`.
3. Compare live schema with `docs/DATABASE_SCHEMA.md`; record exact columns/types/nullability/constraints and stop before DDL if there is a mismatch.
4. Classify each capability as `implemented and tested`, `implemented but untested`, `partially implemented`, `documented only` or `missing`.
5. Produce a gap report and minimal phase plan before touching working modules.

## Non-negotiable product and pipeline constraints

- Product scope is Classes 6–10 and five agreed subjects. A Maths pilot plus one non-Maths sample is only an engineering proof.
- Maintain exactly one master inventory: `data_pipeline/curriculum.csv`. Do not create `resources.csv` or `sources.yaml` as parallel masters.
- Preserve the exact agreed 29-column CSV header and column order. The current `subject_id` mapping is a string because the deployed schema uses `VARCHAR`.
- User-provided source files are copied into explicit resource intake folders: `resources/textbook_pdfs/` and `resources/teammate_csv/incoming/`. Preserve originals byte-for-byte. Keep immutable raw snapshots, CSV profiles, accepted/rejected CSV outputs, page-aware extraction JSON, cleaned/structured JSON, human overrides and derived CSV exports separate. Never overwrite an input or raw artifact during cleaning.
- Teammate CSV cleaning is a required workstream: profile first; preserve original headers/order by default; apply only documented deterministic transformations; write accepted and rejected rows separately; produce a quality report and input/output hash manifest. Never fabricate missing data or automatically reconcile ambiguous values from PDFs.
- `kc_components.csv`, `prerequisites.csv`, `questions.csv` are derived outputs; `notes.csv` is the proposed fourth output pending owner confirmation.
- Rights are purpose-specific: internal processing, external-model processing, indexing/RAG, training, display and redistribution are separate permission decisions. Unknown permission blocks that operation.
- Publicly downloadable does not mean software/indexing/training/display rights exist.
- No LLM from-scratch training or LLM fine-tuning in the first release. BKT is a deterministic runtime mastery estimator; optional offline fitting requires suitable, lawful response sequences.
- LLMs never set scores, mastery, graph edges, user roles, access rights, teacher priorities or next-step decisions.
- Use human review for uncertain OCR, equations, maps/diagrams, language writing, subjective responses, KCs and prerequisite edges.
- Minimise student personal data. Never send student names, phone numbers, roll numbers, passwords, tokens or unnecessary learner history to model providers.

## Database contract — do not silently redesign

- The deployed target namespace is `concepttrail`; the user reports a 26-table schema already created. Preserve it pending read-only introspection and explicit owner approval.
- `subject_id` remains `VARCHAR`; an INTEGER conversion requires a reviewed migration touching every FK and import mapping.
- `embedding_chunk` exact fields: `chunk_id UUID PK`, `content_unit_id VARCHAR FK`, `chunk_order INTEGER`, `chunk_text TEXT`, `token_count INTEGER`, `embedding_model_id VARCHAR`, `embedding VECTOR`, `index_generation VARCHAR`, `created_at TIMESTAMPTZ`. Do not add columns without approval.
- Keep vector dimension unbounded until an embedding model is benchmarked and approved. Do not create a dimension-specific ANN index before that decision.
- Do not add Bell-Ringer or doubt-thread persistence tables silently; current schema has no dedicated entity for them. Prepare an approved migration if durable persistence is required.
- The SQL bootstrap is for a clean schema only. Never drop, truncate, recreate or destructively migrate the user's existing DB.

## Architecture and provider guardrails

- Use FastAPI, SQLAlchemy 2.x, Pydantic v2, Alembic, PostgreSQL/pgvector, NetworkX, PyMuPDF, optional Tesseract, pytest and Ruff. Verify compatibility and pin dependencies during implementation.
- PostgreSQL is the source of truth; pgvector is the vector backend. Keep graph edges relational and use NetworkX in process.
- Current provider architecture (D-055, owner decision 2026-10-31): Primary: Qwen 3.5 9B (`qwen3.5:9b`) through local Ollama. Fallback candidate: GPT-OSS 120B (`openai/gpt-oss-120b`) through Groq, **automatic fallback disabled**. Gemini and DeepSeek are not selected. The embedding model is undecided. (D-055) No Ollama or Groq adapter exists yet; typed settings and `.env.example` are configuration only. Groq external processing of textbook content or student data is **not authorised** until the owner approves the scope and the rights/retention conditions are recorded. Never enable fallback (`LLM_FALLBACK_ENABLED`) without integration, security, privacy and reliability tests plus owner approval. Verify actual model IDs, terms, quotas and prices. No free/unlimited claims. Earlier Gemini-primary and DeepSeek-benchmark proposals are historical (D-016, D-018) and superseded.
- Fallback only on transient errors, never around safety/rights/validation/insufficient-evidence outcomes.
- Embeddings are separate from chat generation. Do not select or invent the embedding model/dimension.
- Multi-KC questions require KC-specific scoring evidence; do not apply one overall correctness boolean to every mapped KC.
- Quiz-score percentage rules and BKT mastery probabilities are separate variables/policies.

## Documentation map

| Directory | Read first | Responsibility |
|---|---|---|
| Root | `README.md` | Product blueprint, architecture, source basis, phases and traceability |
| `app/` | `app/README.md` | Online modular monolith and dependency rules |
| `app/api/` | `app/api/README.md` | HTTP boundary and API module map |
| `app/api/v1/` | `app/api/v1/README.md` | Versioned route contracts |
| `app/core/` | `app/core/README.md` | Settings, auth, errors and redacted logging |
| `app/db/` | `app/db/README.md` | SQLAlchemy, sessions, repositories and migrations |
| `app/db/migrations/` | `app/db/migrations/README.md` | Alembic baseline and safe migration process |
| `app/db/repositories/` | `app/db/repositories/README.md` | Persistence/query boundaries |
| `app/schemas/` | `app/schemas/README.md` | Pydantic API/domain/provider contracts |
| `app/services/` | `app/services/README.md` | BKT, graph, policy, RAG, providers, validation and teacher service |
| `resources/` | `resources/README.md` | User drop-zone for teammate CSV and textbook PDF source files; originals are never edited |
| `resources/textbook_pdfs/` | `resources/textbook_pdfs/README.md` | Textbook PDF drop-zone and pairing conventions |
| `resources/teammate_csv/` | `resources/teammate_csv/README.md` | Teammate CSV intake and cleaning hand-off |
| `resources/teammate_csv/incoming/` | `resources/teammate_csv/incoming/README.md` | Place original teammate CSV exports here |
| `data_pipeline/` | `data_pipeline/README.md` | Master inventory, resource intake, CSV cleaning and content pipeline |
| `data_pipeline/stages/` | `data_pipeline/stages/README.md` | Idempotent CSV profiling/cleaning/validation, PDF and content stages |
| `data_pipeline/prompts/` | `data_pipeline/prompts/README.md` | Versioned content-generation prompts |
| `data_pipeline/data/` | `data_pipeline/data/README.md` | Immutable raw snapshots, CSV profiles, cleaned/rejected data, overrides, logs and final artifacts |
| `data_pipeline/data/raw/` | `data_pipeline/data/raw/README.md` | Immutable hash-addressed PDF and teammate CSV snapshots |
| `data_pipeline/data/raw/teammate_csv/` | `data_pipeline/data/raw/teammate_csv/README.md` | Original teammate CSV snapshots, never edited |
| `data_pipeline/data/interim/csv_profiles/` | `data_pipeline/data/interim/csv_profiles/README.md` | CSV profiling artifacts |
| `data_pipeline/data/processed/csv_cleaning/` | `data_pipeline/data/processed/csv_cleaning/README.md` | Accepted/rejected CSV outputs and validation reports |
| `data_pipeline/data/logs/csv_cleaning/` | `data_pipeline/data/logs/csv_cleaning/README.md` | CSV cleaning manifests and redacted logs |
| `data_pipeline/data/overrides/csv_cleaning/` | `data_pipeline/data/overrides/csv_cleaning/README.md` | Human-approved CSV corrections/mappings only |
| `data_pipeline/data/interim/` | `data_pipeline/data/interim/README.md` | Immutable raw extraction JSON |
| `data_pipeline/data/processed/` | `data_pipeline/data/processed/README.md` | Cleaned/structured JSON |
| `data_pipeline/data/overrides/` | `data_pipeline/data/overrides/README.md` | Human corrections |
| `data_pipeline/data/logs/` | `data_pipeline/data/logs/README.md` | QC and job diagnostics |
| `data_pipeline/data/final/` | `data_pipeline/data/final/README.md` | Generated derived CSVs |
| `db/` | `db/README.md` | Schema snapshot and read-only verification |
| `db/schema/` | `db/schema/README.md` | 26-table bootstrap contract |
| `docs/` | `docs/README.md` | Cross-system specification index |
| `evaluation/` | `evaluation/README.md` | Retrieval, answer, policy and BKT benchmarks |
| `training/` | `training/README.md` | Optional BKT fitting only; no LLM training v1 |
| `training/llm_finetuning/` | `training/llm_finetuning/README.md` | Future-only readiness gate |
| `tests/` | `tests/README.md` | Unit, integration, E2E and data regression tests |
| `deploy/` | `deploy/README.md` | Optional deployment after local acceptance |

| `data_pipeline/data/raw/teammate_csv/` | `data_pipeline/data/raw/teammate_csv/README.md` | Immutable hash-addressed snapshots of teammate CSV inputs |
| `data_pipeline/data/interim/csv_profiles/` | `data_pipeline/data/interim/csv_profiles/README.md` | Column-level and row-level CSV profiling reports |
| `data_pipeline/data/processed/csv_cleaning/` | `data_pipeline/data/processed/csv_cleaning/README.md` | Accepted and rejected rows plus deterministic clean outputs |
| `data_pipeline/data/logs/csv_cleaning/` | `data_pipeline/data/logs/csv_cleaning/README.md` | Cleaning run manifests and redacted event logs |
| `docs/CSV_CLEANING_SPEC.md` | `docs/CSV_CLEANING_SPEC.md` | Teammate CSV profiling, cleaning, PDF cross-check, rejection and approval contract |

## Standard CLI commands

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev,pipeline]"
pytest -q
ruff check .
ruff format --check .
python -m uvicorn app.main:app --reload
```

Use commands only after the corresponding modules exist and have been inspected. For DB migrations, use `alembic upgrade head` only after read-only introspection, backup, Alembic baseline review and explicit approval of the migration. Never run the clean-schema bootstrap against the live DB.

## Phased execution

Follow `docs/IMPLEMENTATION_ROADMAP.md`. The grouped phases map to it: Phase 0 read-only backend/database reconnaissance; Phase 1 reproducible backend environment; Phase 2 resource intake, teammate CSV profiling/cleaning, master inventory and rights; Phase 3 PDF extraction/structuring; Phase 4 KCs/questions/import; Phase 5 embeddings/RAG/provider; Phase 6 student APIs/attempts/BKT/policy; Phase 7 teacher services/class expansion/evaluation/security/deployment. The numbered phases in `docs/IMPLEMENTATION_ROADMAP.md` (0–12) are authoritative for status and gates: roadmap Phase 5 is knowledge components and the prerequisite graph; embeddings and retrieval are roadmap Phase 7 and the LLM flow is roadmap Phase 8 (see `docs/PHASE_5_PROGRESS.md`). No frontend code is in scope. Do not skip phase gates.

## Coding and completion rules

- Read the target folder README in full before editing files there.
- Add/update schema → service → repository → route → tests → docs in dependency order.
- Keep business logic out of routes; use typed DTOs and typed domain errors.
- Add deterministic tests for BKT/graph/policy/scoring; mock external provider calls.
- Do not remove tests or loosen validation to make a phase pass.
- If actual backend code or schema differs from docs, stop before destructive changes and document the evidence plus a reversible migration/change proposal. Frontend files, if present, are read-only: do not edit them.
- Update `docs/PUBLIC_DECISIONS.md` (for decisions safe to publish), `docs/REQUIREMENTS_TRACEABILITY.md`, relevant module README and tests whenever a cross-layer decision changes. Owner rights attestations and other private decisions go in the owner's private records, never in published files.
- Report implemented vs proposed vs blocked accurately. A health endpoint or demo response is not proof of educational effectiveness.


## Teammate CSV and textbook resource hand-off

The user will place original textbook PDFs in `resources/textbook_pdfs/` and the teammate's original CSV export(s) in `resources/teammate_csv/incoming/`. Read `resources/README.md`, both child READMEs and `docs/CSV_CLEANING_SPEC.md` before touching these inputs. Profile CSVs before cleaning. Do not infer the CSV's schema from the filename. Keep source files unchanged; create immutable hash-addressed snapshots under `data_pipeline/data/raw/`; write profiles under `data_pipeline/data/interim/csv_profiles/`; write accepted/rejected outputs under `data_pipeline/data/processed/csv_cleaning/`; write run manifests/reports under `data_pipeline/data/logs/csv_cleaning/`. Preserve all original columns and row meaning unless a reviewed mapping explicitly says otherwise. Cross-check rows against PDFs only when internal processing permission is recorded as allowed; unknown/denied rights block PDF text extraction/OCR. PDF-derived facts must retain page-level evidence and unresolved conflicts must be quarantined for human review. Never overwrite `data_pipeline/curriculum.csv`; only map accepted rows into it after field mapping and owner review.

## Frontend is explicitly out of scope

Do not create or modify frontend code. A read-only Phase 0 inspection may note an existing frontend location for future integration. Backend completion requires exact API schemas, OpenAPI export, authentication/CORS documentation and `docs/FRONTEND_INTEGRATION.md`, not UI code.
