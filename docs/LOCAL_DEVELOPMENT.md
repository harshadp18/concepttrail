# Running ConceptTrail locally

These are the commands used and verified on the owner's Mac on 2026-11-01. Everything stays on
`localhost`; nothing is exposed publicly.

| Piece | Where | URL |
|---|---|---|
| Frontend (Vite dev server) | `frontend/` | http://localhost:5173 |
| Demo backend (FastAPI, disposable `ct_demo` database) | `scripts/run_demo_backend.sh` | http://localhost:8020 (API base `http://localhost:8020/api/v1`) |
| Interactive API docs (demo backend, development only) | | http://localhost:8020/docs |
| Disposable PostgreSQL 18 + pgvector (`ct_demo`) | container `ct-disposable-migrations` | 127.0.0.1:5435 |
| Disposable Redis (rate limits for the demo backend) | container `ct-disposable-redis` | 127.0.0.1:6380 |
| Local model server (Buddy) | Ollama, models `qwen3.5:9b` and `bge-m3` | 127.0.0.1:11434 |
| Persistent development stack (not used by the frontend demo) | `deploy/compose.yaml` | backend http://127.0.0.1:8010, database 127.0.0.1:5433 |

The frontend demo deliberately talks to the **demo backend on port 8020**, which serves the
disposable `ct_demo` copy with synthetic learners. The persistent database (port 5433) has no
demo learners and does not have the proposed tables; it is never written by these steps.

## One-time setup

```sh
cd "concepttrail 2"

# Python environment (already present if you ran the backend before)
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev,pipeline]"

# Frontend dependencies and the browser used by the end-to-end tests
cd frontend && npm ci && npx playwright install chromium && cd ..

# .local/demo.env holds the disposable database URL (Git-ignored, owner-only permissions).
# The password is read from the disposable container's own configuration, never typed here.
PW=$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' ct-disposable-migrations | sed -n 's/^POSTGRES_PASSWORD=//p')
mkdir -p .local && (umask 077; printf 'DEMO_DB=postgresql+psycopg://migadmin:%s@127.0.0.1:5435/ct_demo\n' "$PW" > .local/demo.env)
```

If `ct_demo` does not exist yet, create it from a verified backup and load the synthetic
population as described in [`MVP_SCOPE.md`](MVP_SCOPE.md) ("Run the demo deployment"). The loader
refuses any database whose name does not start with `ct_demo`, applies the proposed migrations
0002–0004 to that disposable database only, and is idempotent:

```sh
set -a; source .local/demo.env; set +a
CONTENT_RELEASE_MODE=demo APP_ENV=development .venv/bin/python -m scripts.demo_data load \
  --database-url "$DEMO_DB" --confirm-disposable --with-proposed-migrations
```

Demo sign-in details are written to `.local/demo_credentials.json` (Git-ignored). Students are
`demo-l6-01` … `demo-l10-10` (8-digit PINs); teachers are `demo.teacher.a@example.invalid`
(Classes 6–10) and `demo.teacher.b@example.invalid` (Class 7 only). Look the secrets up in that
file; they are not printed or documented anywhere else.

## Presentation mode (for recording a walkthrough)

Two optional, reversible switches make the synthetic demo look like an ordinary school:

```sh
# 1. fictional realistic names in the DISPOSABLE ct_demo database only (refuses anything else)
set -a; source .local/demo.env; set +a
.venv/bin/python -m scripts.demo_presentation apply --database-url "$DEMO_DB" --confirm-disposable
#    new sign-in names (same PINs/passwords) -> .local/demo_presentation_credentials.json
# 2. hide the demo labels in the UI (Git-ignored, local only); restart `npm run dev` afterwards
printf 'VITE_SHOW_DEMO_NOTICES=false\n' > frontend/.env.development.local
```

Undo both before running `scripts.demo_data`, `scripts.mvp_gate` or the end-to-end tests, which
use the original demo names:

```sh
.venv/bin/python -m scripts.demo_presentation revert --database-url "$DEMO_DB" --confirm-disposable
rm frontend/.env.development.local
```

The data stays synthetic and the content stays AI-drafted and unreviewed either way; the switches
only change labels. Do not present a recording as real learner results.

## Start everything

Open three terminals in `concepttrail 2`.

```sh
# 1. services (the containers are not set to restart automatically)
docker start ct-disposable-migrations ct-disposable-redis
pgrep -x ollama >/dev/null || ollama serve &      # Buddy; the rest works without it

# 2. demo backend on http://localhost:8020 (refuses anything but a ct_demo* database)
./scripts/run_demo_backend.sh
#    add  --reload --reload-dir app  while editing backend code

# 3. frontend on http://localhost:5173
cd frontend && npm run dev
```

`scripts/run_demo_backend.sh` sets `APP_ENV=development`, `CONTENT_RELEASE_MODE=demo`, the
Redis rate limiter on the disposable Redis, the bge-m3 index generation, the four feature flags
for the proposed tables (only because `ct_demo` has them) and
`CORS_ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173` — explicit origins, never a
wildcard. The frontend reads its API base URL from `frontend/.env.development`
(`VITE_API_BASE_URL=http://localhost:8020/api/v1`).

Check it is up:

```sh
curl -s http://localhost:8020/health          # {"status":"ok"}
curl -s http://localhost:8020/ready
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:5173/
```

## Stop everything

```sh
# frontend and demo backend: Ctrl-C in their terminals, or
kill $(lsof -tiTCP:5173 -sTCP:LISTEN) $(lsof -tiTCP:8020 -sTCP:LISTEN)
# disposable services (data is kept in the containers)
docker stop ct-disposable-migrations ct-disposable-redis
```

Never use `docker compose down -v`; it would delete the persistent database volume.

## Tests

```sh
# backend (Redis and migration tests use the disposable services)
export CONCEPTTRAIL_TEST_REDIS_URL=redis://127.0.0.1:6380/0
export CONCEPTTRAIL_MIGRATION_TEST_ADMIN_URL="postgresql+psycopg://migadmin:$PW@127.0.0.1:5435/postgres"
.venv/bin/python -m pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .

# frontend
cd frontend
npm test                      # unit tests, including the OpenAPI contract test
npm run typecheck && npm run build
npx playwright test           # browser journeys; needs the stack above running
E2E_LLM=1 npx playwright test -g @llm   # also asks Buddy (local model, up to a few minutes)
npm run ui:audit -- http://localhost:5173 run1 --login   # screenshots -> ../.local/ui-audit/run1
```

## Troubleshooting

- **"Cannot reach ConceptTrail" in the browser**: the demo backend is not running on 8020, or
  `VITE_API_BASE_URL` points elsewhere. Restart the dev server after changing `.env` files.
- **CORS error in the console**: open the app at `http://localhost:5173` (the origin the
  backend allows), not a different port.
- **Port 5173 already in use**: the dev server uses `strictPort`; stop the other process. (A
  separate Vite server for the original `CK FRONTEND` folder may be running on port 3000; it is
  unrelated and can be left alone.)
- **Buddy says it is not available**: start Ollama and check `ollama list` shows `qwen3.5:9b`
  and `bge-m3`.
- **Alerts, support plans, chat history or Bell-Ringer cycles say "not available yet"**: the
  backend is running without the proposed tables or flags (for example the 8010 stack). That is
  the correct behaviour until the owner approves migrations 0002–0004.
- **The API stops answering after backend code edits** (`/health` hangs): the `--reload` worker
  can die silently; stop the backend and start `./scripts/run_demo_backend.sh` again.
- **Signed out unexpectedly**: tokens last 30 minutes and there is no refresh endpoint; sign in
  again.
