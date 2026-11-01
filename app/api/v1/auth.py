"""Login and authenticated identity endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.config import ConfigurationError
from app.db.models import User
from app.db.repositories.auth_repository import AuthRepository
from app.db.session import get_db
from app.schemas.auth import LoginRequest, LoginResponse, MeResponse
from app.services.auth_service import (
    InvalidCredentials,
    LoginThrottled,
    RateLimiterUnavailable,
    authenticate,
    current_identity,
)

router = APIRouter(tags=["authentication"])


@router.post("/auth/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    session: Session = Depends(get_db),  # noqa: B008
) -> LoginResponse:
    repository = AuthRepository(session)
    try:
        _user, identity, token, expires_in = authenticate(
            repository,
            payload.login_identifier,
            payload.credential.get_secret_value(),
            client_ip=request.client.host if request.client else None,
        )
    except InvalidCredentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "invalid_credentials",
                "message": "Invalid login identifier or credential.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except LoginThrottled as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "too_many_login_attempts",
                "message": "Too many login attempts. Try again later.",
            },
            headers={"Retry-After": str(exc.retry_after)},
        ) from None
    except RateLimiterUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "login_protection_unavailable",
                "message": "Login is temporarily unavailable.",
            },
        ) from None
    except ConfigurationError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "authentication_not_configured",
                "message": "Authentication is not configured.",
            },
        ) from None
    return LoginResponse(access_token=token, expires_in=expires_in, identity=identity)


@router.get("/me", response_model=MeResponse)
def me(
    user: User = Depends(get_current_user),  # noqa: B008
    session: Session = Depends(get_db),  # noqa: B008
) -> MeResponse:
    try:
        return MeResponse(**current_identity(AuthRepository(session), user.user_id).model_dump())
    except InvalidCredentials:
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthorised", "message": "Authentication is required."},
        ) from None
