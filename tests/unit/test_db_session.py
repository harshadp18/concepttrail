"""Engine construction and session lifecycle. No database connection is opened."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.core.config import ConfigurationError, Settings, load_settings
from app.db import session as db_session

PASSWORD = "pw-Sentinel-41d2e8"
# `.invalid` is reserved (RFC 2606), so an accidental connection attempt cannot reach a server.
UNREACHABLE_URL = f"postgresql+psycopg://ct_user:{PASSWORD}@db.invalid:5432/concepttrail_db"


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    return load_settings(_env_file=None, database_url=UNREACHABLE_URL, db_pool_size=3)


@pytest.fixture(autouse=True)
def reset_engine_cache() -> Iterator[None]:
    db_session.dispose_engine()
    yield
    db_session.dispose_engine()


def captured_engine_kwargs(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, *, read_only: bool
) -> tuple[str, dict[str, Any]]:
    captured: dict[str, Any] = {}

    def fake_create_engine(url: str, **kwargs: Any) -> str:
        captured.update(kwargs, url=url)
        return "engine"

    monkeypatch.setattr(db_session, "create_engine", fake_create_engine)
    db_session.create_db_engine(settings, read_only=read_only)
    return captured.pop("url"), captured


def test_engine_options(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    url, kwargs = captured_engine_kwargs(monkeypatch, settings, read_only=False)
    assert url == UNREACHABLE_URL
    assert kwargs["pool_pre_ping"] is True
    assert kwargs["hide_parameters"] is True
    assert kwargs["pool_size"] == 3
    assert kwargs["max_overflow"] == settings.db_max_overflow
    assert kwargs["pool_timeout"] == settings.db_pool_timeout_seconds
    assert kwargs["connect_args"] == {
        "connect_timeout": settings.db_connect_timeout_seconds,
        "application_name": "concepttrail",
    }
    assert "echo" not in kwargs


def test_read_only_engine_forces_read_only_transactions(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    _, kwargs = captured_engine_kwargs(monkeypatch, settings, read_only=True)
    assert kwargs["connect_args"]["options"] == "-c default_transaction_read_only=on"
    assert kwargs["connect_args"]["application_name"] == "concepttrail-readonly"


def test_engine_is_lazy_and_hides_the_password(settings: Settings) -> None:
    engine = db_session.create_db_engine(settings)  # .invalid host: would fail if it connected
    try:
        assert engine.url.drivername == "postgresql+psycopg"
        assert engine.url.database == "concepttrail_db"
        assert engine.pool.size() == 3
        assert engine.pool.checkedout() == 0
        assert PASSWORD not in repr(engine)
        assert PASSWORD not in str(engine.url)
    finally:
        engine.dispose()


def test_schema_mismatch_is_a_configuration_error(settings: Settings) -> None:
    other = settings.model_copy(update={"db_schema": "public"})
    with pytest.raises(ConfigurationError, match="DB_SCHEMA must be 'concepttrail'"):
        db_session.create_db_engine(other)


def test_engine_and_sessionmaker_are_cached_and_disposable(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    monkeypatch.setattr(db_session, "get_settings", lambda: settings)
    engine = db_session.get_engine()
    factory = db_session.get_sessionmaker()
    assert db_session.get_engine() is engine
    assert db_session.get_sessionmaker() is factory
    assert factory.kw["bind"] is engine
    assert factory.kw["expire_on_commit"] is False

    db_session.dispose_engine()
    assert db_session.get_engine() is not engine


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def commit(self) -> None:
        self.calls.append("commit")

    def rollback(self) -> None:
        self.calls.append("rollback")

    def close(self) -> None:
        self.calls.append("close")


@pytest.fixture
def fake_session(monkeypatch: pytest.MonkeyPatch) -> FakeSession:
    fake = FakeSession()
    monkeypatch.setattr(db_session, "get_sessionmaker", lambda: lambda: fake)
    return fake


def test_get_db_closes_without_committing(fake_session: FakeSession) -> None:
    dependency = db_session.get_db()
    assert next(dependency) is fake_session
    with pytest.raises(StopIteration):
        next(dependency)
    assert fake_session.calls == ["close"]


def test_get_db_rolls_back_and_reraises_on_error(fake_session: FakeSession) -> None:
    dependency = db_session.get_db()
    next(dependency)
    with pytest.raises(RuntimeError, match="boom"):
        dependency.throw(RuntimeError("boom"))
    assert fake_session.calls == ["rollback", "close"]


def test_get_db_closes_when_abandoned(fake_session: FakeSession) -> None:
    dependency = db_session.get_db()
    next(dependency)
    dependency.close()
    assert fake_session.calls == ["close"]


def test_get_db_yields_a_real_session_without_connecting(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    monkeypatch.setattr(db_session, "get_settings", lambda: settings)
    dependency = db_session.get_db()
    session = next(dependency)
    assert isinstance(session, Session)
    assert not session.in_transaction()
    dependency.close()
    assert db_session.get_engine().pool.checkedout() == 0


def test_declarative_base_metadata_conventions() -> None:
    metadata = db_session.Base.metadata
    assert metadata.schema == "concepttrail"
    assert metadata.naming_convention["pk"] == "%(table_name)s_pkey"
    assert metadata.naming_convention["fk"] == "%(table_name)s_%(column_0_name)s_fkey"
    assert metadata.naming_convention["uq"] == "%(table_name)s_%(column_0_name)s_key"
