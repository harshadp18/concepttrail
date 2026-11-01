"""Password hashing and short-lived JWT access-token primitives."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import ConfigurationError, Settings, get_settings

_password_hasher = PasswordHasher()  # Argon2id is argon2-cffi's default variant.
_DUMMY_HASH: str | None = None


def hash_password(secret: str) -> str:
    """Hash a password or PIN with Argon2id."""
    if not secret:
        raise ValueError("Credential must not be empty")
    return _password_hasher.hash(secret)


def verify_password(secret: str, password_hash: str | None) -> bool:
    """Return False for absent, malformed or non-matching hashes."""
    if not secret or not password_hash:
        return False
    try:
        return _password_hasher.verify(password_hash, secret)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def dummy_password_hash() -> str:
    """A process-local dummy hash used to reduce unknown-user timing differences."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("concepttrail-dummy-credential-never-valid")
    return _DUMMY_HASH


def create_access_token(
    user_id: uuid.UUID,
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> tuple[str, int]:
    settings = settings or get_settings()
    secret = settings.jwt_secret_key
    if secret is None:
        raise ConfigurationError("JWT_SECRET_KEY must be configured before authentication is used")
    if len(secret.get_secret_value()) < 32:
        raise ConfigurationError("JWT_SECRET_KEY must contain at least 32 characters")
    issued_at = now or datetime.now(UTC)
    expires_at = issued_at + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": str(user_id),
        "iss": "concepttrail-api",
        "aud": "concepttrail-client",
        "iat": issued_at,
        "exp": expires_at,
        "jti": str(uuid.uuid4()),
        "token_type": "access",
    }
    token = jwt.encode(payload, secret.get_secret_value(), algorithm=settings.jwt_algorithm)
    return token, int((expires_at - issued_at).total_seconds())


def decode_access_token(token: str, *, settings: Settings | None = None) -> uuid.UUID:
    settings = settings or get_settings()
    secret = settings.jwt_secret_key
    if secret is None:
        raise ConfigurationError("JWT_SECRET_KEY must be configured before authentication is used")
    if len(secret.get_secret_value()) < 32:
        raise ConfigurationError("JWT_SECRET_KEY must contain at least 32 characters")
    payload = jwt.decode(
        token,
        secret.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
        issuer="concepttrail-api",
        audience="concepttrail-client",
        options={"require": ["sub", "iss", "aud", "iat", "exp", "jti", "token_type"]},
    )
    if payload.get("token_type") != "access":
        raise jwt.InvalidTokenError("Wrong token type")
    try:
        return uuid.UUID(payload["sub"])
    except (ValueError, TypeError, KeyError) as exc:
        raise jwt.InvalidTokenError("Invalid subject") from exc
