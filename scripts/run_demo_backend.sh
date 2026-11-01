#!/usr/bin/env bash
# Serve the API against the DISPOSABLE demo database (ct_demo), never the persistent one.
#
# Reads DEMO_DB from .local/demo.env (Git-ignored, 0600; see docs/LOCAL_DEVELOPMENT.md). Refuses
# to start unless the database name starts with ct_demo. Feature flags for the proposed tables are
# enabled here only because ct_demo has proposals 0002-0004 applied by scripts/demo_data.py.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f .local/demo.env ]]; then
  echo "missing .local/demo.env (DEMO_DB=postgresql+psycopg://...:5435/ct_demo)" >&2
  exit 1
fi
set -a
# shellcheck disable=SC1091
source .local/demo.env
set +a
db_name="${DEMO_DB##*/}"
db_name="${db_name%%\?*}"
if [[ "$db_name" != ct_demo* ]]; then
  echo "refusing: DEMO_DB must point at a ct_demo* database (got '$db_name')" >&2
  exit 1
fi
PORT="${PORT:-8020}"
export DATABASE_URL="$DEMO_DB"
export APP_ENV=development
export API_DOCS_ENABLED=true
export CONTENT_RELEASE_MODE=demo
export INTERVENTIONS_ENABLED=true
export NOTIFICATIONS_ENABLED=true
export DOUBT_HISTORY_ENABLED=true
export BELL_RINGER_ENABLED=true
export RATE_LIMIT_BACKEND=redis
export REDIS_URL="${DEMO_REDIS_URL:-redis://127.0.0.1:6380/1}"
export RAG_INDEX_GENERATION="${RAG_INDEX_GENERATION:-ig-dev-1-bge-m3}"
export CORS_ALLOWED_ORIGINS="${CORS_ALLOWED_ORIGINS:-http://localhost:5173,http://127.0.0.1:5173}"
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" "$@"
