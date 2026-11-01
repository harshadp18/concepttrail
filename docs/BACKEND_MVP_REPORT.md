# Backend MVP readiness report (2026-11-01)

Scope: the FastAPI backend, database layer, algorithms, tutor and teacher services, on synthetic
demo data. MVP readiness and production readiness are separate (`docs/MVP_SCOPE.md`); this report
covers the first. Earlier phase evidence is in `docs/COMPLETION_AUDIT.md`.

## 1. What existed before this work

18 routes (auth, curriculum, chapter topics, questions, attempts, progress, recommendation, doubts,
teacher dashboard, question review, interventions, jobs, health), deterministic scoring for four
question types, BKT with idempotent mastery updates, prerequisite graph with cycle detection,
adaptive recommendation, RAG with citation validation, Redis rate limiting, 972 passing tests,
synthetic BKT/policy/retrieval/explanation evaluations, and the strict production release gate.

## 2. What was implemented

| Area | Added | Evidence |
|---|---|---|
| Catalog and navigation | `GET /catalog/classes` (all class-subject pairs with `published` / `demo_release` / `not_available`), `GET /curriculum/items/{id}`, `GET /topics/{kc}/prerequisites` (direct + transitive, per-learner readiness, edge provenance) | `tests/unit/test_progress_api_live.py` |
| Progress engine | `app/services/progress_summary.py`: chapter and subject roll-ups, weak areas, activity, retry list, class weak areas, all read from `student_kc_state` and `attempts` | same; numbers asserted against inserted attempts |
| Student routes | `/student/progress/chapters`, `/student/activity`, `/student/weak-areas`, `/student/review` | same |
| Teacher routes | `/teacher/classes`, `/teacher/classes/{id}/learners`, `.../learners/{learner}/progress`, `.../weak-areas` | same; cross-teacher and cross-student refusals |
| Notifications | `app/services/notifications.py`, `/notifications*`; deterministic producers (intervention changes, weekly class weak-topic alerts) with idempotent `dedupe_key` | `tests/integration/test_notifications_history_disposable.py` |
| Tutor history and follow-ups | `app/services/conversations.py`, `conversation_id` on `/doubts`, `/student/doubts/conversations*`; a follow-up borrows the previous student question for retrieval only | same, plus a live check with the local model |
| Migration proposal 0003 | `db/proposals/0003_notifications_and_doubt_history.py` (3 tables) and `app/db/proposed_models.py` | upgrade/downgrade and constraints on a disposable server |
| Synthetic demo population | `scripts/demo_data.py`: fictional learners and teachers, attempts submitted through the real `submit_attempt` path, optional interventions and notifications; refuses any database not named `ct_demo*` or equal to the configured one | `tests/unit/test_demo_data_safety.py`; two runs, second writes nothing |
| MVP gate | `scripts/mvp_gate.py`: 15 end-to-end HTTP checks | 15/15 pass, including the live tutor |
| Docs | `docs/API_CONTRACTS.md` (now the real route table), `docs/FRONTEND_INTEGRATION.md`, `docs/MVP_SCOPE.md`, `docs/SECURITY_PRIVACY.md`, OpenAPI (35 paths), `.env.example` | `test_openapi_export.py`, `test_public_docs.py` |

## 3. What was verified rather than rewritten

Working modules were kept as they were: BKT (`bkt-provisional-v1`, deterministic, idempotent per
attempt), graph validation and traversal, adaptive recommendation with explanations, deterministic
tie-breaking, scoring for single choice, multiple select, true/false and numeric (short answer is
never served), authentication (Argon2id, student PIN, teacher password, role and assignment
checks), the RAG pipeline with citation validation and abstention, and every security control.
Their existing tests (`test_bkt_service`, `test_prerequisite_graph`, `test_ai_adaptive_graph`,
`test_attempts_and_scope_live`, `test_attempt_concurrency`, `test_auth_*`, `test_rate_limit`,
`test_http_surface`) pass unchanged.

## 4. What was repaired

Nothing in the existing modules needed repair this round. The one defect found in my own tests
was an order dependency in the first MVP gate (the gate wrote attempts for the learner it later
used for the "empty state" check); the gate now uses separate learners.

## 5. What remains incomplete

- Interventions, notifications and tutor history are written and tested but off in the persistent
  environment until the owner approves and applies migrations 0002 and 0003 (exact steps below).
- `review_outcome` notifications are defined but no producer exists: review decisions currently do
  not notify anyone.
- AI "conversation" retention policy, parent/school notice and deletion are owner decisions.
- The AI content-review patch is not applied to the persistent database (owner decision).
- Short-answer evaluation does not exist and short-answer items are not served.
- Bell-Ringer cycles are stored by the proposed migration 0004 (added 2026-11-01, see section 12);
  disabled until the owner approves it. The topic analysis and heatmap need no new table.
- A pytest vulnerability (PYSEC-2026-1845, fixed in 9.0.3) is reported for the dev environment;
  the runtime lock file (`deploy/requirements.lock`) is clean. Upgrading is a dev-dependency
  change left for the owner.
- Teammate sign-off is still needed for owner-added routes in teammate areas.

## 6. Database schema status

Persistent database: 26 tables, Alembic `0001`, per-table row fingerprint identical to the start of
this session after all work (including the rebuilt dev backend and its read-only smoke calls).
Created, not applied: `db/proposals/0002_teacher_intervention.py`,
`db/proposals/0003_notifications_and_doubt_history.py` and `db/proposals/0004_bell_ringer_cycle.py`
(additive: 5 tables, no change to any existing table; downgrade drops only them; all verified on
disposable databases).
To adopt after approval and a verified backup (`python -m scripts.db_backup`):

```sh
cp db/proposals/0002_teacher_intervention.py db/proposals/0003_notifications_and_doubt_history.py \
   db/proposals/0004_bell_ringer_cycle.py app/db/migrations/versions/
# add the ORM models from app/db/proposed_models.py to app/db/models.py, then:
alembic upgrade 0004
# then set INTERVENTIONS_ENABLED=true NOTIFICATIONS_ENABLED=true DOUBT_HISTORY_ENABLED=true
#          BELL_RINGER_ENABLED=true
```

## 7. Test, lint and audit results

- `pytest -q` with the disposable Redis and PostgreSQL services: **998 passed, 1 skipped**. The
  skipped test (`test_seed_dev_auth.py:145`, a rollback test) needs a database with no synthetic
  accounts; it passed on a clean disposable database earlier in this project and is not affected
  by this work.
- Ruff check and format check clean (305 files). `git diff --check` clean.
- OpenAPI export current (35 paths). `pip-audit` on the runtime lock: no known vulnerabilities.
- MVP gate on the demo deployment: 15 passed, 0 failed, 0 not run (with `--with-llm`).
- Production release gate: FAIL on application, content, coverage, source_rights, bkt, rag, graph.
  This is correct and unchanged.
- Live check with `qwen3.5:9b` and `bge-m3`: a first question with weak evidence was an explicit
  abstention (`insufficient_evidence`); the follow-up in the same stored conversation was grounded
  with citations.

## 8. Security status

Unchanged and verified by tests: Argon2id hashing, server-side role and class checks, Redis
shared rate limiting (login, doubts), explicit CORS, trusted hosts, security headers, request body
limit, sanitized error envelope, production refusal without Redis, docs disabled in production,
`/health` and `/ready`, model timeout and unavailable handling, parameterised ORM queries. New
routes add no bypass: students get 403 on teacher routes, a teacher of one class gets 403 on
another, a learner not in the class is 404, another learner's conversation or notification is 404.
Notes and tutor history are never visible to teachers or sent to a provider.

## 9. Preservation evidence

Git HEAD `7bf3cc9`, staged tree `c86bd749...`, 41 staged files: identical to the start. Nothing was
staged, committed or pushed; `.env`, `.local/` ignored. The teammate's
reference project (outside this workspace) was not modified. The persistent database volume and
container were untouched (same container ID and start time); only the dev backend container was
rebuilt. Disposable resources created: database `ct_demo` on the disposable server (port 5435),
credentials file `.local/demo_credentials.json` (Git-ignored, 0600).

## 10. Commands

```sh
cd "concepttrail 2"
# 1-2. database and Redis (persistent dev stack)
docker compose --env-file .env -f deploy/compose.yaml up -d db redis
# 3. backend (container) or locally
docker compose --env-file .env -f deploy/compose.yaml up -d --build --no-deps backend
python -m uvicorn app.main:app --reload --port 8010
# 4. Ollama and models
ollama serve &   # if not already running
ollama list | grep -E "qwen3.5:9b|bge-m3"; curl -s localhost:11434/api/tags | head -c 200
# 5. tests (the two variables point at DISPOSABLE services; without them the Redis and migration
#    tests fail rather than skip silently)
export CONCEPTTRAIL_TEST_REDIS_URL=redis://127.0.0.1:6380/0
export CONCEPTTRAIL_MIGRATION_TEST_ADMIN_URL=postgresql+psycopg://<admin>@127.0.0.1:5435/postgres
pytest -q && ruff check . && ruff format --check .
# 6. algorithm evaluations (synthetic)
CONTENT_RELEASE_MODE=demo python -m evaluation.full --with-llm
python -m evaluation.bkt_synthetic; python -m evaluation.policy_simulation
# 7. MVP readiness gate (demo deployment, see docs/MVP_SCOPE.md for the setup)
python -m scripts.mvp_gate --base-url http://127.0.0.1:8020 --database-url "$DEMO_DB" --with-llm
# 8. production release gate (expected to fail today)
python -m scripts.release_gate
# 9. API documentation
python -m scripts.export_openapi      # docs/openapi/openapi-v1.json
# interactive docs are served at /docs only when API_DOCS_ENABLED=true outside production
# 10. health
curl -s localhost:8010/health; curl -s localhost:8010/ready
python -m scripts.seed_dev_auth verify   # read-only check of the dev accounts
```

## 11. Unresolved external dependencies

Owner: approve migrations 0002/0003 and a conversation retention policy; decide on applying the
content patch; acknowledge the earlier external-model read of stored passages. Teammate: sign off
on owner-added routes. Later: human content review, real-learner data for BKT calibration, display
rights, the frontend and deployment.

## 12. Addendum (2026-11-01): frontend integration, Bell Ringer and heatmap

The owner asked for the frontend to be integrated and two teacher features to be built. Backend
changes, all additive:

| Change | Files | Evidence |
|---|---|---|
| Bell-Ringer topic analysis: unique-learner counts with denominators, window, configurable criteria, prerequisite root-gap tracing, deterministic warm-up card | `app/services/bell_ringer.py`, `app/api/v1/bell_ringer.py`, `BELL_RINGER_*` settings | `tests/unit/test_bell_ringer_live.py` |
| Topic-specific Bell-Ringer cycles with baseline and follow-up; one open cycle per class and topic | proposed migration `db/proposals/0004_bell_ringer_cycle.py`, `BellRingerCycle` in `app/db/proposed_models.py` | `tests/integration/test_bell_ringer_cycles_disposable.py` (additive, reversible, idempotent, class-scoped) |
| Class heatmap route | `GET /teacher/classes/{class_id}/heatmap` | same live tests |
| Retry list now names the topic(s) of each question (`kc_ids`) so the client can open the right practice set | `app/services/progress_summary.py` | `tests/unit/test_progress_api_live.py` |
| Demo loader applies proposals 0002–0004 to the disposable database | `scripts/demo_data.py` | run on `ct_demo` (second run writes nothing) |
| Demo backend launcher (refuses any database not named `ct_demo*`) | `scripts/run_demo_backend.sh` | used for the local stack |

OpenAPI now has 40 paths. Backend suite: 1005 passed, 1 skipped (the same seed-rollback test as
before). The frontend, its tests and the visual audit are described in
[`FRONTEND_UI_AUDIT.md`](FRONTEND_UI_AUDIT.md); local start-up in
[`LOCAL_DEVELOPMENT.md`](LOCAL_DEVELOPMENT.md).

Owner decisions added: approve migration 0004 (with 0002 and 0003) and confirm the Bell-Ringer
thresholds for real classes. Teammate sign-off is needed for the new teacher routes. The Bell
Ringer design follows the ConceptTrail deck at the owner's explicit request, although CLAUDE.md
otherwise excludes the deck as a requirements source.
