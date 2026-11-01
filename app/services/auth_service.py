"""Authentication use cases and development-only login throttling."""

from __future__ import annotations

import re
import time
import uuid
from typing import TYPE_CHECKING

from app.core.config import Settings, get_settings
from app.core.rate_limit import (  # noqa: F401  (RateLimiterUnavailable is re-exported)
    MemoryStore,
    RateLimiterUnavailable,
    get_store,
    opaque_key,
)
from app.core.roles import RoleCode, recognized_roles
from app.core.security import create_access_token, dummy_password_hash, verify_password
from app.schemas.auth import AuthIdentity, ClassroomContext

if TYPE_CHECKING:
    from app.db.models import User
    from app.db.repositories.auth_repository import AuthRepository


class InvalidCredentials(Exception):
    """Credential, inactive-account or incomplete-account failure."""


class LoginThrottled(Exception):
    """The identifier has exceeded the local login-failure threshold."""

    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after


class InMemoryLoginRateLimiter:
    """Per-identifier failure throttle on a process-local store (development/test only)."""

    def __init__(self, max_failures: int = 5, window_seconds: int = 900) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._now = 0.0
        self._store = MemoryStore(clock=lambda: self._now)

    def _at(self, now: float | None) -> None:
        self._now = time.monotonic() if now is None else now

    def check(self, identifier: str, now: float | None = None) -> None:
        self._at(now)
        wait = self._store.blocked_for(opaque_key("login-id", identifier))
        if wait:
            raise LoginThrottled(wait)

    def failure(self, identifier: str, now: float | None = None) -> None:
        self._at(now)
        self._store.record_failure(
            opaque_key("login-id", identifier), self.max_failures, self.window_seconds
        )

    def success(self, identifier: str) -> None:
        self._store.clear(opaque_key("login-id", identifier))


class LoginGuard:
    """Login throttling per account identifier and per client IP on the configured store.

    Identifiers and IPs are hashed before they reach the store. Any store error raises
    `RateLimiterUnavailable`, which the login route turns into 503 (fail closed).
    """

    def __init__(self, store_factory=None, settings_factory=get_settings) -> None:
        self._store_factory = store_factory or get_store
        self._settings_factory = settings_factory

    def _keys(self, identifier: str, client_ip: str | None) -> list[tuple[str, int]]:
        settings = self._settings_factory()
        keys = [(opaque_key("login-id", identifier), settings.login_max_failures)]
        if client_ip:
            keys.append((opaque_key("login-ip", client_ip), settings.login_ip_max_failures))
        return keys

    def check(self, identifier: str, client_ip: str | None = None) -> None:
        store = self._store_factory()
        for key, _limit in self._keys(identifier, client_ip):
            wait = store.blocked_for(key)
            if wait:
                raise LoginThrottled(wait)

    def failure(self, identifier: str, client_ip: str | None = None) -> None:
        store = self._store_factory()
        window = self._settings_factory().login_failure_window_seconds
        for key, limit in self._keys(identifier, client_ip):
            store.record_failure(key, limit, window)

    def success(self, identifier: str) -> None:
        self._store_factory().clear(opaque_key("login-id", identifier))


login_rate_limiter = LoginGuard()


def _classroom_context(classroom: object) -> ClassroomContext:
    return ClassroomContext(
        classroom_id=classroom.classroom_id,  # type: ignore[attr-defined]
        grade_level=classroom.grade_level,  # type: ignore[attr-defined]
        section_label=classroom.section_label,  # type: ignore[attr-defined]
        academic_session=classroom.academic_session,  # type: ignore[attr-defined]
        school_label=classroom.school_label,  # type: ignore[attr-defined]
    )


def build_identity(repository: AuthRepository, user: User) -> AuthIdentity:
    learner = repository.learner_for_user(user.user_id)
    roles = repository.roles_for_user(user.user_id)
    enrolled = repository.enrolled_classrooms(learner.learner_id) if learner else []
    assigned = repository.assigned_classrooms(user.user_id)
    return AuthIdentity(
        user_id=user.user_id,
        login_identifier=user.login_identifier or "",
        roles=sorted(role.value for role in recognized_roles(roles)),
        learner_id=learner.learner_id if learner else None,
        display_name=learner.display_name if learner else None,
        enrolled_classrooms=[_classroom_context(item) for item in enrolled],
        assigned_classrooms=[_classroom_context(item) for item in assigned],
    )


def authenticate(
    repository: AuthRepository,
    identifier: str,
    credential: str,
    *,
    settings: Settings | None = None,
    client_ip: str | None = None,
) -> tuple[User, AuthIdentity, str, int]:
    settings = settings or get_settings()
    if settings.app_env == "production" and settings.rate_limit_backend != "redis":
        # Never a per-process limiter in production (settings validation also enforces this).
        raise RateLimiterUnavailable("shared_limiter_required")
    login_rate_limiter.check(identifier, client_ip)
    user = repository.user_by_identifier(identifier)
    stored_hash = user.password_hash if user else None
    valid = verify_password(credential, stored_hash or dummy_password_hash())
    if not valid or user is None or user.is_active is not True:
        login_rate_limiter.failure(identifier, client_ip)
        raise InvalidCredentials

    learner = repository.learner_for_user(user.user_id)
    roles = repository.roles_for_user(user.user_id)
    known_roles = recognized_roles(roles)

    # Unknown database role values must never turn an otherwise incomplete account
    # into an authenticated application principal. Student accounts require both
    # the learner record and the canonical student role. A teacher/school-admin
    # account is role-backed; a user may hold multiple recognized roles if provisioned.
    if not known_roles:
        login_rate_limiter.failure(identifier, client_ip)
        raise InvalidCredentials
    if learner is not None and RoleCode.STUDENT not in known_roles:
        login_rate_limiter.failure(identifier, client_ip)
        raise InvalidCredentials
    if learner is None and RoleCode.STUDENT in known_roles:
        login_rate_limiter.failure(identifier, client_ip)
        raise InvalidCredentials
    if learner is not None and re.fullmatch(r"[0-9]{8}", credential) is None:
        login_rate_limiter.failure(identifier, client_ip)
        raise InvalidCredentials

    login_rate_limiter.success(identifier)
    token, expires_in = create_access_token(user.user_id, settings=settings)
    return user, build_identity(repository, user), token, expires_in


def current_identity(repository: AuthRepository, user_id: uuid.UUID) -> AuthIdentity:
    user = repository.user_by_id(user_id)
    if user is None or user.is_active is not True:
        raise InvalidCredentials
    return build_identity(repository, user)
