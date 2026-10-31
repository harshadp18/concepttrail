"""Validated application settings loaded from the environment and the root `.env`.

Secret values are held as `SecretStr` and never appear in reprs, logs or error
messages. Validation failures raise `ConfigurationError`, whose message names
the failing fields and rules but never echoes the offending input.

Only settings consumed by implemented modules are declared here. Other keys in
`.env` (LLM, embedding, data paths, Docker Compose variables) are ignored until
the phase that uses them adds typed, tested fields.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"

# Values copied unchanged from `.env.example` mean "not configured".
PLACEHOLDER_PREFIXES = ("CHANGE_ME", "SET_AFTER_", "SET_TO_")
ALLOWED_DATABASE_SCHEMES = frozenset({"postgresql+psycopg"})
MIN_SECRET_LENGTH = 32
_SQL_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


class ConfigurationError(RuntimeError):
    """Raised when settings are missing or invalid. The message never contains values."""


def is_placeholder(value: str) -> bool:
    stripped = value.strip()
    return stripped == "" or stripped.startswith(PLACEHOLDER_PREFIXES)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        hide_input_in_errors=True,
        frozen=True,
    )

    app_name: str = "ConceptTrail"
    app_env: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    api_v1_prefix: str = "/api/v1"
    log_request_bodies: bool = False

    database_url: SecretStr
    db_schema: str = "concepttrail"
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=10, ge=0, le=100)
    db_pool_timeout_seconds: int = Field(default=30, ge=1, le=300)
    db_connect_timeout_seconds: int = Field(default=10, ge=1, le=120)

    secret_key: SecretStr | None = None
    jwt_secret_key: SecretStr | None = None
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_token_expire_minutes: int = Field(default=30, ge=1, le=1440)
    refresh_token_expire_days: int = Field(default=7, ge=1, le=90)

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("secret_key", "jwt_secret_key", mode="before")
    @classmethod
    def _placeholder_secret_is_unset(cls, value: Any) -> Any:
        if isinstance(value, str) and is_placeholder(value):
            return None
        return value

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value().strip()
        try:
            parts = urlsplit(raw)
        except ValueError:
            raise ValueError("DATABASE_URL is not a parseable URL") from None
        try:
            parts.port  # noqa: B018  (raises ValueError for a non-numeric or out-of-range port)
        except ValueError:
            raise ValueError("DATABASE_URL port is invalid") from None
        if parts.scheme not in ALLOWED_DATABASE_SCHEMES:
            raise ValueError(
                "DATABASE_URL must use the psycopg 3 driver scheme 'postgresql+psycopg'"
            )
        if not parts.hostname:
            raise ValueError("DATABASE_URL must include a host")
        if not parts.path.strip("/"):
            raise ValueError("DATABASE_URL must include a database name")
        if "CHANGE_ME" in raw:
            raise ValueError("DATABASE_URL still contains the .env.example placeholder")
        return SecretStr(raw)

    @field_validator("db_schema")
    @classmethod
    def _validate_db_schema(cls, value: str) -> str:
        if not _SQL_IDENTIFIER.fullmatch(value):
            raise ValueError("DB_SCHEMA must be a lowercase PostgreSQL identifier")
        return value

    @field_validator("api_v1_prefix")
    @classmethod
    def _validate_api_prefix(cls, value: str) -> str:
        if not value.startswith("/") or value.endswith("/"):
            raise ValueError("API_V1_PREFIX must start with '/' and must not end with '/'")
        return value

    @model_validator(mode="after")
    def _production_requirements(self) -> Settings:
        if self.app_env != "production":
            return self
        if self.debug:
            raise ValueError("DEBUG must be false when APP_ENV=production")
        if self.log_request_bodies:
            raise ValueError("LOG_REQUEST_BODIES must be false when APP_ENV=production")
        secrets: list[str] = []
        for name in ("secret_key", "jwt_secret_key"):
            secret: SecretStr | None = getattr(self, name)
            if secret is None:
                raise ValueError(f"{name.upper()} is required when APP_ENV=production")
            if len(secret.get_secret_value()) < MIN_SECRET_LENGTH:
                raise ValueError(
                    f"{name.upper()} must be at least {MIN_SECRET_LENGTH} characters "
                    "when APP_ENV=production"
                )
            secrets.append(secret.get_secret_value())
        if secrets[0] == secrets[1]:
            raise ValueError("SECRET_KEY and JWT_SECRET_KEY must differ")
        return self


def _describe(error: ValidationError) -> str:
    lines = []
    for item in error.errors(include_input=False, include_url=False):
        field = ".".join(str(part) for part in item["loc"]) or "settings"
        message = item["msg"].removeprefix("Value error, ")
        lines.append(f"  - {field.upper()}: {message}")
    return "Invalid ConceptTrail configuration:\n" + "\n".join(lines)


def load_settings(**overrides: Any) -> Settings:
    """Build settings, converting validation failures into a value-free error.

    Keyword overrides are passed to `Settings` (for example `_env_file=None` in tests).
    """
    try:
        return Settings(**overrides)
    except ValidationError as exc:
        raise ConfigurationError(_describe(exc)) from None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings; call `get_settings.cache_clear()` after changing the env."""
    return load_settings()
