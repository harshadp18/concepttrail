"""The AI-assisted page review record: complete coverage, never presented as human review."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

REVIEW = (
    Path(__file__).resolve().parents[2]
    / "data_pipeline/data/overrides/quality_review/ai_assisted_page_review_2026-10-31.csv"
)
pytestmark = pytest.mark.skipif(
    not REVIEW.exists(),
    reason="private AI-assisted review record (gitignored) is not present in this checkout",
)
OCR_PAGES = {
    "SRC-C09-MAT-IEMH1-04": {9, 21},
    "SRC-C10-MAT-JEMH1-02": {9, 11, 12},
    "SRC-C09-SOC-IEST2-06": {22, 23, 24, 27},
    "SRC-C10-HIN-JHSP1-14": set(range(10)),
}
VIRAMA_PAGES = {"SRC-C09-HIN-IHGA1-02": {0, 3, 8}}


def rows() -> list[dict[str, str]]:
    with REVIEW.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_review_covers_all_ocr_and_worst_virama_pages() -> None:
    covered: dict[str, set[int]] = {}
    for row in rows():
        covered.setdefault(row["source_id"], set()).add(int(row["pdf_page_index"]))
    for source, pages in {**OCR_PAGES, **VIRAMA_PAGES}.items():
        assert pages <= covered[source], source
    assert sum(len(p) for p in OCR_PAGES.values()) == 19


def test_review_never_claims_human_review() -> None:
    for row in rows():
        assert row["human_reviewed"] == "false"
        assert row["reviewer"].startswith("ai_assisted:")
        for field in ("accurate_text", "incorrect_text", "specialist_review"):
            assert row[field], (row["source_id"], row["pdf_page_index"], field)
