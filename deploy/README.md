# `deploy/` — local and hosted deployment

## Files

| File | Purpose |
|---|---|
| `Dockerfile` | Backend image: Python 3.12.16 base pinned by digest, dependencies installed from `requirements.lock` with `--require-hashes`, non-root user, no secrets or private records in the image. |
| `requirements.lock` | Exact, hash-verified runtime dependency set (pip-compile, constrained to the versions the test suite ran on). |
| `compose.yaml` | DEVELOPMENT stack: PostgreSQL 18 + pgvector (volume `concepttrail_pgdata`), Redis (rate-limit counters only), backend in demo mode. |
| `compose.production.yaml` | PRODUCTION-CANDIDATE stack: backend + password-protected Redis; external managed PostgreSQL; every secret required; demo mode impossible. |

## Environments

| | Development (`compose.yaml`) | Production (`compose.production.yaml`) |
|---|---|---|
| `APP_ENV` | `development` | `production` |
| Content served | `demo` (AI-generated `demo_release`, labelled) | `production` (approved/published only) |
| Rate limiter | Redis (memory allowed outside production) | Redis required; startup refuses otherwise |
| CORS | local dev origins | explicit https origins (required) |
| API docs | on | off (startup refuses `API_DOCS_ENABLED=true`) |
| Trusted hosts | not enforced | required |
| Database | `concepttrail-postgres` container, host port 5433 | external, TLS (`sslmode=require`), least-privilege user |

Settings validation (`app/core/config.py`) rejects placeholder or short secrets, equal secrets,
debug, demo content, a per-process limiter, wildcard or plain-http CORS, missing trusted hosts and
public API docs when `APP_ENV=production`.

## Development commands

Run from the repository root with the local `.env` (never committed):

```sh
docker compose --env-file .env -f deploy/compose.yaml build backend
docker compose --env-file .env -f deploy/compose.yaml up -d --no-deps redis backend
curl -s http://127.0.0.1:8010/ready
```

`--no-deps` leaves the database container untouched. Never run `docker compose down -v`: it
deletes the `concepttrail_pgdata` volume. The private authorization records are mounted read-only
into the backend at `/run/concepttrail/authorizations`; without them every rights check refuses.

## Health

- `GET /health` — liveness (process answers). Restart the container if it fails.
- `GET /ready` — readiness: database query and rate limiter (`503` if either fails). The local
  model and retrieval index are reported as optional; learning features return controlled
  `model_unavailable`/`model_timeout` outcomes without them. The container healthcheck uses `/ready`.

## Backup and restore

```sh
python -m scripts.db_backup backup     # pg_dump -Fc + manifest (row counts, constraints, sha256)
python -m scripts.db_backup verify     # restore into a throwaway container and compare
```

Backups go to `.local/backups/` (git-ignored; copy them off the machine). `verify` starts a
disposable `pgvector` container with no volume on `127.0.0.1:5434`, restores, checks every
table's row count, the Alembic revision and the key/constraint count against the manifest, and
removes the container. It never touches the live database.

Policy for production (owner to confirm with the hosting provider):

- Frequency: managed daily full backups plus continuous WAL archiving for point-in-time recovery
  (target RPO 15 minutes); a logical `pg_dump` before every migration or content import.
- Retention: 7 daily, 4 weekly, 12 monthly; encrypted at rest; stored in a different account or
  region from the database.
- Verification: an automated restore of the latest backup into a disposable instance at least
  weekly using the same manifest comparison; a failed verification is an incident.
- Restore: restore into a new instance, verify, then switch the application's `DATABASE_URL`;
  never restore over the live database.
- Ownership: the deployment owner (named in the private operations record) runs and signs off
  restore drills.

## Monitoring

Logs are JSON lines on stdout: one `concepttrail.access` line per request (request ID, method,
route template, status, duration; no bodies, query strings, tokens or identifiers), plus
`concepttrail.app` / `concepttrail.llm` events. Alert on:

- API 5xx rate and p95 latency per route; `/ready` failures.
- `429` on `/auth/login` (throttling spikes) and `503 login_protection_unavailable` (limiter down).
- Database connection failures (`/ready` database failed).
- `/doubts` outcomes: `model_timeout`, `model_unavailable`, `invalid_model_output`,
  `insufficient_evidence` rates.
- `unhandled_error` events (class name only) and `answer_verification_failed` on `/attempts`.

## Production blockers outside this repository

A managed PostgreSQL with backups/PITR; a TLS reverse proxy; a private-network inference host for
Ollama sized for the expected load; secret storage; human review and approval of content; real,
consented learning data before BKT parameters can be calibrated; privacy/legal/school review
before any real student pilot.
