"""Validated application settings loaded from the environment and the root `.env`.

Secret values are held as `SecretStr` and never appear in reprs, logs or error
messages. Validation failures raise `ConfigurationError`, whose message names
the failing fields and rules but never echoes the offending input.

Only settings consumed by implemented modules are declared here. Other keys in
`.env` (embedding, data paths, Docker Compose variables, retired provider keys) are
ignored until the phase that uses them adds typed, tested fields.

LLM provider settings (D-055) describe the approved architecture: local Ollama (Qwen) as the
primary and Groq (GPT-OSS 120B) as a fallback candidate that stays disabled. They are
configuration only: no provider adapter exists yet, and nothing here enables fallback or
authorises sending textbook content to a cloud provider.
"""

from __future__ import annotations

import ipaddress
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
LLM_PROVIDERS = ("ollama", "groq")
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/\-]{0,127}$")
# Ollama durations: "5m", "30s", "1h", a number of seconds, "0" (unload) or "-1" (keep loaded).
_KEEP_ALIVE = re.compile(r"^(?:-1|\d+|\d+(?:\.\d+)?(?:s|m|h))$")
MIN_PROVIDER_KEY_LENGTH = 16
# Explicit on purpose: `ipaddress.is_private` also covers documentation and reserved ranges.
PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
)


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

    # Content serving: "production" serves only human-approved/published content. "demo" also
    # serves AI-generated `demo_release` content and is refused outside development/test.
    content_release_mode: Literal["production", "demo"] = "production"

    # --- LLM providers (D-055): Qwen via local Ollama primary, Groq fallback (disabled) ---
    llm_primary_provider: Literal["ollama", "groq"] = "ollama"
    llm_fallback_provider: Literal["ollama", "groq"] = "groq"
    llm_fallback_enabled: bool = False
    llm_timeout_seconds: int = Field(default=120, ge=1, le=600)
    llm_connect_timeout_seconds: float = Field(default=5.0, ge=0.5, le=60)
    llm_max_output_tokens: int = Field(default=1200, ge=16, le=8192)
    llm_max_retries: int = Field(default=0, ge=0, le=5)
    llm_temperature: float = Field(default=0.2, ge=0.0, le=2.0)

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3.5:9b"
    ollama_num_ctx: int = Field(default=4096, ge=512, le=262144)
    ollama_think: bool = False
    ollama_keep_alive: str = "5m"

    groq_api_key: SecretStr | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "openai/gpt-oss-120b"

    secret_key: SecretStr | None = None
    jwt_secret_key: SecretStr | None = None
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_token_expire_minutes: int = Field(default=30, ge=1, le=1440)
    refresh_token_expire_days: int = Field(default=7, ge=1, le=90)

    # --- Rate limiting: "memory" is per process (development/test only); production needs a
    # shared backend so every worker and container sees the same counters.
    rate_limit_backend: Literal["memory", "redis"] = "memory"
    redis_url: SecretStr | None = None
    login_max_failures: int = Field(default=5, ge=1, le=100)
    login_failure_window_seconds: int = Field(default=900, ge=60, le=86400)
    login_ip_max_failures: int = Field(default=50, ge=1, le=10000)
    doubt_requests_per_hour: int = Field(default=30, ge=1, le=1000)

    # --- HTTP surface. Comma-separated values; empty means none.
    cors_allowed_origins: str = ""
    trusted_hosts: str = ""
    api_docs_enabled: bool | None = None  # default: on outside production, off in production
    max_request_body_bytes: int = Field(default=1_000_000, ge=1024, le=50_000_000)

    # --- Retrieval: the embedding model and index generation the doubt service searches.
    rag_embedding_model: str = "bge-m3"
    rag_index_generation: str | None = None

    # Teacher interventions use a PROPOSED table (db/proposals/0002_teacher_intervention.py).
    # Enable only after the owner approves and applies that migration.
    interventions_enabled: bool = False
    # Notifications and tutor conversation history use PROPOSED tables
    # (db/proposals/0003_notifications_and_doubt_history.py). Enable only after approval.
    notifications_enabled: bool = False
    doubt_history_enabled: bool = False
    # Bell-Ringer cycles use a PROPOSED table (db/proposals/0004_bell_ringer_cycle.py). The
    # read-only topic analysis works without it. Thresholds decide when a topic is flagged:
    # share of enrolled learners with enough evidence, unique learners below the weak cut-off,
    # and their share among learners with evidence. Provisional; tune with real data.
    bell_ringer_enabled: bool = False
    bell_ringer_min_coverage: float = Field(default=0.3, ge=0.0, le=1.0)
    bell_ringer_min_affected_learners: int = Field(default=2, ge=1, le=500)
    bell_ringer_min_affected_share: float = Field(default=0.4, ge=0.0, le=1.0)
    bell_ringer_window_days: int = Field(default=14, ge=1, le=365)

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def trusted_host_list(self) -> list[str]:
        return [h.strip() for h in self.trusted_hosts.split(",") if h.strip()]

    @property
    def docs_enabled(self) -> bool:
        if self.api_docs_enabled is not None:
            return self.api_docs_enabled
        return self.app_env != "production"

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("groq_api_key", mode="before")
    @classmethod
    def _placeholder_provider_key_is_unset(cls, value: Any) -> Any:
        if isinstance(value, str) and is_placeholder(value):
            return None
        return value

    @field_validator("groq_api_key")
    @classmethod
    def _validate_provider_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        raw = value.get_secret_value().strip()
        if len(raw) < MIN_PROVIDER_KEY_LENGTH or any(ch.isspace() for ch in raw):
            raise ValueError("GROQ_API_KEY is not a plausible API key")
        return SecretStr(raw)

    @field_validator("ollama_model", "groq_model")
    @classmethod
    def _validate_model_id(cls, value: str, info: Any) -> str:
        raw = value.strip()
        if is_placeholder(raw) or not _MODEL_ID.fullmatch(raw):
            raise ValueError(f"{info.field_name.upper()} must be a model identifier")
        return raw

    @field_validator("ollama_keep_alive")
    @classmethod
    def _validate_keep_alive(cls, value: str) -> str:
        raw = value.strip()
        if not _KEEP_ALIVE.fullmatch(raw):
            raise ValueError("OLLAMA_KEEP_ALIVE must be like 5m, 30s, 1h, 0 or -1")
        return raw

    @field_validator("ollama_base_url", "groq_base_url")
    @classmethod
    def _validate_service_url(cls, value: str, info: Any) -> str:
        name = info.field_name.upper()
        raw = value.strip()
        try:
            parts = urlsplit(raw)
            parts.port  # noqa: B018  (raises ValueError for a non-numeric or out-of-range port)
        except ValueError:
            raise ValueError(f"{name} is not a parseable URL") from None
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError(f"{name} must be an http(s) URL with a host")
        if parts.username or parts.password:
            raise ValueError(f"{name} must not contain credentials")
        if parts.query or parts.fragment:
            raise ValueError(f"{name} must not contain a query or fragment")
        if info.field_name == "groq_base_url" and parts.scheme != "https":
            raise ValueError("GROQ_BASE_URL must use https")
        return raw.rstrip("/")

    @field_validator("redis_url", mode="before")
    @classmethod
    def _placeholder_redis_is_unset(cls, value: Any) -> Any:
        if isinstance(value, str) and is_placeholder(value):
            return None
        return value

    @field_validator("redis_url")
    @classmethod
    def _validate_redis_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        parts = urlsplit(value.get_secret_value().strip())
        if parts.scheme not in ("redis", "rediss") or not parts.hostname:
            raise ValueError("REDIS_URL must be a redis:// or rediss:// URL with a host")
        return value

    @field_validator("cors_allowed_origins")
    @classmethod
    def _validate_origins(cls, value: str) -> str:
        for origin in (o.strip() for o in value.split(",") if o.strip()):
            if origin == "*":
                raise ValueError("CORS_ALLOWED_ORIGINS must list origins explicitly, never '*'")
            parts = urlsplit(origin)
            if parts.scheme not in ("http", "https") or not parts.hostname:
                raise ValueError("CORS_ALLOWED_ORIGINS entries must be http(s) origins")
            if parts.path.strip("/") or parts.query or parts.fragment or parts.username:
                raise ValueError("CORS_ALLOWED_ORIGINS entries must be bare origins")
        return value

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
    def _demo_only_in_development(self) -> Settings:
        if self.content_release_mode == "demo" and self.app_env not in ("development", "test"):
            raise ValueError(
                "CONTENT_RELEASE_MODE=demo is allowed only when APP_ENV is development or test"
            )
        return self

    @model_validator(mode="after")
    def _provider_consistency(self) -> Settings:
        if self.llm_fallback_enabled and self.llm_fallback_provider == self.llm_primary_provider:
            raise ValueError("LLM_FALLBACK_PROVIDER must differ from LLM_PRIMARY_PROVIDER")
        # The Groq key is optional only while no Groq route can be used.
        uses_groq = self.llm_primary_provider == "groq" or (
            self.llm_fallback_enabled and self.llm_fallback_provider == "groq"
        )
        if uses_groq and self.groq_api_key is None:
            raise ValueError(
                "GROQ_API_KEY is required when Groq is the primary provider or fallback is enabled"
            )
        if self.llm_max_output_tokens >= self.ollama_num_ctx:
            raise ValueError("LLM_MAX_OUTPUT_TOKENS must be smaller than OLLAMA_NUM_CTX")
        if self.llm_connect_timeout_seconds > self.llm_timeout_seconds:
            raise ValueError("LLM_CONNECT_TIMEOUT_SECONDS must not exceed LLM_TIMEOUT_SECONDS")
        return self

    @model_validator(mode="after")
    def _production_requirements(self) -> Settings:
        if self.app_env != "production":
            return self
        if self.debug:
            raise ValueError("DEBUG must be false when APP_ENV=production")
        if self.log_request_bodies:
            raise ValueError("LOG_REQUEST_BODIES must be false when APP_ENV=production")
        if not _ollama_url_is_safe(self.ollama_base_url):
            raise ValueError(
                "OLLAMA_BASE_URL must use https, or http only to a loopback or private-network"
                " host, when APP_ENV=production (never expose Ollama on a public address)"
            )
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
        if self.content_release_mode != "production":
            raise ValueError("CONTENT_RELEASE_MODE must be production when APP_ENV=production")
        if self.rate_limit_backend != "redis" or self.redis_url is None:
            raise ValueError(
                "RATE_LIMIT_BACKEND=redis and REDIS_URL are required when APP_ENV=production"
                " (a per-process limiter cannot protect several workers)"
            )
        if not _redis_url_is_safe(self.redis_url.get_secret_value()):
            raise ValueError(
                "REDIS_URL must use rediss://, or redis:// only to a loopback or private-network"
                " host, when APP_ENV=production"
            )
        if any(urlsplit(o).scheme != "https" for o in self.cors_origins):
            raise ValueError("CORS_ALLOWED_ORIGINS must be https origins when APP_ENV=production")
        hosts = self.trusted_host_list
        if not hosts or any(h == "*" or h.startswith("*") and h.count(".") < 2 for h in hosts):
            raise ValueError(
                "TRUSTED_HOSTS must list the served host names when APP_ENV=production"
            )
        if self.docs_enabled:
            raise ValueError("API_DOCS_ENABLED must be false when APP_ENV=production")
        return self


def _ollama_url_is_safe(url: str) -> bool:
    """https always; plain http only to loopback or a private-network address."""
    parts = urlsplit(url)
    if parts.scheme == "https":
        return True
    host = parts.hostname or ""
    if host in LOOPBACK_HOSTS:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False  # a DNS name over plain http cannot be shown to be private
    return (
        address.is_loopback or address.is_link_local or any(address in n for n in PRIVATE_NETWORKS)
    )


def _redis_url_is_safe(url: str) -> bool:
    """rediss always; plain redis only to loopback, a private address or a single-label service
    name (a Compose/Kubernetes service such as `redis`, which public DNS cannot resolve)."""
    parts = urlsplit(url)
    if parts.scheme == "rediss":
        return True
    host = parts.hostname or ""
    if host and "." not in host and ":" not in host:
        return True
    return _ollama_url_is_safe(f"http://{host}")


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
