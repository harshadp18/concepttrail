"""Measured extraction-quality metrics per document and subject (no text is reported).

Findings are evidence for human review, not a pass/fail verdict: a reviewer must still
compare representative pages with the original PDF rendering.
"""

from __future__ import annotations

import collections
import re
from typing import Any

QUALITY_VERSION = "content-quality/1.4.0"
# Same dependent vowel sign twice in a row: never valid Hindi spelling.
REPEATED_SIGN = re.compile(r"([\u0901-\u0903\u093e-\u094c])\1")

CHEMICAL_FORMULA = re.compile(r"\b(?:[A-Z][a-z]?\d{0,3}){2,}\b")
FORMULA_WITH_DIGIT = re.compile(r"\b(?=[A-Za-z]*\d)(?:[A-Z][a-z]?\d{0,3}){2,}\b")
UNIT = re.compile(
    r"\b\d+(?:\.\d+)?\s?(?:mm|cm|km|m|mg|kg|g|ml|mL|L|s|min|h|N|J|W|V|A|Pa|Hz|°C|K|mol)\b"
)
SCI_NOTATION = re.compile(r"\d(?:\.\d+)?\s?[×x]\s?10")
YEAR = re.compile(r"\b(?:1[0-9]{3}|20[0-9]{2})\b")
EQUATION_LINE = re.compile(r"=")


def _sum_stats(pages: list[dict[str, Any]]) -> collections.Counter[str]:
    total: collections.Counter[str] = collections.Counter()
    for page in pages:
        total.update(page.get("char_stats", {}))
    return total


def document_quality(
    raw: dict[str, Any], normalized: dict[str, Any], subject: str
) -> dict[str, Any]:
    pages = raw["pages"]
    stats = _sum_stats(pages)
    text = "\n".join(p.get("text", "") for p in pages)
    classes = collections.Counter(p.get("classification", {}).get("class") for p in pages)
    tables = [t for p in pages for t in p.get("tables", {}).get("tables", [])]
    norm_pages = normalized["pages"]
    norm_text = "\n".join(p["text"] for p in norm_pages)
    prose = [para for p in norm_pages for para in p["paragraphs"] if para["kind"] == "prose"]
    letters = stats["devanagari"] + stats["latin"]
    metrics: dict[str, Any] = {
        "pages": len(pages),
        "page_classes": dict(sorted(classes.items())),
        "pages_needing_review": sum(
            1 for p in pages if p.get("classification", {}).get("needs_review")
        ),
        "ocr_candidate_pages": sum(
            1 for p in pages if p.get("classification", {}).get("ocr_candidate")
        ),
        "extraction_failures": sum(1 for p in pages if p.get("extraction_method") == "failed"),
        "labelled_page_share": round(
            sum(1 for p in pages if (p.get("page_label") or {}).get("value")) / len(pages), 3
        ),
        "heading_candidates": sum(len(p.get("heading_candidates", [])) for p in pages),
        "caption_candidates": sum(len(p.get("caption_candidates", [])) for p in pages),
        "list_item_lines": sum(p.get("list_item_lines", 0) for p in pages),
        "tables": len(tables),
        "tables_by_kind": dict(collections.Counter(t.get("kind", "unlabelled") for t in tables)),
        "data_grid_tables": sum(1 for t in tables if t.get("kind") == "data_grid"),
        "table_cells": sum(t["row_count"] * t["col_count"] for t in tables),
        "images": sum(len(p.get("images", [])) for p in pages),
        "prose_paragraphs": len(prose),
        "avg_prose_paragraph_chars": round(sum(len(p["text"]) for p in prose) / len(prose))
        if prose
        else 0,
        "header_footer_lines_removed": sum(
            len(p["removed_header_footer_lines"]) for p in norm_pages
        ),
        "devanagari_share_of_letters": round(stats["devanagari"] / letters, 3) if letters else None,
        "private_use_glyphs": stats["private_use"],
        "replacement_characters": stats["replacement"],
        "superscript_spans": sum(p.get("superscript_spans", 0) for p in pages),
        "subscript_like_spans": sum(p.get("subscript_like_spans", 0) for p in pages),
        "pages_with_script_markup": sum(1 for p in pages if p.get("script_markup_text")),
    }
    if subject == "hindi":
        metrics.update(
            matras=stats["devanagari_matras"],
            virama_conjunct_marks=stats["virama"],
            nukta=stats["nukta"],
            danda=stats["danda"],
            # U+094D U+094D never occurs in correct Hindi; some heading fonts emit it.
            doubled_virama=text.count("\u094d\u094d"),
            doubled_virama_after_normalization=norm_text.count("\u094d\u094d"),
            repeated_vowel_signs_after_normalization=len(REPEATED_SIGN.findall(norm_text)),
            devanagari_repair_corrections=(normalized.get("devanagari_repair") or {}).get(
                "corrections_total", 0
            ),
            legacy_font_pages=sum(1 for p in pages if p.get("legacy_devanagari_font")),
            unusable_text_pages=sum(1 for p in norm_pages if p["text_unusable"]),
            mixed_latin_letters=stats["latin"],
        )
    if subject == "mathematics":
        metrics.update(
            math_symbols=stats["math_symbols"],
            greek=stats["greek"],
            unicode_superscripts=stats["superscript_chars"],
            vulgar_fractions=stats["vulgar_fractions"],
            equation_lines=sum(1 for line in text.splitlines() if EQUATION_LINE.search(line)),
        )
    if subject == "science":
        metrics.update(
            formula_like_tokens=len(FORMULA_WITH_DIGIT.findall(text)),
            unit_expressions=len(UNIT.findall(text)),
            scientific_notation=len(SCI_NOTATION.findall(text)),
            unicode_subscripts=stats["subscript_chars"],
        )
    if subject == "social_science":
        metrics.update(year_tokens=len(YEAR.findall(text)))
    metrics["ocr"] = ocr_metrics(pages)
    metrics["findings"] = findings(metrics, subject)
    return metrics


def ocr_metrics(pages: list[dict[str, Any]]) -> dict[str, Any]:
    """OCR outcome evidence for the document's OCR-candidate pages."""
    done = [p for p in pages if p.get("classification", {}).get("ocr_candidate")]
    results = [p.get("ocr", {}) for p in done]
    with_text = [r for r in results if r.get("word_count")]

    def mean(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 3) if values else None

    return {
        "candidate_pages": [p["page_index"] for p in done],
        "statuses": dict(sorted(collections.Counter(r.get("status") for r in results).items())),
        "mean_confidence": mean(
            [r["mean_confidence"] for r in with_text if r.get("mean_confidence") is not None]
        ),
        "words": sum(r.get("word_count", 0) for r in results),
        "uncertain_word_share": round(
            sum(r.get("uncertain_words", 0) for r in with_text)
            / max(sum(r.get("word_count", 0) for r in with_text), 1),
            3,
        ),
        "native_vs_ocr_similarity": mean(
            [r["native_vs_ocr"]["similarity"] for r in with_text if r.get("native_vs_ocr")]
        ),
        "ocr_devanagari_share": mean(
            [r["devanagari_share"] for r in with_text if r.get("devanagari_share") is not None]
        ),
    }


def findings(m: dict[str, Any], subject: str) -> list[dict[str, str]]:
    out = []

    def add(severity: str, code: str, detail: str) -> None:
        out.append({"severity": severity, "code": code, "detail": detail})

    if m["extraction_failures"]:
        add("high", "PAGE_EXTRACTION_FAILED", f"{m['extraction_failures']} page(s)")
    ocr = m.get("ocr", {})
    pending = sum(n for status, n in ocr.get("statuses", {}).items() if status != "completed")
    weak = sum(
        ocr.get("statuses", {}).get(s, 0)
        for s in ("low_confidence", "no_text_found", "minimal_text")
    )
    done = ocr.get("statuses", {}).get("completed", 0)
    if pending - weak:
        add("high", "OCR_REQUIRED", f"{pending - weak} page(s) still need OCR")
    if weak:
        add("medium", "OCR_LOW_CONFIDENCE_OR_EMPTY", f"{weak} page(s); compare with page images")
    if done:
        add("low", "OCR_COMPLETED_NEEDS_SPOT_CHECK", f"{done} page(s) OCR'd; verify against images")
    if m["superscript_spans"] or m["subscript_like_spans"]:
        add(
            "medium",
            "SCRIPT_POSITION_FLATTENED_IN_PLAIN_TEXT",
            f"{m['superscript_spans']} superscript and {m['subscript_like_spans']} subscript-like"
            " spans; plain text loses position, script_markup_text keeps it",
        )
    if m["private_use_glyphs"]:
        add("medium", "SYMBOL_FONT_GLYPHS", f"{m['private_use_glyphs']} private-use glyphs")
    if m["replacement_characters"]:
        add("medium", "REPLACEMENT_CHARACTERS", f"{m['replacement_characters']} characters")
    if m["data_grid_tables"]:
        add("low", "TABLES_NEED_STRUCTURE_REVIEW", f"{m['data_grid_tables']} data grid(s)")
    if m["tables"] - m["data_grid_tables"]:
        add(
            "low",
            "TABLE_DETECTOR_FALSE_POSITIVES_LIKELY",
            f"{m['tables'] - m['data_grid_tables']} box/sparse detections (frames, layout boxes)",
        )
    if m["labelled_page_share"] < 0.5:
        add("low", "FEW_PRINTED_PAGE_LABELS", f"labelled share {m['labelled_page_share']}")
    if subject == "hindi" and m.get("doubled_virama_after_normalization"):
        add(
            "medium",
            "DEVANAGARI_DOUBLED_VIRAMA",
            f"{m['doubled_virama_after_normalization']} doubled virama sequence(s) in normalised"
            f" text ({m['doubled_virama']} in raw); font extraction artifact",
        )
    if subject == "hindi" and m.get("devanagari_repair_corrections"):
        add(
            "low",
            "DEVANAGARI_DUPLICATES_REPAIRED_D044",
            f"{m['devanagari_repair_corrections']} same-glyph duplicate code points removed in"
            f" normalised text ({m['doubled_virama']} doubled viramas remain in raw text)",
        )
    if subject == "hindi" and m.get("repeated_vowel_signs_after_normalization"):
        add(
            "medium",
            "DEVANAGARI_REPEATED_VOWEL_SIGNS",
            f"{m['repeated_vowel_signs_after_normalization']} repeated vowel sign(s) not covered"
            " by D-044; human review",
        )
    if subject == "hindi" and m.get("unusable_text_pages"):
        add(
            "high",
            "HINDI_LEGACY_FONT_TEXT_UNUSABLE",
            f"{m['unusable_text_pages']} page(s); requires Hindi OCR or font remapping",
        )
    return out
