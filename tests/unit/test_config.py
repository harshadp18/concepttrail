"""Settings loading and validation. Never reads the developer's real `.env`."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.core import config
from app.core.config import ConfigurationError, Settings, load_settings

PASSWORD = "pw-Sentinel-7f3a9c"
VALID_URL = f"postgresql+psycopg://ct_user:{PASSWORD}@127.0.0.1:5433/concepttrail_db"
STRONG_A = "a" * 24 + "-strong-secret-A"
STRONG_B = "b" * 24 + "-strong-secret-B"


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


def make(**overrides: object) -> Settings:
    overrides.setdefault("database_url", VALID_URL)
    return load_settings(_env_file=None, **overrides)


def assert_no_secret_leak(text: str) -> None:
    for secret in (PASSWORD, "ct_user", STRONG_A, STRONG_B):
        assert secret not in text


def test_minimal_valid_settings_use_safe_defaults() -> None:
    settings = make()
    assert settings.app_env == "development"
    assert settings.debug is False
    assert settings.log_request_bodies is False
    assert settings.db_schema == "concepttrail"
    assert settings.api_v1_prefix == "/api/v1"
    assert settings.secret_key is None and settings.jwt_secret_key is None
    assert settings.database_url.get_secret_value() == VALID_URL


def test_missing_database_url_raises_configuration_error() -> None:
    with pytest.raises(ConfigurationError, match="DATABASE_URL"):
        load_settings(_env_file=None)


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        (f"postgresql://ct_user:{PASSWORD}@127.0.0.1:5433/db", "psycopg 3 driver"),
        (f"mysql+pymysql://ct_user:{PASSWORD}@127.0.0.1/db", "psycopg 3 driver"),
        (f"postgresql+psycopg://ct_user:{PASSWORD}@/db", "include a host"),
        (f"postgresql+psycopg://ct_user:{PASSWORD}@127.0.0.1:5433", "database name"),
        (f"postgresql+psycopg://ct_user:{PASSWORD}@127.0.0.1:99999/db", "port"),
        ("postgresql+psycopg://ct_user:CHANGE_ME@localhost:5432/concepttrail_db", "placeholder"),
    ],
)
def test_invalid_database_url_is_rejected_without_echoing_it(url: str, reason: str) -> None:
    with pytest.raises(ConfigurationError) as excinfo:
        make(database_url=url)
    message = str(excinfo.value)
    assert reason in message
    assert "DATABASE_URL" in message
    assert_no_secret_leak(message)
    assert url not in message
    assert excinfo.value.__cause__ is None  # the pydantic error (which holds input) is dropped


def test_settings_repr_and_dump_hide_secrets() -> None:
    settings = make(secret_key=STRONG_A, jwt_secret_key=STRONG_B)
    for rendered in (repr(settings), str(settings), str(settings.model_dump())):
        assert_no_secret_leak(rendered)
    assert isinstance(settings.database_url, SecretStr)


@pytest.mark.parametrize(
    "value", ["", "   ", "CHANGE_ME", "CHANGE_ME_generate_a_long_random_secret", "SET_AFTER_X"]
)
def test_placeholder_secrets_are_treated_as_unset(value: str) -> None:
    settings = make(secret_key=value, jwt_secret_key=value)
    assert settings.secret_key is None
    assert settings.jwt_secret_key is None


PRODUCTION = {
    "app_env": "production",
    "secret_key": STRONG_A,
    "jwt_secret_key": STRONG_B,
    "rate_limit_backend": "redis",
    "redis_url": "rediss://cache.internal.example:6380/0",
    "trusted_hosts": "api.school.example",
    "cors_allowed_origins": "https://app.school.example",
}


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("redis://:pw@redis:6379/0", True),  # compose service name on a private network
        ("redis://10.1.2.3:6379/0", True),
        ("rediss://cache.example.com:6380/0", True),
        ("redis://cache.example.com:6379/0", False),  # plain text to a public name
    ],
)
def test_production_redis_transport(url: str, ok: bool) -> None:
    values = {**PRODUCTION, "redis_url": url}
    if ok:
        assert make(**values).redis_url is not None
    else:
        with pytest.raises(ConfigurationError, match="REDIS_URL must use rediss"):
            make(**values)


def test_valid_production_settings() -> None:
    settings = make(**PRODUCTION)
    assert settings.app_env == "production"
    assert settings.docs_enabled is False
    assert settings.cors_origins == ["https://app.school.example"]


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"debug": True}, "DEBUG must be false"),
        ({"log_request_bodies": True}, "LOG_REQUEST_BODIES must be false"),
        ({"secret_key": None}, "SECRET_KEY is required"),
        ({"jwt_secret_key": "CHANGE_ME"}, "JWT_SECRET_KEY is required"),
        ({"secret_key": "too-short"}, "at least 32 characters"),
        ({"jwt_secret_key": STRONG_A}, "must differ"),
        ({"content_release_mode": "demo"}, "CONTENT_RELEASE_MODE=demo is allowed only"),
        ({"rate_limit_backend": "memory"}, "RATE_LIMIT_BACKEND=redis and REDIS_URL"),
        ({"redis_url": None}, "RATE_LIMIT_BACKEND=redis and REDIS_URL"),
        ({"redis_url": "redis://cache.example.com:6379/0"}, "REDIS_URL must use rediss"),
        ({"cors_allowed_origins": "http://app.school.example"}, "must be https origins"),
        ({"cors_allowed_origins": "*"}, "never '\\*'"),
        ({"trusted_hosts": ""}, "TRUSTED_HOSTS must list"),
        ({"trusted_hosts": "*"}, "TRUSTED_HOSTS must list"),
        ({"api_docs_enabled": True}, "API_DOCS_ENABLED must be false"),
    ],
)
def test_production_requirements(overrides: dict[str, object], reason: str) -> None:
    values: dict[str, object] = dict(PRODUCTION)
    values.update(overrides)
    with pytest.raises(ConfigurationError, match=reason) as excinfo:
        make(**values)
    assert_no_secret_leak(str(excinfo.value))


@pytest.mark.parametrize("schema", ["Concepttrail", "public;drop", "1schema", ""])
def test_db_schema_must_be_a_lowercase_identifier(schema: str) -> None:
    with pytest.raises(ConfigurationError, match="DB_SCHEMA"):
        make(db_schema=schema)


@pytest.mark.parametrize("prefix", ["api/v1", "/api/v1/"])
def test_api_prefix_shape(prefix: str) -> None:
    with pytest.raises(ConfigurationError, match="API_V1_PREFIX"):
        make(api_v1_prefix=prefix)


def test_unknown_app_env_and_bad_pool_size_are_rejected() -> None:
    with pytest.raises(ConfigurationError, match="APP_ENV"):
        make(app_env="prod")
    with pytest.raises(ConfigurationError, match="DB_POOL_SIZE"):
        make(db_pool_size=0)


def test_log_level_is_normalised() -> None:
    assert make(log_level=" debug ").log_level == "DEBUG"


def test_settings_are_immutable() -> None:
    settings = make()
    with pytest.raises(Exception, match="frozen"):
        settings.debug = True  # type: ignore[misc]


def test_env_file_is_loaded_and_unrelated_keys_are_ignored(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "APP_ENV=test",
                "DEBUG=true",
                f"DATABASE_URL={VALID_URL}",
                "DB_SCHEMA=concepttrail",
                "GEMINI_API_KEY=CHANGE_ME",
                "EMBEDDING_DIMENSIONS=SET_AFTER_BENCHMARK",
                f"POSTGRES_PASSWORD={PASSWORD}",
            ]
        ),
        encoding="utf-8",
    )
    settings = load_settings(_env_file=env_file)
    assert settings.app_env == "test"
    assert settings.debug is True
    assert not hasattr(settings, "postgres_password")
    assert not hasattr(settings, "gemini_api_key")


def test_process_environment_overrides_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"DATABASE_URL={VALID_URL}\nLOG_LEVEL=INFO\n", encoding="utf-8")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    assert load_settings(_env_file=env_file).log_level == "WARNING"


def test_env_example_template_is_rejected_safely() -> None:
    """`.env.example` still holds placeholders, so it must not validate as a real config."""
    with pytest.raises(ConfigurationError, match="placeholder") as excinfo:
        load_settings(_env_file=config.PROJECT_ROOT / ".env.example")
    assert "concepttrail_user" not in str(excinfo.value)


def test_get_settings_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def fake_load_settings() -> Settings:
        calls.append(1)
        return make()

    monkeypatch.setattr(config, "load_settings", fake_load_settings)
    first = config.get_settings()
    assert config.get_settings() is first
    assert len(calls) == 1
