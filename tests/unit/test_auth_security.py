"""Unit tests for authentication primitives and the development login limiter."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.services.auth_service import InMemoryLoginRateLimiter, LoginThrottled


def settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql+psycopg://user:pass@localhost:5432/testdb",
        jwt_secret_key=SecretStr("j" * 48),
        access_token_expire_minutes=10,
    )


def test_argon2id_hash_verifies_and_is_not_plaintext() -> None:
    credential = "12345678"
    encoded = hash_password(credential)
    assert encoded != credential
    assert encoded.startswith("$argon2id$")
    assert verify_password(credential, encoded)
    assert not verify_password("87654321", encoded)
    assert not verify_password(credential, None)


def test_access_token_round_trip_and_expiry() -> None:
    config = settings()
    user_id = uuid.uuid4()
    token, expires_in = create_access_token(user_id, settings=config)
    assert expires_in == 600
    assert decode_access_token(token, settings=config) == user_id

    expired = create_access_token(
        user_id,
        settings=config,
        now=datetime.now(UTC) - timedelta(minutes=20),
    )[0]
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(expired, settings=config)


def test_limiter_blocks_then_resets_after_window() -> None:
    limiter = InMemoryLoginRateLimiter(max_failures=2, window_seconds=30)
    limiter.failure("student-one", now=100.0)
    limiter.failure("student-one", now=101.0)
    with pytest.raises(LoginThrottled):
        limiter.check("student-one", now=102.0)
    limiter.check("student-one", now=162.0)
    limiter.success("student-one")
    limiter.check("student-one", now=163.0)
