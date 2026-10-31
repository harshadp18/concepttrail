"""Measurable page classification that decides which pages need OCR.

Classes (exactly one per page):

| Class | Rule (checked in this order) | OCR candidate |
|---|---|---|
| `extraction_failed` | the page could not be extracted | no (needs review) |
| `empty_or_non_text` | < MIN_TEXT_CHARS and image coverage < IMAGE_PRESENT_COVERAGE | no |
| `scanned` | < MIN_TEXT_CHARS and image coverage >= SCANNED_COVERAGE | yes |
| `image_heavy` | < MIN_TEXT_CHARS and image coverage >= IMAGE_PRESENT_COVERAGE | yes |
| `low_quality_extraction` | text present but unreliable (see `quality_problems`) | yes |
| `mixed_text_image` | usable text and image coverage >= MIXED_COVERAGE | no |
| `text_native` | usable text, little image coverage | no |

Image coverage alone never means "scanned": these textbooks place full-page artwork behind
real text, so a page is only scanned/image-heavy when native text is also scarce.
"""

from __future__ import annotations

from typing import Any

CLASSIFIER_VERSION = "classify-pages/1.2.0"
MIN_TEXT_CHARS = 40  # mirrors config.yaml extraction.min_text_characters_per_page
IMAGE_PRESENT_COVERAGE = 0.05
SCANNED_COVERAGE = 0.60
MIXED_COVERAGE = 0.30
MAX_UNMAPPED_GLYPH_RATIO = 0.01  # U+FFFD + C0 control codes from fonts lacking ToUnicode
MAX_PRIVATE_USE_RATIO = 0.05
MIN_DEVANAGARI_SHARE = 0.50  # of Devanagari + Latin letters, for Hindi-language sources

OCR_CANDIDATES = frozenset({"scanned", "image_heavy", "low_quality_extraction"})


def quality_problems(page: dict[str, Any], expected_script: str) -> list[str]:
    stats = page["char_stats"]
    total = max(stats["non_whitespace"], 1)
    problems = []
    if (stats["replacement"] + stats["control"]) / total > MAX_UNMAPPED_GLYPH_RATIO:
        problems.append("unmapped_glyph_codes")
    if stats["private_use"] / total > MAX_PRIVATE_USE_RATIO:
        problems.append("private_use_glyphs")
    if expected_script == "devanagari":
        letters = stats["devanagari"] + stats["latin"]
        if letters and stats["devanagari"] / letters < MIN_DEVANAGARI_SHARE:
            problems.append(
                "legacy_devanagari_font_encoding"
                if page.get("legacy_devanagari_font")
                else "devanagari_not_extracted"
            )
    return problems


def review_reasons(page: dict[str, Any], page_class: str, problems: list[str]) -> list[str]:
    reasons = list(problems)
    stats = page.get("char_stats", {})
    if page_class in OCR_CANDIDATES:
        reasons.append(f"ocr_required:{page_class}")
    if stats.get("private_use") and "private_use_glyphs" not in reasons:
        reasons.append("symbol_font_glyphs_may_be_lost")
    if (stats.get("replacement") or stats.get("control")) and "unmapped_glyph_codes" not in reasons:
        reasons.append("some_unmapped_glyph_codes")
    # One-row/one-column detections are layout frames, not tables; only grids need review.
    if any(
        t.get("kind", "data_grid") != "box_or_frame"
        for t in page.get("tables", {}).get("tables", [])
    ):
        reasons.append("table_structure_check")
    if page.get("tables", {}).get("status") == "failed":
        reasons.append("table_detection_failed")
    return reasons


def classify_page(page: dict[str, Any], expected_script: str) -> dict[str, Any]:
    if page.get("extraction_method") == "failed":
        return {
            "class": "extraction_failed",
            "ocr_candidate": False,
            "quality_problems": ["extraction_failed"],
            "review_reasons": ["extraction_failed"],
            "needs_review": True,
        }
    chars, coverage = page["text_length"], page["image_coverage"]
    problems: list[str] = []
    if chars < MIN_TEXT_CHARS:
        if coverage >= SCANNED_COVERAGE:
            page_class = "scanned"
        elif coverage >= IMAGE_PRESENT_COVERAGE:
            page_class = "image_heavy"
        else:
            page_class = "empty_or_non_text"
    else:
        problems = quality_problems(page, expected_script)
        if problems:
            page_class = "low_quality_extraction"
        elif coverage >= MIXED_COVERAGE:
            page_class = "mixed_text_image"
        else:
            page_class = "text_native"
    reasons = review_reasons(page, page_class, problems)
    return {
        "class": page_class,
        "ocr_candidate": page_class in OCR_CANDIDATES,
        "quality_problems": problems,
        "review_reasons": reasons,
        "needs_review": bool(reasons),
        "thresholds": {
            "min_text_chars": MIN_TEXT_CHARS,
            "image_present_coverage": IMAGE_PRESENT_COVERAGE,
            "scanned_coverage": SCANNED_COVERAGE,
            "mixed_coverage": MIXED_COVERAGE,
        },
    }
