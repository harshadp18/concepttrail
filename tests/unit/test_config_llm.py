"""Typed LLM provider settings (D-055). Never reads the developer's real `.env`.

Configuration only: these tests do not exercise a provider adapter, because none exists.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.core import config
from app.core.config import ConfigurationError, Settings, load_settings

PASSWORD = "pw-Sentinel-7f3a9c"
VALID_URL = f"postgresql+psycopg://ct_user:{PASSWORD}@127.0.0.1:5433/concepttrail_db"
GROQ_KEY = "gsk_SENTINEL_not_a_real_key_0123456789"
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


def production(**overrides: object) -> Settings:
    base = {
        "app_env": "production",
        "secret_key": STRONG_A,
        "jwt_secret_key": STRONG_B,
        "rate_limit_backend": "redis",
        "redis_url": "redis://10.0.0.7:6379/0",
        "trusted_hosts": "api.school.example",
    }
    return make(**{**base, **overrides})


def test_defaults_are_qwen_primary_groq_fallback_disabled() -> None:
    s = make()
    assert s.llm_primary_provider == "ollama"
    assert s.llm_fallback_provider == "groq"
    assert s.llm_fallback_enabled is False
    assert s.ollama_base_url == "http://localhost:11434"
    assert s.ollama_model == "qwen3.5:9b"
    assert s.ollama_num_ctx == 4096
    assert s.ollama_think is False
    assert s.ollama_keep_alive == "5m"
    assert s.groq_base_url == "https://api.groq.com/openai/v1"
    assert s.groq_model == "openai/gpt-oss-120b"
    assert (s.llm_timeout_seconds, s.llm_connect_timeout_seconds) == (120, 5.0)
    assert (s.llm_max_output_tokens, s.llm_max_retries) == (1200, 0)
    assert 0.1 <= s.llm_temperature <= 0.2


def test_groq_key_is_not_required_while_fallback_is_disabled() -> None:
    s = make()
    assert s.groq_api_key is None
    assert make(llm_fallback_enabled=False, groq_api_key="CHANGE_ME").groq_api_key is None


def test_groq_key_is_required_when_fallback_is_enabled() -> None:
    with pytest.raises(ConfigurationError, match="GROQ_API_KEY is required"):
        make(llm_fallback_enabled=True)
    s = make(llm_fallback_enabled=True, groq_api_key=GROQ_KEY)
    assert s.llm_fallback_enabled is True
    assert s.groq_api_key is not None and s.groq_api_key.get_secret_value() == GROQ_KEY


@pytest.mark.parametrize("value", ["", "   ", "CHANGE_ME", "CHANGE_ME_later", "SET_AFTER_X"])
def test_placeholder_groq_keys_are_unset_and_never_satisfy_the_requirement(value: str) -> None:
    assert make(groq_api_key=value).groq_api_key is None
    with pytest.raises(ConfigurationError, match="GROQ_API_KEY is required"):
        make(llm_fallback_enabled=True, groq_api_key=value)


@pytest.mark.parametrize("value", ["short", "has a space in the middle of a long key 123"])
def test_implausible_groq_keys_are_rejected_without_echoing_them(value: str) -> None:
    with pytest.raises(ConfigurationError) as excinfo:
        make(groq_api_key=value)
    assert "GROQ_API_KEY" in str(excinfo.value)
    assert value not in str(excinfo.value)


def test_secret_values_never_appear_in_reprs_dumps_or_errors() -> None:
    s = make(llm_fallback_enabled=True, groq_api_key=GROQ_KEY)
    for rendered in (repr(s), str(s), str(s.model_dump()), str(s.model_dump_json())):
        assert GROQ_KEY not in rendered
        assert PASSWORD not in rendered
    with pytest.raises(ConfigurationError) as excinfo:
        make(groq_api_key=GROQ_KEY, ollama_num_ctx=10)
    assert GROQ_KEY not in str(excinfo.value)
    assert PASSWORD not in str(excinfo.value)
    with pytest.raises(ConfigurationError) as excinfo:
        make(ollama_base_url=f"http://user:{GROQ_KEY}@localhost:11434")
    assert GROQ_KEY not in str(excinfo.value)


def test_groq_as_primary_also_requires_the_key() -> None:
    with pytest.raises(ConfigurationError, match="GROQ_API_KEY is required"):
        make(llm_primary_provider="groq", llm_fallback_provider="ollama")


def test_fallback_provider_must_differ_from_primary_when_enabled() -> None:
    with pytest.raises(ConfigurationError, match="must differ"):
        make(llm_fallback_enabled=True, llm_fallback_provider="ollama", groq_api_key=GROQ_KEY)


@pytest.mark.parametrize("name", ["gemini", "deepseek", "openai", ""])
def test_retired_or_unknown_providers_are_rejected(name: str) -> None:
    with pytest.raises(ConfigurationError, match="LLM_PRIMARY_PROVIDER"):
        make(llm_primary_provider=name)
    with pytest.raises(ConfigurationError, match="LLM_FALLBACK_PROVIDER"):
        make(llm_fallback_provider=name)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:11434",
        "http://localhost:11434/",
        "http://127.0.0.1:11434",
        "http://[::1]:11434",
        "https://ollama.internal.example",
    ],
)
def test_valid_ollama_urls_in_development(url: str) -> None:
    assert not make(ollama_base_url=url).ollama_base_url.endswith("/")


@pytest.mark.parametrize(
    "url",
    [
        "ftp://localhost:11434",
        "localhost:11434",
        "http://",
        "http://localhost:99999",
        "http://user:pw@localhost:11434",
        "http://localhost:11434?x=1",
        "http://localhost:11434#frag",
    ],
)
def test_invalid_ollama_urls_are_rejected(url: str) -> None:
    with pytest.raises(ConfigurationError, match="OLLAMA_BASE_URL"):
        make(ollama_base_url=url)


@pytest.mark.parametrize(
    "url",
    ["http://203.0.113.10:11434", "http://ollama.example.com:11434", "http://8.8.8.8:11434"],
)
def test_public_http_ollama_is_rejected_in_production(url: str) -> None:
    with pytest.raises(ConfigurationError, match="OLLAMA_BASE_URL must use https"):
        production(ollama_base_url=url)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:11434",
        "http://127.0.0.1:11434",
        "http://10.0.0.5:11434",
        "http://192.168.1.20:11434",
        "https://ollama.example.com",
    ],
)
def test_loopback_private_or_https_ollama_is_allowed_in_production(url: str) -> None:
    assert production(ollama_base_url=url).app_env == "production"


def test_public_http_ollama_is_allowed_only_outside_production() -> None:
    assert make(ollama_base_url="http://203.0.113.10:11434").app_env == "development"


def test_groq_base_url_must_be_https_without_credentials() -> None:
    assert make(groq_base_url="https://api.groq.com/openai/v1/").groq_base_url.endswith("/v1")
    for url in ("http://api.groq.com/openai/v1", "https://u:p@api.groq.com/openai/v1"):
        with pytest.raises(ConfigurationError, match="GROQ_BASE_URL"):
            make(groq_base_url=url)


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("ollama_num_ctx", 100),
        ("ollama_num_ctx", 10**7),
        ("llm_max_output_tokens", 0),
        ("llm_max_output_tokens", 10**6),
        ("llm_max_retries", -1),
        ("llm_max_retries", 50),
        ("llm_timeout_seconds", 0),
        ("llm_timeout_seconds", 10_000),
        ("llm_connect_timeout_seconds", 0),
        ("llm_temperature", -0.1),
        ("llm_temperature", 5),
    ],
)
def test_invalid_numeric_ranges_are_rejected(field: str, bad: object) -> None:
    with pytest.raises(ConfigurationError, match=field.upper()):
        make(**{field: bad})


def test_output_tokens_must_fit_inside_the_context_window() -> None:
    with pytest.raises(ConfigurationError, match="smaller than OLLAMA_NUM_CTX"):
        make(llm_max_output_tokens=4096, ollama_num_ctx=4096)
    assert make(llm_max_output_tokens=2000, ollama_num_ctx=8192).ollama_num_ctx == 8192


def test_connect_timeout_cannot_exceed_total_timeout() -> None:
    with pytest.raises(ConfigurationError, match="must not exceed"):
        make(llm_connect_timeout_seconds=30, llm_timeout_seconds=10)


@pytest.mark.parametrize("value", ["5m", "30s", "1h", "0", "-1", "300", "1.5h"])
def test_valid_keep_alive(value: str) -> None:
    assert make(ollama_keep_alive=value).ollama_keep_alive == value


@pytest.mark.parametrize("value", ["", "five minutes", "5 m", "-5m", "5d"])
def test_invalid_keep_alive(value: str) -> None:
    with pytest.raises(ConfigurationError, match="OLLAMA_KEEP_ALIVE"):
        make(ollama_keep_alive=value)


@pytest.mark.parametrize("name", ["ollama_model", "groq_model"])
@pytest.mark.parametrize("value", ["", "CHANGE_ME", "SET_TO_A_MODEL", "bad model", "x;rm -rf"])
def test_invalid_model_identifiers(name: str, value: str) -> None:
    with pytest.raises(ConfigurationError, match=name.upper()):
        make(**{name: value})


def test_thinking_flag_parses_from_environment_strings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", VALID_URL)
    monkeypatch.setenv("OLLAMA_THINK", "false")
    assert load_settings(_env_file=None).ollama_think is False
    monkeypatch.setenv("OLLAMA_THINK", "true")
    assert load_settings(_env_file=None).ollama_think is True


def test_database_configuration_is_unaffected() -> None:
    s = make()
    assert s.database_url.get_secret_value() == VALID_URL
    assert s.db_schema == "concepttrail"
    with pytest.raises(ConfigurationError, match="DATABASE_URL"):
        load_settings(_env_file=None)


def test_env_example_documents_the_current_architecture_without_secrets() -> None:
    text = (config.PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    values = dict(
        line.split("=", 1)
        for line in text.splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    )
    assert values["LLM_PRIMARY_PROVIDER"] == "ollama"
    assert values["LLM_FALLBACK_PROVIDER"] == "groq"
    assert values["LLM_FALLBACK_ENABLED"] == "false"
    assert values["OLLAMA_MODEL"] == "qwen3.5:9b"
    assert values["GROQ_MODEL"] == "openai/gpt-oss-120b"
    assert values["GROQ_API_KEY"] == "CHANGE_ME"
    for retired in ("GEMINI", "DEEPSEEK"):
        assert not any(key.startswith(retired) for key in values)
    for key in values:
        assert (
            not key.startswith("EMBEDDING")
            or values[key].startswith("SET_AFTER_")
            or key in ("EMBEDDING_DISTANCE_METRIC",)
        )


def test_llm_dependency_group_matches_the_architecture() -> None:
    import tomllib

    pyproject = tomllib.loads((config.PROJECT_ROOT / "pyproject.toml").read_text("utf-8"))
    llm = [
        d.split(">")[0].split("=")[0].strip()
        for d in pyproject["project"]["optional-dependencies"]["llm"]
    ]
    assert llm == ["groq"]  # no Gemini SDK; Ollama is reached over httpx
    core = {
        d.split(">")[0].split("=")[0].split("[")[0] for d in pyproject["project"]["dependencies"]
    }
    assert "httpx" in core and "openai" not in core
