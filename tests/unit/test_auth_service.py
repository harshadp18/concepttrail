"""Authentication service tests using a repository double (no PostgreSQL required)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.core.security import hash_password
from app.services import auth_service
from app.services.auth_service import InvalidCredentials, authenticate


class FakeAuthRepository:
    def __init__(
        self, *, learner: object | None, roles: list[str], stored_credential: str | None = None
    ) -> None:
        self.user = SimpleNamespace(
            user_id=uuid.uuid4(),
            login_identifier="learner-001" if learner else "teacher@school.example",
            password_hash=hash_password(
                stored_credential or ("12345678" if learner else "teacher-password")
            ),
            is_active=True,
        )
        self.learner = learner
        self.roles = roles

    def user_by_identifier(self, _identifier: str):
        return self.user

    def learner_for_user(self, _user_id: uuid.UUID):
        return self.learner

    def roles_for_user(self, _user_id: uuid.UUID):
        return self.roles

    def enrolled_classrooms(self, _learner_id: uuid.UUID):
        return []

    def assigned_classrooms(self, _user_id: uuid.UUID):
        return []


def test_student_username_and_eight_digit_pin_authenticate() -> None:
    learner = SimpleNamespace(learner_id=uuid.uuid4(), display_name="Test learner")
    repository = FakeAuthRepository(learner=learner, roles=["student"])
    config = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://user:pass@localhost:5432/testdb",
        jwt_secret_key=SecretStr("j" * 48),
    )
    auth_service.login_rate_limiter.success("learner-001")

    _user, identity, token, expires_in = authenticate(
        repository, "learner-001", "12345678", settings=config
    )

    assert identity.learner_id == learner.learner_id
    assert identity.display_name == "Test learner"
    assert token
    assert expires_in == 1800


def test_student_rejects_non_eight_digit_pin() -> None:
    learner = SimpleNamespace(learner_id=uuid.uuid4(), display_name="Test learner")
    repository = FakeAuthRepository(learner=learner, roles=["student"], stored_credential="1234")
    config = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://user:pass@localhost:5432/testdb",
        jwt_secret_key=SecretStr("j" * 48),
    )
    auth_service.login_rate_limiter.success("learner-001")

    with pytest.raises(InvalidCredentials):
        authenticate(repository, "learner-001", "1234", settings=config)


def test_teacher_email_and_password_authenticate() -> None:
    repository = FakeAuthRepository(learner=None, roles=["teacher"])
    config = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://user:pass@localhost:5432/testdb",
        jwt_secret_key=SecretStr("j" * 48),
    )
    auth_service.login_rate_limiter.success("teacher@school.example")

    _user, identity, token, _expires_in = authenticate(
        repository, "teacher@school.example", "teacher-password", settings=config
    )

    assert identity.roles == ["teacher"]
    assert identity.learner_id is None
    assert token


def test_unknown_only_role_cannot_authenticate() -> None:
    repository = FakeAuthRepository(learner=None, roles=["future_superuser"])
    config = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://user:pass@localhost:5432/testdb",
        jwt_secret_key=SecretStr("j" * 48),
    )
    auth_service.login_rate_limiter.success("teacher@school.example")

    with pytest.raises(InvalidCredentials):
        authenticate(repository, "teacher@school.example", "teacher-password", settings=config)


def test_learner_record_without_student_role_cannot_authenticate() -> None:
    learner = SimpleNamespace(learner_id=uuid.uuid4(), display_name="Test learner")
    repository = FakeAuthRepository(learner=learner, roles=["teacher"])
    config = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://user:pass@localhost:5432/testdb",
        jwt_secret_key=SecretStr("j" * 48),
    )
    auth_service.login_rate_limiter.success("learner-001")

    with pytest.raises(InvalidCredentials):
        authenticate(repository, "learner-001", "12345678", settings=config)
