"""Liveness and readiness probes (unauthenticated, no internals in the response).

`/health`: the process answers (liveness; restart the container if this fails).
`/ready`: the database accepts a query and the rate limiter is reachable (route traffic only
when this is 200). The local model is reported but does not fail readiness: learning features
that need it return their own controlled `model_unavailable` outcome.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.core.rate_limit import RateLimiterUnavailable, get_store

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _database_ok() -> bool:
    from app.db.session import get_engine

    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001  (any failure means not ready; details stay in logs)
        return False


def _limiter_ok() -> bool:
    try:
        return get_store().healthy()
    except RateLimiterUnavailable:
        return False


def _model_state() -> str:
    from app.services.llm import LLMNotPermitted, build_llm

    try:
        return "available" if build_llm().identity().available else "unavailable"
    except LLMNotPermitted:
        return "not_permitted"


@router.get("/ready")
def ready() -> JSONResponse:
    settings = get_settings()
    checks = {
        "database": "ok" if _database_ok() else "failed",
        "rate_limiter": "ok" if _limiter_ok() else "failed",
    }
    ok = all(v == "ok" for v in checks.values())
    body = {
        "status": "ready" if ok else "not_ready",
        "checks": checks,
        "optional": {
            "local_model": _model_state(),
            "retrieval_index": "configured" if settings.rag_index_generation else "not_configured",
        },
        "content_release_mode": settings.content_release_mode,
    }
    return JSONResponse(status_code=200 if ok else 503, content=body)
