"""Render representative pilot pages next to their extracted text for human inspection.

For each processed pilot document, pages are chosen from the raw artifact: first content
page, a table page, the most symbol-dense page, a low-quality page, **every** OCR page
(with its OCR text next to the native text) and the three pages with the most doubled
viramas. Across the pilot, the best and worst OCR pages by mean confidence are labelled.
Each page gets `<source>__p<index>.png` (local PyMuPDF render) and `<source>__p<index>.txt`
(classification, OCR summary, raw, script markup, normalised and OCR text).
`decisions.md` summarises the topic and objective decision for each document.

The pack is for the human reviewer; it is written under the Git-ignored logs folder and
is gated by the `local_extraction_quality_evaluation` authorisation.

    python -m data_pipeline.inspection_pack
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pymupdf

from data_pipeline.authorization import check_use, load_records
from data_pipeline.stages.ocr_pages import MIN_MEANINGFUL_WORDS

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_MANIFEST = PROJECT_ROOT / "data_pipeline/data/logs/extraction_pilot/run_manifest.json"
OUTPUT = PROJECT_ROOT / "data_pipeline/data/logs/extraction_pilot/inspection"
DPI = 110
DOUBLED_VIRAMA = "\u094d\u094d"
VIRAMA_PAGES = 3
UNIFIED = PROJECT_ROOT / "data_pipeline/data/processed/metadata_enrichment/unified_enrichment.json"


def choose_pages(raw: dict[str, Any]) -> dict[int, list[str]]:
    pages = raw["pages"]
    picks: dict[int, list[str]] = {}

    def pick(index: int | None, why: str) -> None:
        if index is not None:
            picks.setdefault(index, []).append(why)

    content = [p for p in pages if p.get("text_length", 0) >= 40]
    pick(content[0]["page_index"] if content else None, "first_content_page")
    tables = [p for p in pages if p.get("tables", {}).get("tables")]
    pick(tables[0]["page_index"] if tables else None, "table_page")
    dense = max(
        pages,
        key=lambda p: (
            p.get("char_stats", {}).get("math_symbols", 0) + p.get("superscript_spans", 0)
        ),
        default=None,
    )
    if dense and dense.get("char_stats", {}).get("math_symbols", 0):
        pick(dense["page_index"], "symbol_dense_page")
    for p in pages:
        if p.get("classification", {}).get("ocr_candidate"):
            pick(p["page_index"], f"ocr_page:{(p.get('ocr') or {}).get('status')}")
    low = [p for p in pages if p.get("classification", {}).get("class") == "low_quality_extraction"]
    pick(low[0]["page_index"] if low else None, "low_quality_page")
    virama = sorted(
        (p for p in pages if p.get("text", "").count(DOUBLED_VIRAMA)),
        key=lambda p: (-p["text"].count(DOUBLED_VIRAMA), p["page_index"]),
    )
    for p in virama[:VIRAMA_PAGES]:
        pick(p["page_index"], f"doubled_virama:{p['text'].count(DOUBLED_VIRAMA)}")
    return picks


def ocr_extremes(raws: list[dict[str, Any]]) -> dict[tuple[str, int], str]:
    """Best and worst OCR pages by mean confidence (pages with at least a few words).

    A one-word page can score high confidence, so it is never a "good" example.
    """
    scored = sorted(
        (
            (p["ocr"]["mean_confidence"], r["document"]["source_id"], p["page_index"])
            for r in raws
            for p in r["pages"]
            if (p.get("ocr") or {}).get("word_count", 0) >= MIN_MEANINGFUL_WORDS
            and p["ocr"].get("mean_confidence") is not None
        ),
    )
    labels: dict[tuple[str, int], str] = {}
    for _, sid, index in scored[:2]:
        labels[(sid, index)] = "ocr_example_poor"
    for _, sid, index in scored[-2:]:
        labels[(sid, index)] = "ocr_example_good"
    return labels


def decisions_markdown(unified: list[dict[str, Any]]) -> str:
    lines = [
        "# Topic and objective decisions (pilot)",
        "",
        "| Document | Topic status | Topics | Topic reason | Objective status"
        " | Objective origins | Objective reason |",
        "|---|---|---|---|---|---|---|",
    ]
    for u in unified:
        reasons = u.get("reasons") or {}
        origins = {k: v for k, v in (u.get("objective_counts_by_origin") or {}).items() if v}
        lines.append(
            f"| `{u['source_document_id']}` | {u['topic_value_status']} | {u.get('topic_count')}"
            f" | {reasons.get('topic_title', '')} | {u['objective_value_status']}"
            f" | {origins or '-'} | {reasons.get('learning_objective', '')} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    manifest = json.loads(RUN_MANIFEST.read_text(encoding="utf-8"))
    records = load_records()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for stale in [*OUTPUT.glob("*.png"), *OUTPUT.glob("*.txt")]:
        stale.unlink()  # the pack is regenerated whole; no page from an older selection stays
    index = []
    processed = [d for d in manifest["documents"] if d["status"] == "processed"]
    raws = [
        json.loads((PROJECT_ROOT / d["raw_path"]).read_text(encoding="utf-8")) for d in processed
    ]
    extremes = ocr_extremes(raws)
    for doc, raw in zip(processed, raws, strict=True):
        normalized = json.loads((PROJECT_ROOT / doc["normalized_path"]).read_text(encoding="utf-8"))
        meta = raw["document"]
        decision = check_use(
            meta["source_id"], meta["pdf_sha256"], "local_extraction_quality_evaluation", records
        )
        if not decision.permitted:
            index.append({"source_id": meta["source_id"], "skipped": decision.reason})
            continue
        norm_pages = {p["page_index"]: p for p in normalized["pages"]}
        with pymupdf.open(PROJECT_ROOT / meta["pdf_path"]) as pdf:
            picks = choose_pages(raw)
            for (sid, page_index), label in extremes.items():
                if sid == meta["source_id"]:
                    picks.setdefault(page_index, []).append(label)
            for page_index, reasons in sorted(picks.items()):
                stem = f"{meta['source_id']}__p{page_index:03d}"
                pdf[page_index].get_pixmap(dpi=DPI).save(OUTPUT / f"{stem}.png")
                page = raw["pages"][page_index]
                ocr = page.get("ocr") or {}
                ocr_summary = {k: v for k, v in ocr.items() if k not in ("text", "paragraphs")}
                (OUTPUT / f"{stem}.txt").write_text(
                    "\n".join(
                        [
                            f"source_id: {meta['source_id']}  pdf_page_index: {page_index}"
                            f"  printed_label: {(page.get('page_label') or {}).get('value')}",
                            f"why selected: {', '.join(reasons)}",
                            f"classification: {json.dumps(page.get('classification'))}",
                            f"ocr: {json.dumps(ocr_summary)}",
                            "",
                            "===== RAW TEXT =====",
                            page.get("text", ""),
                            "===== SCRIPT MARKUP (^{sup} _{sub}) =====",
                            page.get("script_markup_text") or "(none)",
                            "===== NORMALISED TEXT =====",
                            norm_pages[page_index]["text"],
                            "===== OCR TEXT (local Tesseract; untrusted until checked) =====",
                            ocr.get("text") or "(no OCR for this page)",
                        ]
                    ),
                    encoding="utf-8",
                )
                index.append(
                    {"source_id": meta["source_id"], "page_index": page_index, "why": reasons}
                )
    (OUTPUT / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    unified = json.loads(UNIFIED.read_text(encoding="utf-8"))
    (OUTPUT / "decisions.md").write_text(decisions_markdown(unified), encoding="utf-8")
    rendered = sum(1 for i in index if "page_index" in i)
    print(f"{rendered} pages rendered to {OUTPUT.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
