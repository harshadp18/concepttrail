"""Choose the extraction pilot from measured PDF signals (numeric only; no text stored).

Candidates are accepted, non-quarantined `chapter_pdf` rows whose bytes match the
inventory SHA-256 and whose local extraction is authorised. Ten slots, two per subject
at different class levels, each chosen by a documented signal (ties: `source_id`):

| Slot | Signal maximised |
|---|---|
| mathematics_equations | (math symbols + superscript spans) per page |
| mathematics_symbol_fonts | private-use glyphs per page (symbol-font risk) |
| science_formulas | (subscript-like spans + formula-like tokens) per page |
| science_tables | detected tables |
| social_science_tables | detected tables |
| social_science_figures | low-text image pages, then captions (maps/figures) |
| english_prose | characters per page (text-native prose) |
| english_layout | detected tables + low-text image pages |
| hindi_unicode | Devanagari matras + conjunct marks per page (Unicode text) |
| hindi_legacy_or_scanned | lowest Devanagari share (legacy font / OCR-needed pages) |

    python -m data_pipeline.select_pilot
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pymupdf

from data_pipeline.authorization import check_use, load_records
from data_pipeline.stages.extract_pdf import (
    CAPTION,
    LEGACY_DEVANAGARI_FONTS,
    char_stats,
    page_images,
)
from data_pipeline.stages.validate_content import FORMULA_WITH_DIGIT
from data_pipeline.stages.validate_csv import check_pdf, parse_local_path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLEANED = PROJECT_ROOT / "resources/teammate_csv/processed/cleaned/curriculum_inventory.cleaned.csv"
QUARANTINED = (
    PROJECT_ROOT / "resources/teammate_csv/processed/rejected/curriculum_inventory.quarantined.csv"
)
PDF_ROOT = PROJECT_ROOT / "resources/textbook_pdfs"
OUTPUT = PROJECT_ROOT / "data_pipeline/data/logs/extraction_pilot/pilot_selection.json"
SELECTION_VERSION = "pilot-selection/1.0.0"
TABLE_SUBJECTS = ("science", "social_science", "english")  # slots that rank by tables

SLOTS: list[tuple[str, str, str]] = [
    ("mathematics_equations", "mathematics", "equation_density"),
    ("mathematics_symbol_fonts", "mathematics", "private_use_per_page"),
    ("science_formulas", "science", "formula_density"),
    ("science_tables", "science", "tables"),
    ("social_science_tables", "social_science", "tables"),
    ("social_science_figures", "social_science", "figure_signal"),
    ("english_prose", "english", "chars_per_page"),
    ("english_layout", "english", "layout_signal"),
    ("hindi_unicode", "hindi", "devanagari_marks_per_page"),
    ("hindi_legacy_or_scanned", "hindi", "inverse_devanagari_share"),
]


def document_signals(path: Path, subject: str) -> dict[str, Any]:
    doc = pymupdf.open(path)
    pages = doc.page_count
    totals: dict[str, float] = dict.fromkeys(
        ["chars", "dev", "lat", "marks", "pua", "math", "sup", "sub", "low_text_image", "captions"],
        0,
    )
    formulas, legacy = 0, False
    for page in doc:
        text = page.get_text()
        stats = char_stats(text)
        totals["chars"] += stats["non_whitespace"]
        totals["dev"] += stats["devanagari"]
        totals["lat"] += stats["latin"]
        totals["marks"] += stats["devanagari_matras"] + stats["virama"]
        totals["pua"] += stats["private_use"]
        totals["math"] += stats["math_symbols"]
        formulas += len(FORMULA_WITH_DIGIT.findall(text))
        _, coverage = page_images(page)
        if stats["non_whitespace"] < 40 and coverage >= 0.05:
            totals["low_text_image"] += 1
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = [s for s in line["spans"] if s["text"].strip()]
                if not spans:
                    continue
                big = max(s["size"] for s in spans)
                base = max(spans, key=lambda s: s["size"])["origin"][1]
                totals["sup"] += sum(1 for s in spans if s["flags"] & 1)
                totals["sub"] += sum(
                    1 for s in spans if s["size"] < 0.8 * big and s["origin"][1] > base + 0.15 * big
                )
                if CAPTION.match("".join(s["text"] for s in spans)):
                    totals["captions"] += 1
        legacy = legacy or any(LEGACY_DEVANAGARI_FONTS.search(f[3]) for f in page.get_fonts())
    doc.close()
    letters = totals["dev"] + totals["lat"]
    per = max(pages, 1)
    return {
        "pages": pages,
        "chars_per_page": round(totals["chars"] / per, 1),
        "devanagari_share": round(totals["dev"] / letters, 3) if letters else None,
        "devanagari_marks_per_page": round(totals["marks"] / per, 1),
        "private_use_per_page": round(totals["pua"] / per, 2),
        "equation_density": round((totals["math"] + totals["sup"]) / per, 2),
        "formula_density": round((totals["sub"] + formulas) / per, 2),
        "superscript_spans": int(totals["sup"]),
        "subscript_like_spans": int(totals["sub"]),
        "low_text_image_pages": int(totals["low_text_image"]),
        "captions": int(totals["captions"]),
        "legacy_devanagari_font": legacy,
        "subject": subject,
    }


def count_tables(path: Path) -> int:
    doc = pymupdf.open(path)
    try:
        return sum(len(page.find_tables().tables) for page in doc)
    finally:
        doc.close()


def score(sig: dict[str, Any], metric: str) -> float:
    if metric == "figure_signal":
        return sig["low_text_image_pages"] * 100 + sig["captions"]
    if metric == "layout_signal":
        return sig.get("tables", 0) * 100 + sig["low_text_image_pages"]
    if metric == "inverse_devanagari_share":
        share = sig["devanagari_share"]
        return 1 - share if share is not None else 0
    return sig.get(metric) or 0


def select(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    for slot, subject, metric in SLOTS:
        used_classes = {c["class_level"] for c in chosen if c["subject_id"] == subject}
        used_ids = {c["source_id"] for c in chosen}
        pool = [
            c
            for c in candidates
            if c["subject_id"] == subject
            and c["source_id"] not in used_ids
            and c["class_level"] not in used_classes
        ]
        if metric == "devanagari_marks_per_page":
            pool = [c for c in pool if (c["signals"]["devanagari_share"] or 0) >= 0.9]
        if not pool:
            chosen.append({"slot": slot, "status": "gap", "reason": "no eligible candidate"})
            continue
        best = max(pool, key=lambda c: (score(c["signals"], metric), c["source_id"]))
        chosen.append(
            {
                **best,
                "slot": slot,
                "status": "selected",
                "selection_metric": metric,
                "selection_value": score(best["signals"], metric),
            }
        )
    return chosen


def main() -> int:
    records = load_records()
    with CLEANED.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    with QUARANTINED.open(encoding="utf-8", newline="") as handle:
        quarantined = {r["inventory_id"] for r in csv.DictReader(handle)}
    candidates, excluded = [], []
    for row in rows:
        if row["item_type"] != "chapter_pdf" or row["inventory_id"] in quarantined:
            continue
        decision = check_use(row["source_id"], row["sha256"], "local_pdf_extraction", records)
        local_path = parse_local_path(row["notes"])
        check = check_pdf(PDF_ROOT, local_path, row["sha256"], {})
        if not decision.permitted or not check.sha256_match:
            excluded.append({"source_id": row["source_id"], "reason": decision.reason})
            continue
        signals = document_signals(PDF_ROOT / str(check.resolved_path), row["subject_id"])
        candidates.append(
            {
                "inventory_id": row["inventory_id"],
                "source_id": row["source_id"],
                "class_level": row["class_level"],
                "subject_id": row["subject_id"],
                "course_or_language": row["course_or_language"],
                "chapter_title": row["chapter_title"],
                "local_path": check.resolved_path,
                "sha256": row["sha256"],
                "signals": signals,
            }
        )
    for c in candidates:
        c["signals"]["tables"] = (
            count_tables(PDF_ROOT / c["local_path"]) if c["subject_id"] in TABLE_SUBJECTS else None
        )
    selection = select(candidates)
    payload = {
        "selection_version": SELECTION_VERSION,
        "candidate_count": len(candidates),
        "excluded": excluded,
        "quarantined_excluded": sorted(quarantined),
        "slots": [{"slot": s, "subject": sub, "metric": m} for s, sub, m in SLOTS],
        "selected": selection,
        "candidate_signals": [
            {k: c[k] for k in ("source_id", "class_level", "subject_id", "signals")}
            for c in sorted(candidates, key=lambda c: c["source_id"])
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for item in selection:
        print(
            json.dumps(
                {
                    k: item.get(k)
                    for k in ("slot", "status", "source_id", "class_level", "selection_value")
                }
            )
        )
    print(f"wrote {OUTPUT.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
