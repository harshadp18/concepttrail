# ConceptTrail technical reference

**Adaptive learning for CBSE Classes 6–10. Algorithms decide; AI writes.**

ConceptTrail finds the topic that is holding a student back, gives practice on exactly that topic,
and shows the teacher who needs help and why. It covers five subjects — English, Hindi,
Mathematics, Science and Social Science — for Classes 6 to 10.

Every decision that matters (scores, mastery, which topic comes next, which topics a class
struggles with, who may see what) is made by deterministic, tested code. A language model is used
only to *explain* — and only from stored course pages it can cite, or it says it cannot answer.

The project overview is the root [`README.md`](../README.md). This document is the detailed technical
reference: how ConceptTrail is built, how to run and test it, and the rules for changing it.

---

## Contents

1. [Status at a glance](#1-status-at-a-glance)
2. [What the product does](#2-what-the-product-does)
3. [Architecture](#3-architecture)
4. [Repository layout](#4-repository-layout)
5. [Technology stack](#5-technology-stack)
6. [Database](#6-database)
7. [Algorithms](#7-algorithms)
8. [AI tutor, retrieval and providers](#8-ai-tutor-retrieval-and-providers)
9. [HTTP API](#9-http-api)
10. [Frontend](#10-frontend)
11. [Content and data pipeline](#11-content-and-data-pipeline)
12. [Running it locally](#12-running-it-locally)
13. [Testing and evaluation](#13-testing-and-evaluation)
14. [Documentation map](#14-documentation-map)
15. [Security, privacy and rights](#15-security-privacy-and-rights)
16. [Engineering rules](#16-engineering-rules)
17. [Owner decisions still open](#17-owner-decisions-still-open)
18. [Glossary](#18-glossary)

---

## 1. Status at a glance

| Area | State |
|---|---|
| Backend (FastAPI) | Working end to end on synthetic demo data. 40 API paths. MVP readiness gate: 15/15 checks pass. |
| Frontend (React) | Integrated in `frontend/`, connected to the real API for every screen; checked at desktop, laptop, tablet and phone sizes. |
| Teacher Bell Ringer and heatmap | Implemented and tested. Saving Bell-Ringer *cycles* needs proposed migration 0004 (owner approval). |
| AI tutor ("Buddy") | Works with a local model (`qwen3.5:9b` through Ollama, `bge-m3` embeddings). Answers with citations or abstains. |
| Tests | Backend 1005 passed, 1 skipped; frontend 53 unit tests and 6 browser journeys pass. |
| Content | AI-drafted and AI-reviewed **demo** content (`demo_release`). No human teacher has approved it yet. |
| Production release gate | Fails by design until human-approved content, verified rights, calibrated BKT and released graph exist. |

**MVP readiness is not production readiness.** Passing the MVP gate shows the software works; it
does not show the content is correct, that learning improves, or that the BKT parameters are
calibrated on real learners. See [`docs/MVP_SCOPE.md`](MVP_SCOPE.md).

---

## 2. What the product does

### For students
- Sign in with a **platform-issued username and an individual 8-digit PIN** (no public sign-up).
- See subjects and chapters for their own class; each chapter is broken into small topics
  (knowledge components) with the student's own mastery estimate.
- **Practise**: single choice, multiple select, true/false and numeric questions, scored by the
  server against stored keys (short-answer items are never served). Every answer updates a
  per-topic mastery estimate (Bayesian Knowledge Tracing).
- **Next step**: a deterministic recommendation with its reason — strengthen a missing building
  block first, continue a topic in progress, or start something new.
- Progress by subject, chapter and topic; weak areas; a retry list of questions last answered
  wrongly; full answer history.
- **Buddy**: ask a doubt in your own words; get an explanation or a hint built only from cited
  course pages, or an honest "I couldn't find this".
- Alerts, profile and reading preferences (text size, spacing, contrast).

### For teachers
- Sign in with a **school email and password**; see only the classes the school assigned.
- Class overview, roster, per-learner progress, class weak areas.
- **Learning heatmap**: every learner against every topic, current estimate in each cell, with
  filters, tooltips and keyboard navigation. Missing data is shown as missing, never as zero.
- **Bell Ringer**: topics where several *different* learners struggle, each with a ready
  five-minute warm-up (board question, timed steps, bridge question, answer key, the wrong answer
  this class picks most often). Each topic gets its own cycle: planned → run in class → completed,
  with a follow-up showing who has moved.
- Question review: approve, reject or request revision of AI-drafted questions (the AI check is
  shown separately and never counts as a teacher review).
- Support plans (interventions) and notifications.

### What it deliberately does not do
- No LLM decides a score, a mastery value, a prerequisite edge, a role, an access right, a
  teacher priority or a next step.
- No LLM training or fine-tuning in the first release.
- No unrestricted self-registration; accounts are provisioned by the school.
- No student names, phone numbers, roll numbers, passwords or tokens are sent to any model.

---

## 3. Architecture

A **modular monolith**: one FastAPI application, one PostgreSQL database, one React frontend.

```
 Browser (React, Vite)                       Teachers / students
        │  HTTPS JSON, bearer token
        ▼
 FastAPI  /api/v1  ── auth, role and class checks on every request
   ├─ routes (app/api/v1)          thin: validate, call a service, shape the response
   ├─ services (app/services)      all business logic
   │    ├─ scoring + attempts ──► BKT update (once per attempt, idempotent)
   │    ├─ adaptive policy ─────► prerequisite graph (NetworkX over relational edges)
   │    ├─ progress, heatmap, Bell Ringer (unique-learner rules)
   │    └─ tutor: retrieval (pgvector) ► local LLM (Ollama) ► citation validation
   ├─ repositories / SQLAlchemy models (app/db)
   └─ core: settings, security, rate limits, HTTP hardening (app/core)
        │
        ▼
 PostgreSQL 18 + pgvector (schema `concepttrail`, 26 tables)     Redis (shared rate limits)
        ▲
 Offline: data_pipeline/ (inventory, rights, PDF extraction, KCs, questions, import, index)
```

Key flows:

- **Answer** → `POST /attempts` → load the canonical question version → deterministic scoring →
  immutable attempt row → BKT update for the question's knowledge component (only single-KC
  questions are evidence) → response with the new estimate. Retries with the same idempotency key
  replay the stored result.
- **Recommendation** → released (or demo) prerequisite graph + the learner's estimates → blocked
  topics' unmet prerequisites first, then topics in progress, then new topics; deterministic ties.
- **Doubt** → authorise the learner's scope → retrieve stored chunks for the class → the local
  model writes a structured answer from that evidence only → every citation is checked against
  the retrieved pages → grounded answer, or an explicit abstention.
- **Bell Ringer** → class learners × class topics → unique learners below the weak cut-off → topics
  that meet the criteria → reverse search of the prerequisite graph for a shared root gap →
  fixed-template warm-up from stored questions.

---

## 4. Repository layout

```
app/                      FastAPI application
  api/v1/                 HTTP routes (one module per area; see section 9)
  core/                   settings (typed, env-driven), security, roles, rate limiting, HTTP hardening
  db/                     SQLAlchemy models (26 tables), session, schema snapshot, migrations
    migrations/           Alembic; only revision 0001 (the 26-table baseline) is active
  db/proposed_models.py   ORM models for PROPOSED tables (0002–0004), on a separate metadata
  schemas/                Pydantic request/response models
  services/               business logic: BKT, scoring, adaptive policy, graph, progress,
                          Bell Ringer + heatmap, retrieval, LLM, tutor, notifications, rights
db/
  schema/001_initial_schema.sql   clean-schema bootstrap (never run against a live database)
  verify_schema.sql               read-only verification
  proposals/              additive migrations awaiting owner approval (0002, 0003, 0004)
data_pipeline/            offline content pipeline
  curriculum.csv          the ONE master inventory (29 columns)
  stages/                 profile/clean/validate CSV; classify, extract, OCR, clean, structure PDFs
  kc_graph/               knowledge components and prerequisite edges: drafting, review log,
                          lifecycle, release snapshots, import plans
  demo_content/           generation and import of AI-drafted demo content (demo_release)
  content_review/         loader and reversible patch for the AI content review (records private)
  data/                   raw / interim / processed / overrides / logs / final — private, Git-ignored
  prompts/                versioned generation prompts
resources/                drop zones: textbook_pdfs/, teammate_csv/incoming/ (originals never edited)
evaluation/               metric catalogue, benchmark data, simulators, report runner
training/                 optional offline BKT fitting only (no LLM training in v1)
frontend/                 React + TypeScript app (Vite)
scripts/                  operational commands (demo data, gates, backups, OpenAPI export, ...)
deploy/                   Dockerfile, compose files, pinned runtime requirements
docs/                     specifications and reports (section 14)
tests/                    unit/ and integration/ (pytest)
```

Folder conventions:
- **Routes stay thin** (route → service → repository). No business logic in routes.
- **`data_pipeline/data/`** holds immutable raw snapshots, profiles, page-aware extraction JSON,
  cleaned/structured JSON, human overrides, logs and derived CSVs, each in its own folder. Nothing
  overwrites an input or a raw artifact. These folders are private and kept in Git only as empty
  placeholders (`.gitkeep`).
- **`resources/textbook_pdfs/`** and **`resources/teammate_csv/incoming/`** are where the owner
  drops source files. Originals are preserved byte-for-byte; the pipeline snapshots them by SHA-256.

---

## 5. Technology stack

| Layer | Choice |
|---|---|
| API | Python 3.12, FastAPI, Pydantic v2, Uvicorn |
| Database | PostgreSQL 18 with pgvector 0.8.7, SQLAlchemy 2.x, Alembic |
| Rate limits | Redis (shared across processes; required in production) |
| Graph | NetworkX in process, edges stored relationally |
| PDF and text | PyMuPDF, optional Tesseract OCR, Devanagari repair |
| Local AI | Ollama: chat `qwen3.5:9b`, embeddings `bge-m3` |
| Frontend | Vite 5, React 18, TypeScript (strict), React Router 6, TanStack Query 5, Tailwind CSS 3, Framer Motion 11, Radix primitives, lucide icons |
| Quality | pytest, Ruff (lint + format), Vitest + Testing Library, Playwright |
| Packaging | `pyproject.toml` (`pip install -e ".[dev,pipeline]"`), `deploy/requirements.lock`, Docker |

---

## 6. Database

PostgreSQL schema **`concepttrail`**, **26 tables**, Alembic revision **`0001`**:

`attempts`, `bkt_config_version`, `class_enrollments`, `classroom`, `content_unit`,
`content_unit_kcs`, `curriculum_item`, `curriculum_version`, `embedding_chunk`, `ingestion_job`,
`ingestion_job_documents`, `kc_curriculum_map`, `kc_edge`, `knowledge_component`, `learners`,
`note`, `question_kcs`, `question_options`, `questions`, `role`, `source_document`,
`student_kc_state`, `subject`, `teacher_class_assignments`, `user_roles`, `users`.

Contract points (full column-level detail in [`docs/DATABASE_SCHEMA.md`](DATABASE_SCHEMA.md)):
- `subject_id` is `VARCHAR`; converting it would need a reviewed migration across every FK.
- `embedding_chunk` keeps exactly nine columns (`chunk_id`, `content_unit_id`, `chunk_order`,
  `chunk_text`, `token_count`, `embedding_model_id`, `embedding`, `index_generation`,
  `created_at`). The `VECTOR` column stays dimension-unbounded; no dimension-specific ANN index
  until an embedding model is approved.
- The baseline has no table for interventions, notifications, tutor history or Bell-Ringer
  cycles; nothing is persisted by overloading unrelated tables.

### Proposed additive migrations (not applied to the persistent database)

| Proposal | Adds | Feature flag | Used by |
|---|---|---|---|
| `db/proposals/0002_teacher_intervention.py` | `teacher_intervention` | `INTERVENTIONS_ENABLED` | support plans |
| `db/proposals/0003_notifications_and_doubt_history.py` | `notification`, `doubt_conversation`, `doubt_message` | `NOTIFICATIONS_ENABLED`, `DOUBT_HISTORY_ENABLED` | alerts, tutor history |
| `db/proposals/0004_bell_ringer_cycle.py` | `bell_ringer_cycle` (one open cycle per class and topic) | `BELL_RINGER_ENABLED` | Bell-Ringer cycles |

They live outside `app/db/migrations/versions`, so `alembic upgrade head` never applies them.
They are tested only on disposable databases (upgrade, constraints, downgrade). Until approved,
their routes answer `503 feature_not_enabled`, and the frontend shows "not available yet".
To adopt after approval and a verified backup (`python -m scripts.db_backup`): copy them into
`app/db/migrations/versions/`, add the models from `app/db/proposed_models.py` to
`app/db/models.py`, run `alembic upgrade 0004`, then enable the flags.

Migration rules: read-only introspection first; never drop, truncate, recreate or destructively
migrate an existing database; never run the clean-schema bootstrap against a live database;
additive changes need explicit owner approval and a backup.

---

## 7. Algorithms

### Scoring
Deterministic, per item type: `single_choice` / `true_false` (one option key), `multiple_select`
(exact set, all-or-nothing), `numeric` (value with the stored tolerance). Keys never leave the
server for students. Option order is shuffled deterministically per learner and question.

### Bayesian Knowledge Tracing (BKT)
Runtime configuration `bkt-provisional-v1`: four parameters per topic (initial knowledge, learn,
guess, slip). The estimate updates once per attempt (idempotent), only from single-KC questions;
an answer given after a strong hint (tier ≥ 2) counts as incorrect evidence. The parameters are
**provisional and uncalibrated**; synthetic calibration studies live in `evaluation/` and never
change runtime values. Real calibration needs at least 2,000 events from at least 30 consenting
learners.

### Thresholds (provisional)
| Threshold | Value | Meaning |
|---|---|---|
| Mastered | ≥ 0.95 | topic counted as mastered |
| Prerequisite ready | ≥ 0.70 | a prerequisite no longer blocks its dependents |
| Weak | < 0.50 with ≥ 2 scored answers | reported as needing practice |

Quiz percentages and BKT probabilities are separate quantities and are never mixed.

### Prerequisite graph
Edges are rows in `kc_edge`; NetworkX builds the graph in process. Validation rejects cycles,
unknown or retired topics and duplicate keys. Only a released, verified snapshot is used in
production; demo mode may use the AI-proposed demo graph, and every response says which.

### Adaptive policy (`adaptive-policy-v1`)
Candidates are released topics in the learner's scope (plus earlier-class prerequisites reached
through the graph). A topic is blocked while a direct prerequisite is below "ready" or has no
evidence; unmet prerequisites become remediation candidates. Order: remediation first, then topics
in progress (lowest estimate first), then new topics; ties by graph layer, then how many topics it
unblocks, then ID. The chosen question is an unattempted approved one whose difficulty is closest
to the learner's estimate.

### Bell Ringer (`app/services/bell_ringer.py`)
For each topic of the class level, over the class's actively enrolled learners (the denominator):
learners with an estimate, **unique** learners below the weak cut-off (five wrong answers by one
learner count once), learners who never attempted it, and — inside a stated window — failed
attempts and the unique learners behind them. A topic is flagged only when all three criteria
hold (settings, provisional): `BELL_RINGER_MIN_COVERAGE` (0.3), `BELL_RINGER_MIN_AFFECTED_LEARNERS`
(2), `BELL_RINGER_MIN_AFFECTED_SHARE` (0.4); window `BELL_RINGER_WINDOW_DAYS` (14). The response
says which criteria a topic missed. The **root gap** is the prerequisite on which most affected
learners are also weak (at least half of them; ties: the earliest). The **warm-up card** follows a
fixed template — 1 minute alone, 3 minutes in pairs, 1 minute class share — with a board question
on the root topic, a bridge question on the flagged topic, the answer key, and "watch for" (the
class's most common wrong option, else the question's stored misconception note). No model is
involved. A cycle stores a baseline; its follow-up re-checks the same learners with the same
cut-off. Repeated "open cycle" requests return the open cycle instead of creating another.

### Heatmap
One request per view: learners (rows) × topics (columns), each cell with the current estimate or
`null`, evidence count, attempts, correct answers, last attempt and a band (`mastered`,
`developing`, `needs_practice`, `insufficient_evidence`, `no_data`). The window limits attempt
counts only; estimates are always current.

---

## 8. AI tutor, retrieval and providers

| Item | Decision |
|---|---|
| Chat model | **Qwen 3.5 9B** (`qwen3.5:9b`) through local Ollama (`http://localhost:11434`), context 4096, thinking off, JSON Schema structured output |
| Embeddings | `bge-m3` locally (index generation `ig-dev-1-bge-m3`); the production embedding model and dimension are still **undecided** |
| Cloud fallback | GPT-OSS 120B (`openai/gpt-oss-120b`) through Groq is a candidate only. `LLM_FALLBACK_ENABLED=false`; no Groq (cloud) adapter exists and `build_llm` refuses any configuration that would enable one |
| Not selected | Gemini, DeepSeek |

The local Ollama adapter is `app/services/llm.py`: business logic calls `LocalLLM`, never HTTP;
the reply is validated against a Pydantic model; prompts and replies are never logged. Fallback, if
ever approved, may only follow transient errors — never safety, rights, validation or
insufficient-evidence outcomes. Groq processing of textbook content or student data is **not
authorised** until the owner records the scope and the rights and retention conditions.

Tutor rules: retrieval is filtered to the learner's class and authorised content; the model sees
only the question and the retrieved evidence; every citation must point to a retrieved page;
outcomes are `grounded` or `abstained` (`insufficient_evidence`, `not_authorized`,
`model_unavailable`, `model_timeout`, `invalid_model_output`). Hints and explanations never mark
answers or change mastery. Requests are rate-limited per learner (`DOUBT_REQUESTS_PER_HOUR`).

---

## 9. HTTP API

Base path `/api/v1` (plus `/health`, `/ready`). The generated contract is
[`docs/openapi/openapi-v1.json`](openapi/openapi-v1.json) (40 paths; regenerate with
`python -m scripts.export_openapi`; a test fails on drift). Rules and examples:
[`docs/API_CONTRACTS.md`](API_CONTRACTS.md), [`docs/FRONTEND_INTEGRATION.md`](FRONTEND_INTEGRATION.md).

| Area | Routes |
|---|---|
| Auth | `POST /auth/login`, `GET /me` |
| Catalog and curriculum | `/catalog/classes`, `/curriculum`, `/curriculum/items/{id}`, `/curriculum/items/{id}/topics`, `/topics/{kc}`, `/topics/{kc}/prerequisites`, `/topics/{kc}/questions` |
| Practice | `POST /attempts` |
| Student progress | `/student/progress`, `/student/progress/chapters`, `/student/activity`, `/student/weak-areas`, `/student/review`, `/student/recommendation` |
| Tutor | `POST /doubts`, `/student/doubts/conversations[/{id}[/archive]]` |
| Teacher | `/teacher/classes`, `/teacher/classes/{id}/dashboard`, `/learners`, `/learners/{learner}/progress`, `/weak-areas`, `/heatmap`, `/bell-ringer/topics`, `/bell-ringer/cycles[/{cycle}[/status]]`, `/interventions[/{id}/status]` |
| Review | `/teacher/review/questions`, `POST /teacher/review/questions/{id}` |
| Notifications | `/notifications`, `POST /notifications/{id}/read`, `POST /notifications/read-all` |
| Operations | `/jobs/{id}`, `/health`, `/ready` |

Conventions: errors are `{"error": {"code", "message", "request_id"}}`; learner and user identity
always comes from the token, never from a request body; out-of-scope content is `404`, another
teacher's class is `403 forbidden_classroom`; list routes take `limit`/`offset` and return a total
`count`; `null` means "no evidence yet".

---

## 10. Frontend

Location `frontend/`. It talks only to the HTTP API — never to PostgreSQL, Redis or Ollama.

```
src/api/http.ts        fetch wrapper: base URL, bearer token, error envelope → ApiError, 401 handling
src/api/types.ts       response types
src/api/endpoints.ts   one function per backend route (the only place that builds URLs)
src/api/hooks.ts       React Query hooks and cache invalidation after writes
src/context/           AuthContext (login, /me, expiry, logout), TeacherClassContext
src/components/        AppShell layout, UI primitives and state views, student and teacher components
src/pages/             public, auth, student, teacher, shared (alerts, profile)
src/__tests__/         unit tests, including the OpenAPI contract test
e2e/flows.spec.ts      Playwright journeys against the running stack
scripts/ui-audit.mjs   screenshots of every page at four viewports
```

Behaviour:
- **Auth**: student username + 8-digit PIN; teacher school email + password. The token and its
  expiry sit in `sessionStorage`; reload restores the session through `/me`; any `401` ends it.
  Signing in on the wrong role's tab is refused with a clear message.
- **States**: loading skeletons; empty states that explain why; `null` shown as "Not started" or
  "—"; `503 feature_not_enabled` shown as "not available yet"; `403`, `404`, network, timeout and
  `429` (with `Retry-After`) each handled; success shown only after the server confirms.
- **Design system**: tokens in `tailwind.config.js` (brand `#287A9F`, text `#444444`, surfaces
  `#F0F2F3`, soft subject tints), shared classes in `src/index.css`. Mastery bands use a palette
  checked for colour-vision deficiency and contrast and are always paired with text.
- **Brand**: the official logo is used only through `src/components/brand/BrandLogo.tsx` (trimmed
  from the supplied artwork, never redrawn). Illustrations are original SVGs in one style.
- **Motion**: Framer Motion only, transform/opacity, short; `prefers-reduced-motion` respected.
- **Accessibility**: zoom allowed, skip link, focus rings, labelled fields, radio/checkbox roles for
  answers, `role="meter"` mastery bars with text, a keyboard-operable heatmap grid.
- **Demo labelling**: AI-drafted content and synthetic learners are labelled by default. Setting
  `VITE_SHOW_DEMO_NOTICES=false` (only in a Git-ignored `frontend/.env.development.local`) hides the
  labels for a recorded walkthrough; nothing else changes.

Details: [`docs/FRONTEND_INTEGRATION.md`](FRONTEND_INTEGRATION.md) and the before/after audit
[`docs/FRONTEND_UI_AUDIT.md`](FRONTEND_UI_AUDIT.md).

---

## 11. Content and data pipeline

### One master inventory
`data_pipeline/curriculum.csv` is the only master inventory. Its 29-column header is fixed, in this
order:

`inventory_id, class_level, board, academic_session, subject_id, course_or_language, item_type,
chapter_or_unit_code, chapter_title, topic_title, learning_objective, resource_title, source_id,
source_url, publication_or_revision, rights_status, permitted_processing, permitted_indexing,
permitted_training, permitted_display, permission_reference, acquired_at, sha256,
extraction_status, validation_status, review_status, index_status, last_verified_at, notes`

No parallel masters (`resources.csv`, `sources.yaml`). Derived outputs: `kc_components.csv`,
`prerequisites.csv`, `questions.csv` (and the proposed `notes.csv`), generated into
`data_pipeline/data/final/`.

### Stages
1. **Intake** — originals in `resources/…`; immutable SHA-256 snapshots under `data_pipeline/data/raw/`.
2. **Teammate CSV cleaning** — profile first (`data/interim/csv_profiles/`); only documented,
   deterministic transformations; original headers and order preserved; accepted and rejected rows
   written separately (`data/processed/csv_cleaning/`); a quality report and input/output hash
   manifest (`data/logs/csv_cleaning/`). Missing data is never fabricated and ambiguous values are
   never auto-reconciled from PDFs; corrections come only from human overrides. Spec:
   [`docs/CSV_CLEANING_SPEC.md`](CSV_CLEANING_SPEC.md).
3. **PDF extraction** — page classification, text extraction, optional OCR, Devanagari repair,
   cleaning and structuring into page-aware JSON, with page-level evidence kept for every fact.
4. **Knowledge components and prerequisite edges** — drafted, reviewed through an append-only
   review log, released as verified snapshots (`data_pipeline/kc_graph/`).
5. **Questions and notes** — generated and validated; demo content is imported as `demo_release`.
6. **Indexing** — chunking and embeddings into `embedding_chunk` for retrieval.

### Rights gate
Rights are **purpose-specific**: internal processing, external-model processing, indexing/RAG,
training, display and redistribution are separate decisions. Unknown permission blocks the
operation (`data_pipeline/authorization.py` fails closed). Publicly downloadable does not mean any
of these rights exist. Uncertain OCR, equations, maps and diagrams, language writing, subjective
responses, knowledge components and prerequisite edges go to human review.

### Content status today
The question bank and graph are AI-drafted demo content. An AI review (`data_pipeline/content_review/`)
repaired, withdrew or escalated items; it is labelled as an AI review, never as a human one. Its
records are private (they contain textbook-derived text) and the patch has not been applied to the
persistent database. The release gate rejects AI review as approval.

---

## 12. Running it locally

Full, verified commands and troubleshooting: [`docs/LOCAL_DEVELOPMENT.md`](LOCAL_DEVELOPMENT.md).

| Piece | URL |
|---|---|
| Frontend | http://localhost:5173 |
| Demo backend (disposable `ct_demo` database) | http://localhost:8020, API `http://localhost:8020/api/v1`, docs `/docs` |
| Persistent development stack (not used by the demo) | http://127.0.0.1:8010 |

```sh
# one-time
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev,pipeline]"
cd frontend && npm ci && npx playwright install chromium && cd ..
# .local/demo.env must hold DEMO_DB=...ct_demo (see docs/LOCAL_DEVELOPMENT.md)

# start
docker start ct-disposable-migrations ct-disposable-redis
pgrep -x ollama >/dev/null || ollama serve &
./scripts/run_demo_backend.sh          # refuses any database not named ct_demo*
cd frontend && npm run dev

# stop
kill $(lsof -tiTCP:5173 -sTCP:LISTEN) $(lsof -tiTCP:8020 -sTCP:LISTEN)
docker stop ct-disposable-migrations ct-disposable-redis
```

### Demo data
`scripts/demo_data.py` loads a fictional population into a disposable database whose name starts
with `ct_demo` (it refuses anything else, including the configured database): two teachers, one
class per level 6–10, ten learners per class with strong, average, struggling and inactive
profiles. Attempts are submitted through the real scoring and BKT path, so progress is derived
exactly as for real learners. It is idempotent. Sign-in details go to the Git-ignored
`.local/demo_credentials.json`.

`scripts/demo_presentation.py apply|revert` gives that disposable database realistic fictional
names (for recording a walkthrough) and restores the originals exactly. Revert it before running
the demo loader, the MVP gate or the end-to-end tests.

### Useful commands
| Command | Purpose |
|---|---|
| `python -m scripts.mvp_gate --base-url … --database-url "$DEMO_DB" [--with-llm]` | 15 end-to-end MVP checks |
| `python -m scripts.release_gate` | strict production gate (fails today by design) |
| `python -m scripts.export_openapi` | regenerate `docs/openapi/openapi-v1.json` |
| `python -m scripts.db_backup` | verified backup of the persistent database |
| `python -m scripts.seed_dev_auth verify` | read-only check of development accounts |
| `curl localhost:8020/health` / `/ready` | liveness / readiness (database, limiter, model) |

Never run `docker compose down -v`: it deletes the persistent database volume.

---

## 13. Testing and evaluation

```sh
# backend (Redis and migration tests use DISPOSABLE services)
export CONCEPTTRAIL_TEST_REDIS_URL=redis://127.0.0.1:6380/0
export CONCEPTTRAIL_MIGRATION_TEST_ADMIN_URL=postgresql+psycopg://<admin>@127.0.0.1:5435/postgres
pytest -q && ruff check . && ruff format --check .

# frontend
cd frontend && npm test && npm run build && npx playwright test
```

- Live-database tests run inside a transaction that is always rolled back; migration tests create
  and drop their own throwaway databases; provider calls are mocked by default.
- Deterministic tests cover BKT, graph, policy, scoring, Bell Ringer counting and authorisation.
- The frontend contract test fails if the app calls any path not in the OpenAPI file.
- Tests are never removed or loosened to make a phase pass.

### Evaluation (`evaluation/`)
Three separate things: **instruments** (`stats.py`, `bank_metrics.py`, `citations.py`,
`review.py`, `run.py`, `catalog.py`), **benchmark data** (`evaluation/benchmarks/v1/`, sealed by
SHA-256 in `manifest.json`, written by people or derived from rules, never from model output), and
**reports** (`.local/evaluation/reports/`, Git-ignored).

Software correctness (does the code match its spec?) and quality (is the content right, clear and
useful?) are reported separately. Only independent human review or real learner outcomes can
establish quality; automated metrics are labelled `automated_property` or `proxy`, never accuracy;
AI-generated labels never score anything; cells with fewer than 10 items are `insufficient_data`.

Benchmark cases carry `case_id`, `dataset_version`, `class_level`, `subject_id`, `language`,
`curriculum_item_id`, `label_provenance`, `reviewers` (pseudonymous) and `split` (`dev` or
`locked_test`; the locked split is never used for tuning). Today: 38 scoring cases, 12 adaptive
cases and 4 exact BKT vectors exist; retrieval, explanation, question-review, BKT-sequence and
learning-outcome datasets have schemas but **no data yet**.

```sh
python -m evaluation.full [--quick] [--with-llm]      # everything, one index report
python -m evaluation.run [--live-retrieval]           # core report (deterministic fingerprint)
python -m evaluation.bkt_synthetic [--quick]          # synthetic BKT study
python -m evaluation.policy_simulation [--quick]      # synthetic adaptive-policy comparison
python -m evaluation.retrieval_regression             # synthetic retrieval regression
```

#### Metric catalogue (`evaluation/catalog.py`)

| Metric | What it is | Kind | Automation |
|---|---|---|---|
| `scoring.conformance` | Evaluator agrees with the scoring specification | software_correctness | automated |
| `scoring.type_coverage` | Question types covered by constructed cases | software_correctness | automated |
| `questions.structure` | Servable: deterministic key, option and type rules hold | automated_property | automated |
| `questions.key_position_bias` | Correct-answer position distribution | automated_property | automated |
| `questions.longest_correct_cue` | Correct option is also the longest | proxy | automated |
| `questions.passage_dependence` | Stem refers to text the student cannot see | proxy | automated |
| `questions.near_duplicates` | Near-duplicate stems within the bank | proxy | automated |
| `questions.option_explanations` | Options with an explanation | automated_property | automated |
| `questions.source_page_resolvable` | Cited page exists as a stored content unit | automated_property | automated |
| `questions.kc_coverage` | Questions per knowledge component | automated_property | automated |
| `questions.review_status` | Questions with a recorded human review | automated_property | automated |
| `questions.key_correct` | Stored answer key is correct (blind reviewer agrees) | human_quality | human_required |
| `questions.unambiguous` | Question has one defensible answer | human_quality | human_required |
| `questions.kc_alignment` | Question assesses its knowledge component | human_quality | human_required |
| `questions.age_language_fit` | Suitable for the class and language | human_quality | human_required |
| `questions.distractor_quality` | Distractors plausible and instructive | human_quality | human_required |
| `questions.copied_wording` | Copies textbook wording | proxy | automated |
| `retrieval.index_integrity` | Chunks resolve to units, sources, pages, hashes | automated_property | automated |
| `retrieval.filter_leakage` | Retrieval returns nothing outside the learner scope | software_correctness | automated |
| `retrieval.recall_mrr_ai_labels` | Recall@k / MRR on AI-derived relevance | proxy | automated |
| `retrieval.recall_mrr` | Recall@k / MRR on human-judged relevance | human_quality | human_required |
| `explanation.citation_resolves` | Every cited label maps to retrieved evidence | software_correctness | automated |
| `explanation.lexical_support` | Explanation sentences lexically overlap cited text | proxy | automated |
| `explanation.supported` | Claims are supported by the cited page | human_quality | human_required |
| `explanation.correct` | Explanation is educationally correct and clear | human_quality | human_required |
| `explanation.abstention` | Abstains when evidence is insufficient | human_quality | human_required |
| `bkt.known_answers` | Update equations match hand-computed vectors | software_correctness | automated |
| `bkt.fit_pipeline` | Fitting recovers known parameters on synthetic learners | software_correctness | automated |
| `bkt.real_prediction` | Held-out log loss / Brier / calibration on real learners | outcome | blocked |
| `bkt.synthetic_recovery` | Parameter recovery, held-out prediction, robustness on synthetic learners | synthetic | automated |
| `adaptive.synthetic_policy_comparison` | Policy vs baselines on simulated learners, adverse conditions | synthetic | automated |
| `content.ai_review` | Whole-bank AI review: defects repaired, withdrawn, escalated | ai_review | automated |
| `retrieval.synthetic_regression` | Chapter-hit regression on AI-derived queries; abstention probes | synthetic | automated |
| `explanation.synthetic_regression` | Citation validity, abstention, arithmetic, language on AI-authored prompts | synthetic | automated |
| `adaptive.policy_conformance` | Recommendation matches the written policy | software_correctness | automated |
| `adaptive.simulation` | Policy behaviour on simulated learners | proxy | automated |
| `adaptive.learning_gain` | Recommendations improve learning | outcome | blocked |

`human_required` metrics need independent reviewers; `blocked` metrics cannot be measured until
the data or decision they depend on exists. Reports print them as `not_measured` or `blocked`.

---

## 14. Documentation map

| Document | Contents |
|---|---|
| [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) | architecture detail |
| [`docs/API_CONTRACTS.md`](API_CONTRACTS.md) | route table, request/response rules, error codes |
| [`docs/FRONTEND_INTEGRATION.md`](FRONTEND_INTEGRATION.md) | how the frontend uses the API; Bell Ringer and heatmap contracts |
| [`docs/FRONTEND_UI_AUDIT.md`](FRONTEND_UI_AUDIT.md) | frontend before/after audit, assets, motion, accessibility |
| [`docs/LOCAL_DEVELOPMENT.md`](LOCAL_DEVELOPMENT.md) | start, stop, test, troubleshoot |
| [`docs/DATABASE_SCHEMA.md`](DATABASE_SCHEMA.md) | 26-table contract |
| [`docs/DATA_PIPELINE.md`](DATA_PIPELINE.md), [`docs/CSV_CLEANING_SPEC.md`](CSV_CLEANING_SPEC.md) | pipeline and CSV cleaning |
| [`docs/AI_AND_PROVIDER_STRATEGY.md`](AI_AND_PROVIDER_STRATEGY.md), [`docs/PROVIDER_READINESS.md`](PROVIDER_READINESS.md) | model providers |
| [`docs/SECURITY_PRIVACY.md`](SECURITY_PRIVACY.md) | security and privacy controls |
| [`docs/PUBLICATION_AND_REPRODUCIBILITY.md`](PUBLICATION_AND_REPRODUCIBILITY.md) | what is public, what stays private |
| [`docs/PUBLIC_DECISIONS.md`](PUBLIC_DECISIONS.md) | public decision register |
| [`docs/REQUIREMENTS_TRACEABILITY.md`](REQUIREMENTS_TRACEABILITY.md) | requirement → code → test |
| [`docs/IMPLEMENTATION_ROADMAP.md`](IMPLEMENTATION_ROADMAP.md) | phases 0–12 and gates |
| [`docs/MVP_SCOPE.md`](MVP_SCOPE.md), [`docs/BACKEND_MVP_REPORT.md`](BACKEND_MVP_REPORT.md), [`docs/COMPLETION_AUDIT.md`](COMPLETION_AUDIT.md) | readiness and evidence |
| [`docs/PHASE_5_PROGRESS.md`](PHASE_5_PROGRESS.md) and the other `PHASE_5_*` files | knowledge-component and graph phase |
| [`docs/RISKS_AND_DECISIONS.md`](RISKS_AND_DECISIONS.md), [`docs/TROUBLESHOOTING.md`](TROUBLESHOOTING.md), [`docs/CLAUDE_CODE_WORKFLOW.md`](CLAUDE_CODE_WORKFLOW.md) | risks, troubleshooting, AI-assisted workflow |

---

## 15. Security, privacy and rights

- Passwords and PINs are hashed with **Argon2id**; login is throttled per account and per address
  (shared Redis limits; production refuses to start without Redis).
- Server-side role and class checks on every request; explicit CORS origins (never `*`; https only
  in production); trusted hosts; security headers; request-body limit; sanitised error envelope;
  API docs disabled in production; parameterised queries only.
- Bearer tokens (30 minutes, no refresh); the frontend keeps them in `sessionStorage`, never in URLs.
- Data minimisation for minors: no names, phone numbers, roll numbers, passwords, tokens or
  unnecessary history to any model; logs carry request IDs, not content. Teacher notes and tutor
  history are never sent to a provider. Retention for tutor history is an owner decision.
- Rights are purpose-specific and fail closed (section 11).
- **Public repository boundary**: source code, tests, synthetic fixtures and specifications are
  public. Private: `.env`, `.local/`, `data_pipeline/data/**` (except placeholders), textbook PDFs,
  teammate CSVs, owner attestations and decision records, and the content-review records. Never
  force-add ignored files. See [`docs/PUBLICATION_AND_REPRODUCIBILITY.md`](PUBLICATION_AND_REPRODUCIBILITY.md).

---

## 16. Engineering rules

These replace the per-folder notes and `CLAUDE.md` files that used to live next to the code.

1. **Read before changing.** Inspect the real code and the live schema (read-only) before editing;
   do not assume the docs prove implementation status.
2. **Preserve the database.** Never drop, reset or truncate it, replace its volume, run destructive
   seeds, or apply a migration without explicit owner approval and a verified backup. Test
   migrations on disposable databases only.
3. **Order of work**: schema → service → repository → route → tests → docs. Routes stay thin;
   typed DTOs and typed domain errors; identity from authentication, never from a request body;
   attempt + mastery changes in one PostgreSQL transaction.
4. **Algorithms decide.** No LLM in repositories, model hooks, scoring, BKT, graph, policy, roles or
   access. Deterministic tests for BKT, graph, policy and scoring; mock providers in tests; no paid
   or external model calls in default test runs.
5. **Multi-KC questions** need KC-specific evidence; one overall correct/incorrect is never applied
   to every mapped topic.
6. **Content pipeline**: one master inventory; originals byte-for-byte; raw snapshots immutable;
   accepted and rejected rows separate; never fabricate missing data; human review for uncertain
   items; unknown rights block the operation.
7. **Frontend**: all API calls in `src/api/endpoints.ts`; never show `null` as 0; treat
   `feature_not_enabled` as "not available yet"; use the design tokens and `BrandLogo`; keep motion
   short and reduced-motion-safe.
8. **Never weaken** security controls, tests or validation to make something pass. Report
   implemented vs proposed vs blocked accurately; a health check or demo is not proof of learning.
9. **Keep docs true.** When a cross-layer decision changes, update this reference and the README,
   `docs/PUBLIC_DECISIONS.md`, `docs/REQUIREMENTS_TRACEABILITY.md`, the OpenAPI export and tests.
   Private decisions and rights attestations stay in the owner's private records.
10. **Git hygiene.** Do not commit `.env`, `.local/`, private data or credentials.

---

## 17. Owner decisions still open

- Approve and apply proposed migrations 0002, 0003 and 0004 (with a backup), then enable their flags.
- Confirm the Bell-Ringer thresholds for real classes, and a retention policy and school notice for
  tutor history.
- Decide whether to apply the AI content-review patch to the persistent database.
- Human (teacher / subject-expert, including Hindi) review and approval of content.
- Choose the production embedding model and vector dimension after a retrieval evaluation.
- Real-learner data (with consent) for BKT calibration; outcome studies before any efficacy claim.
- Display, indexing and redistribution rights for production sources.
- Teammate sign-off on owner-added routes; deployment (out of scope so far).

---

## 18. Glossary

| Term | Meaning |
|---|---|
| KC (knowledge component) | One small, teachable topic; the unit of mastery |
| BKT | Bayesian Knowledge Tracing: a probabilistic estimate of whether a learner knows a KC |
| Mastery estimate | BKT probability (0–1); provisional, not a grade |
| Prerequisite edge | "A must come before B" between two KCs |
| `demo_release` | AI-drafted content served only in demo mode; not human-approved |
| Released snapshot | A verified, human-approved graph version used in production |
| Bell Ringer | A five-minute class warm-up targeting a gap that several learners share |
| Cycle | One topic's Bell Ringer from planning to follow-up |
| Grounded / abstained | Tutor answered from cited evidence / declined for a stated reason |
| `ct_demo` | The disposable demo database; never the persistent one |
| MVP gate / release gate | "Does it work end to end?" / "May real students rely on it?" |
