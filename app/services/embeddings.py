"""Local embedding provider (Ollama `/api/embed`), separate from chat generation.

The embedding model and dimension are an owner decision; nothing here fixes either. The model
is passed in, its identity (name plus digest) is recorded with every vector, and a batch whose
vectors disagree in dimension, contain non-finite values or have zero norm is rejected. There
is no cloud fallback and no fake vector: when the service is down `EmbeddingUnavailable` is
raised and nothing is written.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import httpx


class EmbeddingError(RuntimeError):
    kind = "embedding_error"


class EmbeddingUnavailable(EmbeddingError):
    kind = "embedding_unavailable"


class InvalidEmbedding(EmbeddingError):
    kind = "invalid_embedding"


@dataclass(frozen=True)
class EmbeddingModel:
    name: str
    digest: str | None
    dimension: int

    @property
    def model_id(self) -> str:
        """Stored in `embedding_chunk.embedding_model_id`; ties vectors to exact weights."""
        return f"ollama:{self.name}" + (f"@{self.digest[:12]}" if self.digest else "")


class Embedder(Protocol):
    def describe(self) -> EmbeddingModel: ...
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def validate_vectors(vectors: Sequence[Sequence[float]], expected: int | None = None) -> int:
    """Return the common dimension; raise on any malformed vector."""
    if not vectors:
        raise InvalidEmbedding("no vectors")
    dimension = len(vectors[0])
    for vector in vectors:
        if len(vector) != dimension or dimension == 0:
            raise InvalidEmbedding("vectors disagree in dimension")
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in vector):
            raise InvalidEmbedding("non-finite value in vector")
        if math.sqrt(sum(x * x for x in vector)) == 0.0:
            raise InvalidEmbedding("zero vector")
    if expected is not None and dimension != expected:
        raise InvalidEmbedding(f"dimension {dimension} != expected {expected}")
    return dimension


class OllamaEmbedder:
    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        *,
        timeout: float = 120.0,
        batch_size: int = 16,
        max_retries: int = 1,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.batch_size = batch_size
        self.max_retries = max_retries
        self._client = httpx.Client(timeout=timeout, transport=transport)
        self._described: EmbeddingModel | None = None

    def _post(self, texts: list[str]) -> list[list[float]]:
        last: EmbeddingError = EmbeddingUnavailable("unknown")
        for _ in range(self.max_retries + 1):
            try:
                response = self._client.post(
                    f"{self.base_url}/api/embed", json={"model": self.model, "input": texts}
                )
                if response.status_code == 404:
                    raise EmbeddingUnavailable("model_not_installed")
                response.raise_for_status()
                vectors = response.json().get("embeddings")
                if not isinstance(vectors, list) or len(vectors) != len(texts):
                    raise InvalidEmbedding("wrong number of vectors returned")
                return vectors
            except httpx.TimeoutException:
                last = EmbeddingUnavailable("timeout")
            except (httpx.ConnectError, httpx.NetworkError):
                last = EmbeddingUnavailable("connection_failed")
            except httpx.HTTPStatusError as exc:
                last = EmbeddingUnavailable(f"http_{exc.response.status_code}")
        raise last

    def describe(self) -> EmbeddingModel:
        if self._described is None:
            try:
                tags = self._client.get(f"{self.base_url}/api/tags", timeout=5.0).json()
            except (httpx.HTTPError, ValueError) as exc:
                raise EmbeddingUnavailable(type(exc).__name__) from None
            digest = next(
                (
                    m.get("digest")
                    for m in tags.get("models", [])
                    if m.get("name") == self.model or m.get("name") == f"{self.model}:latest"
                ),
                None,
            )
            if digest is None:
                raise EmbeddingUnavailable("model_not_installed")
            dimension = validate_vectors(self._post(["dimension probe"]))
            self._described = EmbeddingModel(self.model, digest, dimension)
        return self._described

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        model = self.describe()
        out: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = [t if t.strip() else " " for t in texts[start : start + self.batch_size]]
            vectors = self._post(batch)
            validate_vectors(vectors, model.dimension)
            out.extend([float(x) for x in v] for v in vectors)
        return out


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))
