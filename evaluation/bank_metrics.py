"""Automated, read-only measurements over the stored question bank and retrieval index.

These are PROPERTIES and PROXIES of stored content (counts, rule checks, regex and similarity
screens). None of them says a question is correct, unambiguous or well-aligned: that needs the
independent review in `evaluation.review`. Every rate is reported with its denominator and a 95%
interval, and a breakdown cell with fewer than `stats.MIN_STRATUM` items is `insufficient_data`.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    ContentUnit,
    CurriculumItem,
    CurriculumVersion,
    EmbeddingChunk,
    KnowledgeComponent,
    Question,
    QuestionKc,
    QuestionOption,
    SourceDocument,
)
from app.services.attempt_service import is_deliverable
from data_pipeline.demo_content.assemble import _PASSAGE_DEPENDENT, near_duplicate
from evaluation.stats import rate

DIMENSIONS = ("class_level", "subject_id", "chapter", "language", "item_type")
_DEVANAGARI = re.compile("[ऀ-ॿ]")


def chi_square_uniform_p(counts: list[int]) -> float | None:
    """p-value of a chi-square test of equal frequencies (survival function, df = k - 1)."""
    k, n = len(counts), sum(counts)
    if k < 2 or n == 0:
        return None
    expected = n / k
    x = sum((c - expected) ** 2 / expected for c in counts)
    df = k - 1
    if df == 3:
        return round(math.erfc(math.sqrt(x / 2)) + math.sqrt(2 * x / math.pi) * math.exp(-x / 2), 6)
    if df == 1:
        return round(math.erfc(math.sqrt(x / 2)), 6)
    return None


def question_rows(session: Session) -> list[dict[str, Any]]:
    kc_of: dict[str, list[str]] = defaultdict(list)
    for question_id, kc_id in session.execute(select(QuestionKc.question_id, QuestionKc.kc_id)):
        kc_of[question_id].append(kc_id)
    options: dict[str, list[QuestionOption]] = defaultdict(list)
    for option in session.scalars(select(QuestionOption)):
        options[option.question_id].append(option)
    pages = {(u.source_id, u.pdf_page_index) for u in session.scalars(select(ContentUnit))}
    sources = {s.source_id: (s.sha256 or "") for s in session.scalars(select(SourceDocument))}
    titles = {i.item_id: i.title for i in session.scalars(select(CurriculumItem))}
    rows = []
    for q in session.scalars(select(Question).order_by(Question.question_id)):
        prov = (q.verification or {}).get("provenance") or {}
        verification = q.verification or {}
        opts = sorted(options[q.question_id], key=lambda o: o.option_key)
        correct = [o for o in opts if o.is_correct]
        longest = max((len(o.option_text) for o in opts), default=0)
        refs = q.source_refs or []
        item_id = prov.get("curriculum_item_id")
        rows.append(
            {
                "question_id": q.question_id,
                "item_type": q.item_type,
                "class_level": prov.get("class_level"),
                "subject_id": prov.get("subject_id"),
                "language": prov.get("language"),
                "chapter": item_id,
                "chapter_title": titles.get(item_id),
                "kc_ids": kc_of[q.question_id],
                "review_status": q.review_status,
                "origin": prov.get("origin"),
                "prompt_version": prov.get("prompt_version"),
                "reviews": len(verification.get("reviews") or []),
                "human_reviewed": bool(verification.get("human_reviewed")),
                "deliverable": is_deliverable(q, opts),
                "stem": q.stem or "",
                "n_options": len(opts),
                "correct_key": correct[0].option_key if len(correct) == 1 else None,
                "correct_is_longest": bool(correct and len(correct[0].option_text) >= longest),
                "options_with_explanation": sum(bool((o.explanation or "").strip()) for o in opts),
                "passage_dependent": bool(_PASSAGE_DEPENDENT.search(q.stem or "")),
                "refs": len(refs),
                "refs_page_exists": sum(
                    (r.get("source_id"), r.get("pdf_page_index")) in pages for r in refs
                ),
                "refs_sha_matches": sum(
                    bool(r.get("sha256"))
                    and sources.get(r.get("source_id"), "").startswith(r["sha256"])
                    for r in refs
                ),
            }
        )
    return rows


def breakdown(
    rows: Iterable[dict],
    predicate: Callable[[dict], bool],
    where: Callable[[dict], bool] = lambda r: True,
) -> dict:
    """Rate of `predicate` among rows where `where`, overall and by every dimension."""
    selected = [r for r in rows if where(r)]
    out: dict[str, Any] = {"overall": rate(sum(predicate(r) for r in selected), len(selected))}
    for dim in DIMENSIONS:
        cells: dict[str, list[dict]] = defaultdict(list)
        for r in selected:
            cells[str(r.get(dim))].append(r)
        out[dim] = {
            key: rate(sum(predicate(r) for r in group), len(group))
            for key, group in sorted(cells.items())
        }
    return out


def question_bank_report(rows: list[dict]) -> dict:
    single = [r for r in rows if r["item_type"] == "single_choice" and r["correct_key"]]
    positions = Counter(r["correct_key"] for r in single)
    letters = sorted({k for r in single for k in "ABCD"})
    counts = [positions.get(k, 0) for k in letters]
    by_kc: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        for kc in r["kc_ids"]:
            by_kc[kc].append(r)
    duplicate_pairs = 0
    in_duplicate = set()
    for group in by_kc.values():
        for i, a in enumerate(group):
            for b in group[i + 1 :]:
                if near_duplicate(a["stem"], [b["stem"]]):
                    duplicate_pairs += 1
                    in_duplicate |= {a["question_id"], b["question_id"]}
    refs = [r for r in rows if r["refs"]]
    options_total = sum(r["n_options"] for r in rows if r["n_options"])
    return {
        "questions": len(rows),
        "by_status": dict(Counter(r["review_status"] for r in rows)),
        "by_origin": dict(Counter(r["origin"] for r in rows)),
        "by_item_type": dict(Counter(r["item_type"] for r in rows)),
        "by_language": dict(Counter(r["language"] for r in rows)),
        "by_class_subject": {
            f"{c}/{s}": n
            for (c, s), n in sorted(
                Counter((r["class_level"], r["subject_id"]) for r in rows).items()
            )
        },
        "questions.review_status": {
            "with_recorded_human_review": rate(sum(r["reviews"] > 0 for r in rows), len(rows), 1),
            "marked_human_reviewed": rate(sum(r["human_reviewed"] for r in rows), len(rows), 1),
            "note": "any value above 0/N must be traceable to a real reviewer record",
        },
        "questions.structure": {
            "servable_by_deterministic_rules": breakdown(rows, lambda r: r["deliverable"]),
            "note": "rule conformance only; says nothing about whether the key is right",
        },
        "questions.key_position_bias": {
            "single_choice_correct_key_counts": dict(sorted(positions.items())),
            "uniform_chi_square_p": chi_square_uniform_p(counts),
            "note": "learner-facing order is shuffled per learner; this is the STORED key",
        },
        "questions.longest_correct_cue": {
            "single_choice": breakdown(single, lambda r: r["correct_is_longest"]),
            "chance_level_note": "with 4 similar-length options about 25% would be expected",
        },
        "questions.passage_dependence": {
            "regex_flagged": breakdown(rows, lambda r: r["passage_dependent"]),
            "note": "regex screen only; unlabelled passage dependence is not detected",
        },
        "questions.near_duplicates": {
            "pairs_within_same_kc": duplicate_pairs,
            "questions_in_a_pair": rate(len(in_duplicate), len(rows), 1),
        },
        "questions.option_explanations": {
            "options_with_explanation": rate(
                sum(r["options_with_explanation"] for r in rows), options_total, 1
            ),
            "questions_with_all_options_explained": breakdown(
                [r for r in rows if r["n_options"]],
                lambda r: r["options_with_explanation"] == r["n_options"],
            ),
        },
        "questions.source_page_resolvable": {
            "questions_with_a_source_ref": rate(len(refs), len(rows), 1),
            "all_refs_resolve_to_a_stored_page": breakdown(
                refs, lambda r: r["refs_page_exists"] == r["refs"]
            ),
            "all_refs_match_source_hash": breakdown(
                refs, lambda r: r["refs_sha_matches"] == r["refs"]
            ),
            "note": "existence only: it does not show the page supports the question",
        },
    }


def kc_coverage_report(session: Session, rows: list[dict]) -> dict:
    per_kc = Counter(kc for r in rows for kc in r["kc_ids"])
    kcs = list(session.scalars(select(KnowledgeComponent)))
    sizes = [per_kc.get(k.kc_id, 0) for k in kcs]
    return {
        "knowledge_components": len(kcs),
        "questions_per_kc": dict(sorted(Counter(sizes).items())),
        "kcs_with_zero_questions": sorted(k.kc_id for k in kcs if per_kc.get(k.kc_id, 0) == 0),
        "kcs_with_at_least_3": rate(sum(s >= 3 for s in sizes), len(sizes), 1),
        "by_subject": {
            s: {"kcs": sum(1 for k in kcs if k.subject_id == s)}
            for s in sorted({k.subject_id for k in kcs})
        },
    }


def index_integrity_report(session: Session) -> dict:
    """Chunk provenance: every chunk resolves to a unit, a hashed source and a real page."""
    query = (
        select(EmbeddingChunk, ContentUnit, SourceDocument, CurriculumVersion.class_level)
        .outerjoin(ContentUnit, ContentUnit.content_unit_id == EmbeddingChunk.content_unit_id)
        .outerjoin(SourceDocument, SourceDocument.source_id == ContentUnit.source_id)
        .outerjoin(CurriculumItem, CurriculumItem.item_id == ContentUnit.item_id)
        .outerjoin(
            CurriculumVersion,
            CurriculumVersion.curriculum_version_id == CurriculumItem.curriculum_version_id,
        )
    )
    rows = []
    for chunk, unit, source, level in session.execute(query):
        text = chunk.chunk_text or ""
        devanagari = len(_DEVANAGARI.findall(text))
        rows.append(
            {
                "resolves": unit is not None and source is not None,
                "has_page": unit is not None and unit.pdf_page_index is not None,
                "source_hashed": bool(source and source.sha256),
                "indexing_permitted": bool(
                    source and "indexing_retrieval" in (source.permitted_uses or [])
                ),
                "has_vector": chunk.embedding is not None,
                "nonempty": bool(text.strip()) and (chunk.token_count or 0) > 0,
                "class_level": level,
                "subject_id": source.subject_id if source else None,
                "language": "hi" if devanagari > 0.3 * max(1, len(text)) else "en",
                "item_type": "chunk",
                "chapter": unit.item_id if unit else None,
                "model": chunk.embedding_model_id,
                "generation": chunk.index_generation,
                "dims": len(chunk.embedding) if chunk.embedding is not None else None,
            }
        )
    checks = {
        "resolves_to_unit_and_source": "resolves",
        "has_pdf_page_index": "has_page",
        "source_has_sha256": "source_hashed",
        "indexing_permitted_in_record": "indexing_permitted",
        "has_vector": "has_vector",
        "nonempty_text_and_tokens": "nonempty",
    }
    units = list(session.scalars(select(ContentUnit)))
    chunked = {c for (c,) in session.execute(select(EmbeddingChunk.content_unit_id))}
    return {
        "chunks": len(rows),
        "models": dict(Counter(r["model"] for r in rows)),
        "generations": dict(Counter(r["generation"] for r in rows)),
        "dimensions": dict(Counter(r["dims"] for r in rows)),
        "checks": {
            name: breakdown(rows, lambda r, key=key: r[key]) for name, key in checks.items()
        },
        "content_units": len(units),
        "units_without_chunks": dict(
            Counter(u.extraction_status for u in units if u.content_unit_id not in chunked)
        ),
        "note": "provenance integrity only; it says nothing about retrieval relevance",
    }
