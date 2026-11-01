"""Retrieval over existing content units: chunking, gated ingestion, embedding, retrieval, context.

Eligible source → `content_unit` → chunk (`embedding_chunk`, no new column) → local embedding →
pgvector cosine search with **hard filters in SQL** → dedupe → evidence → token-bounded context.

Gates, all enforced in code before any model sees text:

- **Indexing** (chunking and embedding) needs the purpose-specific rights decision
  `check_use(source_id, sha256, "indexing_retrieval")`, the stored source digest to match, and
  usable extracted text. Exclusions are returned with their reason.
- **Retrieval** always filters by embedding model and index generation (never mixing vectors)
  and by class, subject, curriculum version and chapter when given. `mode="student"` (the only
  mode for learner-facing use) additionally requires an `approved` content unit and a source
  whose stored `permitted_uses` include `student_facing_display`. `mode="internal"` (owner
  evaluation) relaxes only the review requirement, never rights.

Chunk identity is deterministic: uuid5 of content unit, generation, order and text digest.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.content_release import demo_enabled
from app.db.models import (
    ContentUnit,
    CurriculumItem,
    CurriculumVersion,
    EmbeddingChunk,
    SourceDocument,
)
from app.services.embeddings import Embedder, EmbeddingModel

CHUNKER_VERSION = "chunker-v1"
NAMESPACE = uuid.UUID("0b7c6a1e-2d3f-4e5a-9b8c-7d6e5f4a3b2c")
INDEXING_USE = "indexing_retrieval"
DISPLAY_USE = "student_facing_display"
UNUSABLE_EXTRACTION = ("failed", "text_unusable", "not_started")
FLAGGED_PAGES = ("low_quality_extraction", "scanned")

_SENTENCE = re.compile(r"(?<=[.!?।])\s+")
_MATH = re.compile(r"[=<>≤≥±×÷√∑∫π^]|\b\d+\s*/\s*\d+\b|\\frac|\\sqrt")
_HEADING = re.compile(
    r"^(?:\d+(?:\.\d+)*\s+\S.*|[A-Z][A-Z0-9 ,:'-]{3,80}|(?:Chapter|Unit|Activity|"
    r"Example|Exercise|अध्याय|पाठ)\b.*)$"
)
_INJECTION = re.compile(
    r"(?i)(ignore (?:all |the )?(?:previous|above|prior) instructions?|disregard (?:the )?"
    r"(?:previous|above) |you are now|system prompt|<\|[^|]*\|>|\b(?:assistant|system|user)\s*:)"
)


def estimate_tokens(text: str) -> int:
    """Conservative token estimate (no tokenizer dependency): Latin ~4 chars per token,
    Devanagari and other scripts ~2 chars per token."""
    latin = sum(1 for ch in text if ord(ch) < 0x0250)
    other = len(text) - latin
    return max(1, math.ceil(latin / 4 + other / 2))


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


@dataclass(frozen=True)
class Block:
    text: str
    kind: Literal["heading", "equation", "text"]


def split_blocks(text: str) -> list[Block]:
    blocks = []
    for raw in re.split(r"\n\s*\n", text.strip()):
        para = raw.strip()
        if not para:
            continue
        lines = [ln for ln in para.splitlines() if ln.strip()]
        if len(lines) == 1 and len(para) <= 90 and _HEADING.match(para) and not para.endswith("."):
            blocks.append(Block(para, "heading"))
        elif _MATH.search(para) and len(_MATH.findall(para)) >= max(1, len(para.split()) // 8):
            blocks.append(Block(para, "equation"))
        else:
            blocks.append(Block(para, "text"))
    return blocks


@dataclass(frozen=True)
class Chunk:
    chunk_id: uuid.UUID
    order: int
    text: str
    token_count: int


def chunk_content_unit(
    content_unit_id: str,
    text: str,
    index_generation: str,
    *,
    max_tokens: int = 320,
    overlap_tokens: int = 48,
) -> list[Chunk]:
    """Heading- and paragraph-aware chunks of one content unit (never across units).

    Equation blocks are atomic (kept whole even if long); long prose splits at sentence
    ends (Latin and Devanagari). A heading opens a new chunk and travels with what follows.
    The last paragraph of a chunk is repeated at the start of the next when it fits the
    overlap budget. Identical chunk texts are emitted once.
    """
    pieces: list[Block] = []
    for block in split_blocks(text):
        if block.kind == "text" and estimate_tokens(block.text) > max_tokens:
            pieces.extend(Block(s, "text") for s in _SENTENCE.split(block.text) if s.strip())
        else:
            pieces.append(block)
    chunks_text: list[str] = []
    current: list[Block] = []

    def flush() -> None:
        if any(b.kind != "heading" for b in current):
            chunks_text.append("\n\n".join(b.text for b in current))

    for block in pieces:
        size = sum(estimate_tokens(b.text) for b in current)
        starts_section = block.kind == "heading" and any(b.kind != "heading" for b in current)
        if current and (starts_section or size + estimate_tokens(block.text) > max_tokens):
            flush()
            tail = current[-1]
            carry = (
                not starts_section
                and tail.kind != "heading"
                and estimate_tokens(tail.text) <= overlap_tokens
            )
            current = [tail] if carry else []
        current.append(block)
    if current:
        flush()
    out, seen = [], set()
    for chunk_text in chunks_text:
        key = _norm(chunk_text)
        if key in seen:
            continue
        seen.add(key)
        order = len(out)
        chunk_id = uuid.uuid5(
            NAMESPACE, f"{content_unit_id}|{index_generation}|{order}|{_digest(chunk_text)}"
        )
        out.append(Chunk(chunk_id, order, chunk_text, estimate_tokens(chunk_text)))
    return out


@dataclass
class IngestReport:
    index_generation: str
    eligible_units: int = 0
    chunks_created: int = 0
    chunks_existing: int = 0
    excluded: dict[str, str] = field(default_factory=dict)  # content_unit_id -> reason


def ingest_eligible_content(
    session: Session,
    index_generation: str,
    check_use: Callable[..., Any],
    *,
    source_ids: Sequence[str] | None = None,
    records: list[dict[str, Any]] | None = None,
    write: bool = True,
) -> IngestReport:
    """Chunk every eligible content unit into `embedding_chunk` (no vectors yet). No commit.

    With `write=False` nothing is added to the session (a dry run)."""
    report = IngestReport(index_generation)
    query = select(ContentUnit, SourceDocument).join(
        SourceDocument, SourceDocument.source_id == ContentUnit.source_id
    )
    if source_ids is not None:
        query = query.where(ContentUnit.source_id.in_(list(source_ids)))
    existing_ids = set(
        session.scalars(
            select(EmbeddingChunk.chunk_id).where(
                EmbeddingChunk.index_generation == index_generation
            )
        )
    )
    now = datetime.now(UTC)
    for unit, source in session.execute(query.order_by(ContentUnit.content_unit_id)):
        reason = None
        decision = check_use(source.source_id, source.sha256 or "", INDEXING_USE, records)
        if not decision.permitted:
            reason = f"rights:{decision.reason}"
        elif unit.extraction_status in UNUSABLE_EXTRACTION:
            reason = f"extraction:{unit.extraction_status}"
        elif not (unit.content_text or "").strip():
            reason = "no_text"
        elif unit.content_sha256 and unit.content_sha256 != _digest(unit.content_text or ""):
            reason = "content_hash_mismatch"
        if reason:
            report.excluded[unit.content_unit_id] = reason
            continue
        report.eligible_units += 1
        for chunk in chunk_content_unit(
            unit.content_unit_id, unit.content_text or "", index_generation
        ):
            if chunk.chunk_id in existing_ids:
                report.chunks_existing += 1
                continue
            existing_ids.add(chunk.chunk_id)
            report.chunks_created += 1
            if not write:
                continue
            session.add(
                EmbeddingChunk(
                    chunk_id=chunk.chunk_id,
                    content_unit_id=unit.content_unit_id,
                    chunk_order=chunk.order,
                    chunk_text=chunk.text,
                    token_count=chunk.token_count,
                    embedding_model_id=None,
                    embedding=None,
                    index_generation=index_generation,
                    created_at=now,
                )
            )
    if write:
        session.flush()
    return report


def generation_model(session: Session, index_generation: str) -> str | None:
    models = set(
        session.scalars(
            select(EmbeddingChunk.embedding_model_id)
            .where(
                EmbeddingChunk.index_generation == index_generation,
                EmbeddingChunk.embedding_model_id.is_not(None),
            )
            .distinct()
        )
    )
    if len(models) > 1:
        raise ValueError(f"index generation {index_generation} mixes embedding models")
    return next(iter(models), None)


def embed_chunks(
    session: Session, embedder: Embedder, index_generation: str, *, batch: int = 32
) -> int:
    """Embed the generation's chunks that have no vector. Refuses to mix models. No commit."""
    model: EmbeddingModel = embedder.describe()
    current = generation_model(session, index_generation)
    if current is not None and current != model.model_id:
        raise ValueError(f"generation {index_generation} already uses {current}")
    pending = list(
        session.scalars(
            select(EmbeddingChunk)
            .where(
                EmbeddingChunk.index_generation == index_generation,
                EmbeddingChunk.embedding.is_(None),
            )
            .order_by(EmbeddingChunk.content_unit_id, EmbeddingChunk.chunk_order)
        )
    )
    done = 0
    for start in range(0, len(pending), batch):
        rows = pending[start : start + batch]
        vectors = embedder.embed([r.chunk_text or "" for r in rows])
        for row, vector in zip(rows, vectors, strict=True):
            row.embedding = vector
            row.embedding_model_id = model.model_id
        done += len(rows)
        session.flush()
    return done


@dataclass(frozen=True)
class Evidence:
    label: str
    chunk_id: uuid.UUID
    content_unit_id: str
    source_id: str
    source_sha256: str | None
    pdf_page_index: int | None
    printed_page_label: str | None
    item_id: str | None
    item_title: str | None
    curriculum_version_id: str | None
    content_sha256: str | None
    review_status: str | None
    embedding_model_id: str
    index_generation: str
    score: float
    text: str

    def citation(self) -> dict[str, Any]:
        return {
            k: (str(v) if isinstance(v, uuid.UUID) else v)
            for k, v in self.__dict__.items()
            if k != "text"
        }


@dataclass(frozen=True)
class RetrievalFilter:
    class_level: int | None = None
    subject_id: str | None = None
    curriculum_version_id: str | None = None
    item_ids: tuple[str, ...] | None = None
    source_ids: tuple[str, ...] | None = None


NO_FILTER = RetrievalFilter()


def retrieve_evidence(
    session: Session,
    query_vector: Sequence[float],
    *,
    embedding_model_id: str,
    index_generation: str,
    filters: RetrievalFilter = NO_FILTER,
    mode: Literal["student", "demo", "internal"] = "student",
    k: int = 5,
    min_score: float = 0.35,
) -> list[Evidence]:
    """Top-k evidence after hard filters, ranked by cosine similarity, deduplicated."""
    distance = EmbeddingChunk.embedding.cosine_distance(list(query_vector)).label("distance")
    query = (
        select(EmbeddingChunk, ContentUnit, SourceDocument, CurriculumItem, distance)
        .join(ContentUnit, ContentUnit.content_unit_id == EmbeddingChunk.content_unit_id)
        .join(SourceDocument, SourceDocument.source_id == ContentUnit.source_id)
        .outerjoin(CurriculumItem, CurriculumItem.item_id == ContentUnit.item_id)
        .outerjoin(
            CurriculumVersion,
            CurriculumVersion.curriculum_version_id == CurriculumItem.curriculum_version_id,
        )
        .where(
            EmbeddingChunk.embedding_model_id == embedding_model_id,
            EmbeddingChunk.index_generation == index_generation,
            EmbeddingChunk.embedding.is_not(None),
            SourceDocument.permitted_uses.contains([INDEXING_USE]),
        )
    )
    if mode == "student":
        query = query.where(
            and_(
                ContentUnit.review_status == "approved",
                SourceDocument.permitted_uses.contains([DISPLAY_USE]),
            )
        )
    if mode == "demo":
        # Demo learners: pages with usable, unflagged extraction (still display-rights gated).
        # Refused unless demo mode is enabled in a development environment.
        if not demo_enabled():
            raise PermissionError("demo retrieval requires CONTENT_RELEASE_MODE=demo")
        query = query.where(
            ContentUnit.extraction_status.not_in(UNUSABLE_EXTRACTION),
            ContentUnit.asset_refs["classification"].astext.not_in(FLAGGED_PAGES),
            SourceDocument.permitted_uses.contains([DISPLAY_USE]),
        )
    if filters.class_level is not None:
        query = query.where(CurriculumVersion.class_level == filters.class_level)
    if filters.subject_id is not None:
        query = query.where(SourceDocument.subject_id == filters.subject_id)
    if filters.curriculum_version_id is not None:
        query = query.where(CurriculumItem.curriculum_version_id == filters.curriculum_version_id)
    if filters.item_ids is not None:
        query = query.where(ContentUnit.item_id.in_(list(filters.item_ids)))
    if filters.source_ids is not None:
        query = query.where(ContentUnit.source_id.in_(list(filters.source_ids)))
    rows = session.execute(query.order_by(distance, EmbeddingChunk.chunk_id).limit(k * 4)).all()
    out: list[Evidence] = []
    seen: set[str] = set()
    for chunk, unit, source, item, dist in rows:
        score = 1.0 - float(dist)
        key = _norm(chunk.chunk_text or "")[:400]
        if score < min_score or key in seen:
            continue
        seen.add(key)
        out.append(
            Evidence(
                label=f"E{len(out) + 1}",
                chunk_id=chunk.chunk_id,
                content_unit_id=unit.content_unit_id,
                source_id=source.source_id,
                source_sha256=source.sha256,
                pdf_page_index=unit.pdf_page_index,
                printed_page_label=unit.printed_page_label,
                item_id=unit.item_id,
                item_title=item.title if item is not None else None,
                curriculum_version_id=item.curriculum_version_id if item is not None else None,
                content_sha256=unit.content_sha256,
                review_status=unit.review_status,
                embedding_model_id=embedding_model_id,
                index_generation=index_generation,
                score=round(score, 6),
                text=chunk.chunk_text or "",
            )
        )
        if len(out) == k:
            break
    return out


def neutralize(text: str) -> str:
    """Retrieved text is data: defuse instruction-like phrases and delimiter look-alikes."""
    text = text.replace("<<<", "‹‹‹").replace(">>>", "›››").replace("```", "'''")
    return _INJECTION.sub(lambda m: "[removed instruction-like text]", text)


@dataclass(frozen=True)
class Context:
    text: str
    evidence: tuple[Evidence, ...]
    tokens: int
    dropped: tuple[str, ...]


def assemble_context(evidence: Sequence[Evidence], budget_tokens: int) -> Context:
    """Labelled, neutralised evidence blocks in rank order, within `budget_tokens`."""
    parts, kept, dropped, used = [], [], [], 0
    for item in evidence:
        page = item.printed_page_label or (
            str(item.pdf_page_index + 1) if item.pdf_page_index is not None else "?"
        )
        block = (
            f"<<<EVIDENCE {item.label} | source {item.source_id} | page {page}>>>\n"
            f"{neutralize(item.text)}\n<<<END {item.label}>>>"
        )
        cost = estimate_tokens(block)
        if used + cost > budget_tokens:
            dropped.append(item.label)
            continue
        parts.append(block)
        kept.append(item)
        used += cost
    return Context("\n\n".join(parts), tuple(kept), used, tuple(dropped))
