"""Provider-neutral local LLM service: Qwen 3.5 9B through Ollama (D-055).

Business logic calls `LocalLLM`, never HTTP. Output is constrained by a Pydantic model: its
JSON Schema is sent as Ollama's `format`, and the reply is validated again here (the model's own
claim of validity is never trusted). There is no cloud route: the Groq fallback stays disabled,
and `build_llm` refuses any configuration that would enable it. When Ollama is down every call
raises `LLMUnavailable`, and deterministic services (scoring, BKT, recommendations) never call
this module. Prompts and replies are never logged; logs carry the request ID, model and timing.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import Settings, get_settings

log = logging.getLogger("concepttrail.llm")
T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Base class; `kind` is a stable machine-readable reason."""

    kind = "llm_error"


class LLMUnavailable(LLMError):
    kind = "model_unavailable"


class LLMTimeout(LLMError):
    kind = "model_timeout"


class LLMInvalidOutput(LLMError):
    kind = "invalid_model_output"


class LLMNotPermitted(LLMError):
    kind = "provider_not_permitted"


@dataclass(frozen=True)
class ModelIdentity:
    provider: str
    model: str
    digest: str | None
    available: bool
    detail: str = ""

    @property
    def model_id(self) -> str:
        return f"{self.provider}:{self.model}" + (f"@{self.digest[:12]}" if self.digest else "")


@dataclass(frozen=True)
class Generation:
    value: BaseModel
    model: ModelIdentity
    request_id: str
    duration_ms: int
    usage: dict[str, int]


class LocalLLM:
    """Ollama `/api/chat` with thinking disabled, structured output and bounded retries."""

    provider = "ollama"

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        num_ctx: int = 4096,
        timeout: float = 120.0,
        connect_timeout: float = 5.0,
        max_retries: int = 0,
        temperature: float = 0.2,
        max_output_tokens: int = 1200,
        keep_alive: str = "5m",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.num_ctx = num_ctx
        self.max_retries = max_retries
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.keep_alive = keep_alive
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=connect_timeout), transport=transport
        )
        self._digest: str | None = None

    def identity(self) -> ModelIdentity:
        """Model availability and digest; never raises."""
        try:
            tags = self._client.get(f"{self.base_url}/api/tags", timeout=5.0)
            tags.raise_for_status()
        except httpx.HTTPError as exc:
            return ModelIdentity(self.provider, self.model, None, False, type(exc).__name__)
        for entry in tags.json().get("models", []):
            if entry.get("name") == self.model or entry.get("model") == self.model:
                self._digest = entry.get("digest")
                return ModelIdentity(self.provider, self.model, self._digest, True)
        return ModelIdentity(self.provider, self.model, None, False, "model_not_installed")

    def generate(
        self, system: str, user: str, schema: type[T], *, request_id: str | None = None
    ) -> Generation:
        """One structured generation validated against `schema`."""
        request_id = request_id or str(uuid.uuid4())
        payload = {
            "model": self.model,
            "stream": False,
            "think": False,
            "keep_alive": self.keep_alive,
            "format": schema.model_json_schema(),
            "options": {
                "num_ctx": self.num_ctx,
                "temperature": self.temperature,
                "num_predict": self.max_output_tokens,
            },
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        started = time.monotonic()
        body: dict[str, Any] | None = None
        last: LLMError = LLMUnavailable("unknown")
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.post(f"{self.base_url}/api/chat", json=payload)
                if response.status_code == 404:
                    raise LLMUnavailable("model_not_installed")
                response.raise_for_status()
                body = response.json()
                break
            except httpx.TimeoutException as exc:
                last = LLMTimeout(type(exc).__name__)
            except (httpx.ConnectError, httpx.NetworkError) as exc:
                last = LLMUnavailable(type(exc).__name__)
            except httpx.HTTPStatusError as exc:
                last = LLMUnavailable(f"http_{exc.response.status_code}")
                if exc.response.status_code < 500:
                    break  # a client error will not improve on retry
            log.info("llm retry request_id=%s attempt=%d", request_id, attempt + 1)
        if body is None:
            raise last
        content = (body.get("message") or {}).get("content", "")
        try:
            value = schema.model_validate(json.loads(content))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise LLMInvalidOutput(type(exc).__name__) from None
        duration = int((time.monotonic() - started) * 1000)
        usage = {k: int(body[k]) for k in ("prompt_eval_count", "eval_count") if k in body}
        log.info(
            "llm ok request_id=%s model=%s ms=%d tokens=%s", request_id, self.model, duration, usage
        )
        if self._digest is None:
            self.identity()
        identity = ModelIdentity(self.provider, self.model, self._digest, True)
        return Generation(value, identity, request_id, duration, usage)


def build_llm(settings: Settings | None = None, **overrides: Any) -> LocalLLM:
    """The configured local model. A cloud primary or an enabled fallback is refused."""
    settings = settings or get_settings()
    if settings.llm_primary_provider != "ollama":
        raise LLMNotPermitted("only the local Ollama provider is permitted")
    if settings.llm_fallback_enabled:
        raise LLMNotPermitted("automatic cloud fallback is disabled by policy (D-055)")
    options: dict[str, Any] = {
        "num_ctx": settings.ollama_num_ctx,
        "timeout": float(settings.llm_timeout_seconds),
        "connect_timeout": settings.llm_connect_timeout_seconds,
        "max_retries": settings.llm_max_retries,
        "temperature": settings.llm_temperature,
        "max_output_tokens": settings.llm_max_output_tokens,
        "keep_alive": settings.ollama_keep_alive,
    }
    options.update(overrides)
    return LocalLLM(settings.ollama_base_url, settings.ollama_model, **options)


def check_local_model(llm: LocalLLM | None = None) -> ModelIdentity:
    return (llm or build_llm()).identity()
