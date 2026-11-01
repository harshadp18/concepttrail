"""Local KC and prerequisite-edge candidate drafting (D17), disabled unless authorised.

Conditions (guidelines, section 10), all enforced before any model call:

1. Local inference only: Ollama on localhost (`qwen3.5:9b`, thinking off, `num_ctx` 4096). Any
   non-loopback base URL is refused; no external provider is supported.
2. A separate owner rights record grants `local_llm_kc_drafting` (or
   `local_llm_prerequisite_edge_drafting`) for **every** cited source's exact bytes. No such
   record exists today, so every real call is refused (`DraftingNotAuthorised`).
3. Hindi drafting is refused until output quality has been evaluated.
4. Output is schema-constrained and validated with the loader's own row rules; a failing draft
   is discarded, never repaired. Drafts are `needs_review`, `origin=ai_drafted`, with an
   `origin_ref` to a generation record (model, prompt version and digests; no textbook text),
   no author, no review records. Fields a model must not set are rejected
   (`AI_FIELD_VIOLATION`); a model never adds a vocabulary entry.
"""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.services.audit_chain import digest, sha256_hex
from data_pipeline import authorization
from data_pipeline.kc_graph import contract as c
from data_pipeline.kc_graph.csv_io import CsvRow
from data_pipeline.kc_graph.rows import parse_edge, parse_kc
from data_pipeline.kc_graph.sources import SourceIndex
from data_pipeline.kc_graph.vocabulary import Vocabulary

PROMPT_VERSION = "kc-graph-drafting-v1"
PROMPT_FILE = c.PROJECT_ROOT / "data_pipeline/prompts/kc_graph_drafting_v1.md"
DEFAULT_MODEL = "qwen3.5:9b"
DEFAULT_BASE_URL = "http://localhost:11434"
DISABLED_SUBJECTS = ("hindi",)
KC_USE, EDGE_USE = authorization.DRAFTING_USES
KC_DRAFT_FIELDS = {
    "stable_key",
    "name",
    "learning_objective",
    "kc_type",
    "misconceptions",
    "declared_class_levels",
    "scope",
    "source_refs",
    "difficulty_tier",
    "aliases",
}
EDGE_DRAFT_FIELDS = {
    "prerequisite_kc_id",
    "dependent_kc_id",
    "dependency_basis",
    "reason",
    "strength",
    "evidence_refs",
}


class DraftingNotAuthorised(RuntimeError):
    pass


@dataclass(frozen=True)
class Draft:
    rows: list[dict[str, str]]  # valid candidate rows in CSV-header order
    discarded: list[dict[str, Any]]  # {"index", "codes"} only; no model text
    generation: dict[str, Any]


def require_local(base_url: str) -> str:
    host = urlparse(base_url).hostname or ""
    if host != "localhost":
        try:
            if not ipaddress.ip_address(host).is_loopback:
                raise DraftingNotAuthorised("only a local (loopback) Ollama endpoint is allowed")
        except ValueError as exc:
            raise DraftingNotAuthorised(
                "only a local (loopback) Ollama endpoint is allowed"
            ) from exc
    return base_url.rstrip("/")


class OllamaChat:
    """Minimal local Ollama `/api/chat` client. `transport` is injectable for mock tests."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        num_ctx: int = 4096,
        timeout: float = 120.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = require_local(base_url)
        self.model, self.num_ctx = model, num_ctx
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def chat(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "stream": False,
            "think": False,
            "format": schema,
            "options": {"num_ctx": self.num_ctx, "temperature": 0},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        response = self._client.post(f"{self.base_url}/api/chat", json=payload)
        response.raise_for_status()
        return json.loads(response.json()["message"]["content"])


def authorise(
    task: str,
    subject_id: str,
    tokens: Sequence[str],
    sources: SourceIndex,
    records: list[dict[str, Any]] | None = None,
) -> None:
    """Raise `DraftingNotAuthorised` unless every condition holds. Called before any request."""
    if subject_id in DISABLED_SUBJECTS:
        raise DraftingNotAuthorised("Hindi drafting is disabled until quality is evaluated")
    if not tokens:
        raise DraftingNotAuthorised("drafting needs at least one cited source token")
    use = KC_USE if task == "kc" else EDGE_USE
    for token in sorted({t.split("@", 1)[0].removeprefix("src:") for t in tokens}):
        doc = sources.documents.get(token)
        if doc is None:
            raise DraftingNotAuthorised(f"{token} is not in the accepted inventory")
        decision = authorization.check_use(token, doc.sha256, use, records)
        if not decision.permitted:
            raise DraftingNotAuthorised(f"{token}: {use} refused: {decision.reason}")


def _schema(task: str, vocab: Vocabulary, subject_id: str, tokens: Sequence[str]) -> dict:
    if task == "kc":
        item = {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "stable_key",
                "name",
                "learning_objective",
                "kc_type",
                "scope",
                "source_refs",
            ],
            "properties": {
                "stable_key": {"type": "string"},
                "name": {"type": "string"},
                "learning_objective": {"type": "string"},
                "kc_type": {"enum": sorted(vocab.kc_types)},
                "scope": {"enum": list(c.SCOPES)},
                "declared_class_levels": {"type": "array", "items": {"enum": list(c.CLASS_LEVELS)}},
                "misconceptions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["id", "text"],
                        "additionalProperties": False,
                        "properties": {"id": {"type": "string"}, "text": {"type": "string"}},
                    },
                },
                "source_refs": {"type": "array", "items": {"enum": list(tokens)}},
            },
        }
    else:
        item = {
            "type": "object",
            "additionalProperties": False,
            "required": ["prerequisite_kc_id", "dependent_kc_id", "dependency_basis", "reason"],
            "properties": {
                "prerequisite_kc_id": {"type": "string"},
                "dependent_kc_id": {"type": "string"},
                "dependency_basis": {"enum": sorted(vocab.dependency_bases)},
                "reason": {"type": "string"},
                "evidence_refs": {"type": "array", "items": {"enum": list(tokens)}},
            },
        }
    return {
        "type": "object",
        "required": ["candidates"],
        "additionalProperties": False,
        "properties": {"candidates": {"type": "array", "items": item}},
    }


def _system_prompt() -> str:
    text = PROMPT_FILE.read_text(encoding="utf-8")
    return text.split("## System message", 1)[1].split("## User message", 1)[0].strip()


def draft(
    task: str,
    subject_id: str,
    request: dict[str, Any],
    tokens: Sequence[str],
    vocab: Vocabulary,
    sources: SourceIndex,
    client: OllamaChat,
    *,
    next_kc_id: Callable[[str], str] | None = None,
    records: list[dict[str, Any]] | None = None,
    generated_on: str,
) -> Draft:
    """Authorise, call the local model once, validate, and return candidate rows."""
    authorise(task, subject_id, tokens, sources, records)
    if any(k in request for k in ("review_status", "reviewer_id", "author_id")):
        raise ValueError("the request may not carry review fields")
    system = _system_prompt()
    user = json.dumps(
        {"task": task, "subject_id": subject_id, **request, "source_tokens": list(tokens)},
        ensure_ascii=False,
        sort_keys=True,
    )
    schema = _schema(task, vocab, subject_id, tokens)
    output = client.chat(system, user, schema)
    generation = {
        "record_type": "kc_graph_generation",
        "task": task,
        "subject_id": subject_id,
        "model": client.model,
        "num_ctx": client.num_ctx,
        "think": False,
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": sha256_hex(system.encode("utf-8")),
        "request_sha256": sha256_hex(user.encode("utf-8")),
        "input_refs_sha256": digest(sorted(tokens)),
        "output_sha256": digest(output),
        "generated_on": generated_on,
        "vocabulary": vocab.manifest(),
        "note": "no textbook text is stored in this record",
    }
    generation["generation_id"] = f"GEN-{generated_on}-{digest(generation)[:10]}"
    allowed = KC_DRAFT_FIELDS if task == "kc" else EDGE_DRAFT_FIELDS
    header = c.KC_HEADER if task == "kc" else c.EDGE_HEADER
    rows, discarded = [], []
    candidates = output.get("candidates") if isinstance(output, dict) else None
    for index, cand in enumerate(candidates if isinstance(candidates, list) else []):
        if not isinstance(cand, dict) or set(cand) - allowed:
            discarded.append({"index": index, "codes": ["AI_FIELD_VIOLATION"]})
            continue
        cells = dict.fromkeys(header, "")
        for k, v in cand.items():
            if isinstance(v, list):
                cells[k] = (
                    json.dumps(v, ensure_ascii=False)
                    if k == "misconceptions"
                    else c.LIST_SEPARATOR.join(map(str, v))
                )
            else:
                cells[k] = "" if v is None else str(v)
        cells.update(
            origin="ai_drafted",
            origin_ref=generation["generation_id"],
            review_status="needs_review",
            review_record_ids="",
            author_id="",
        )
        if task == "kc":
            cells.update(
                subject_id=subject_id,
                content_version="kc-v1",
                kc_id=next_kc_id(subject_id) if next_kc_id else "",
            )
            _, findings = parse_kc(CsvRow(0, cells), vocab, "draft")
        else:
            _, findings = parse_edge(CsvRow(0, cells), vocab, "draft")
        bad = sorted({f.code for f in findings if f.severity == "error"})
        if task == "kc" and cells["subject_id"] != subject_id:
            bad.append("SUBJECT_ID_MISMATCH")
        if bad:
            discarded.append({"index": index, "codes": bad})
        else:
            rows.append(cells)
    generation["kept"], generation["discarded"] = len(rows), len(discarded)
    return Draft(rows, discarded, generation)


def write_generation(directory: Path, generation: dict[str, Any]) -> Path:
    from data_pipeline.teacher_validation import write_once

    return write_once(directory / f"{generation['generation_id']}.json", generation)[0]
