"""ConceptTrail FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1.attempts import router as attempts_router
from app.api.v1.auth import router as auth_router
from app.api.v1.bell_ringer import router as bell_ringer_router
from app.api.v1.catalog import router as catalog_router
from app.api.v1.curriculum import router as curriculum_router
from app.api.v1.doubts import router as doubts_router
from app.api.v1.health import router as health_router
from app.api.v1.interventions import router as interventions_router
from app.api.v1.jobs import router as jobs_router
from app.api.v1.learning import router as learning_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.progress import router as progress_router
from app.api.v1.questions import router as questions_router
from app.api.v1.review import router as review_router
from app.api.v1.student_activity import router as student_activity_router
from app.api.v1.teacher import router as teacher_router
from app.api.v1.teacher_roster import router as teacher_roster_router
from app.core.config import get_settings
from app.core.http import RequestContextMiddleware, app_log, configure_logging


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Validate configuration before serving. Database connections remain lazy.
    settings = get_settings()
    app_log.info(
        "startup",
        extra={
            "fields": {
                "app_env": settings.app_env,
                "content_release_mode": settings.content_release_mode,
                "rate_limit_backend": settings.rate_limit_backend,
                "docs_enabled": settings.docs_enabled,
                "cors_origin_count": len(settings.cors_origins),
            }
        },
    )
    yield


def _error(request: Request, status: int, code: str, message: str, headers=None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        headers=headers,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": getattr(request.state, "request_id", "unknown"),
            }
        },
    )


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)
    docs = settings.docs_enabled
    application = FastAPI(
        title="ConceptTrail",
        version="0.2.0",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )

    @application.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        return _error(
            request,
            exc.status_code,
            detail.get("code", "http_error"),
            detail.get("message", "The request could not be completed."),
            exc.headers,
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, _exc: RequestValidationError):
        return _error(request, 422, "validation_error", "The request data is invalid.")

    application.include_router(health_router)
    for router in (
        auth_router,
        curriculum_router,
        learning_router,
        questions_router,
        attempts_router,
        progress_router,
        doubts_router,
        teacher_router,
        review_router,
        interventions_router,
        catalog_router,
        student_activity_router,
        teacher_roster_router,
        notifications_router,
        bell_ringer_router,
        jobs_router,
    ):
        application.include_router(router, prefix=settings.api_v1_prefix)

    # Added innermost first: CORS, then trusted hosts, then the outer request context.
    if settings.cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=False,  # bearer tokens in the Authorization header, not cookies
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
            expose_headers=["X-Request-ID", "Retry-After"],
            max_age=600,
        )
    if settings.trusted_host_list:
        application.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_host_list)
    application.add_middleware(
        RequestContextMiddleware,
        max_body_bytes=settings.max_request_body_bytes,
        hsts=settings.app_env == "production",
    )
    return application


app = create_app()
