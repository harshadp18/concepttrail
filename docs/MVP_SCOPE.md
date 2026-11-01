# MVP backend scope and readiness

Two readiness concepts are kept apart on purpose.

| | MVP backend readiness | Production readiness |
|---|---|---|
| Question it answers | Does the backend work end to end so a frontend can be built and demonstrated? | May real students rely on this content and model? |
| Data allowed | Synthetic learners, AI-reviewed and AI-generated `demo_release` content, synthetic BKT evaluation | Human-approved content, verified rights, real calibration data |
| Command | `python -m scripts.mvp_gate` | `python -m scripts.release_gate` (strict; unchanged) |
| Today | 15 of 15 checks pass on the demo deployment (see `docs/BACKEND_MVP_REPORT.md`) | Fails all gates, by design |

Passing the MVP gate does not mean: human-reviewed content, real student evidence, real-world BKT
calibration, verified learning improvement, or production content approval. Content stays
`demo_release`; the runtime BKT configuration stays `bkt-provisional-v1`; synthetic calibration
and policy simulations live in `evaluation/` and never change runtime parameters.

## What the MVP backend covers

Authentication and server-side authorization for students and teachers; class-subject catalog,
chapters, topics, prerequisites; deterministic question delivery and scoring for single choice,
multiple select, true/false and numeric (short answer is never served); idempotent attempts with
BKT updates; chapter and subject progress, weak areas, retry list; a deterministic explained
recommendation; a local-model tutor that cites stored pages or abstains; teacher roster, learner
progress, class weak areas, question review and (after migration approval) interventions and
notifications; a synthetic demo population; security controls (shared Redis rate limits, CORS,
trusted hosts, security headers, body limits, sanitized errors).

## Run the demo deployment

The demo uses a disposable copy of the database, never the persistent one. Commands (adapt the
backup file; the disposable PostgreSQL server in these examples is the test container on port 5435):

```sh
# 1. disposable database from a verified backup, with the pgvector extension first
docker exec ct-disposable-migrations psql -U migadmin -d postgres -c 'CREATE DATABASE ct_demo'
docker exec ct-disposable-migrations psql -U migadmin -d ct_demo -c 'CREATE EXTENSION IF NOT EXISTS vector'
docker exec -i ct-disposable-migrations pg_restore -U migadmin -d ct_demo --no-owner --no-privileges < .local/backups/<backup>.dump
export DEMO_DB="postgresql+psycopg://migadmin:<disposable password>@127.0.0.1:5435/ct_demo"

# 2. optionally apply the AI content-review patch to the DISPOSABLE copy only
python -m data_pipeline.content_review.patch apply --database-url "$DEMO_DB" --apply

# 3. load the fictional population (refuses any database not named ct_demo*)
CONTENT_RELEASE_MODE=demo APP_ENV=development python -m scripts.demo_data load \
  --database-url "$DEMO_DB" --confirm-disposable --with-proposed-migrations

# 4. serve it
./scripts/run_demo_backend.sh     # reads DEMO_DB from .local/demo.env; see docs/LOCAL_DEVELOPMENT.md

# 5. gate (add --with-llm for the live tutor)
python -m scripts.mvp_gate --base-url http://127.0.0.1:8020 --database-url "$DEMO_DB" --with-llm
```

The loader submits its synthetic attempts through the real `submit_attempt` path, so mastery and
progress are derived by the same code as for real learners, but only inside the disposable
database. Everything it creates is labelled (`SYNTHETIC-DEMO` classrooms, `DEMO` learner names,
`demo-` logins, `is_synthetic` notifications). It is idempotent: a second run replays the same
idempotency keys and writes nothing new.

## Deferred to production (not blockers for the MVP)

Independent subject-expert and Hindi review; human approval of content (the release gate rejects
AI review as approval); real-learner BKT calibration (needs >= 2000 events from >= 30 learners);
controlled learning-outcome evidence; display/indexing rights for production sources; owner
approval of migrations 0002, 0003 and 0004; a retention policy for tutor conversations; teammate
sign-off on owner-added routes; deployment. (The frontend now lives in `frontend/`.)
