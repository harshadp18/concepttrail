"""Diagnose doubled virama (U+094D U+094D) in pilot Hindi text. Changes no pipeline text.

Evidence gathered, per affected document/page:

1. Where `््` occurs: raw native text, normalised text and OCR text (separately).
2. Glyph level (PyMuPDF `rawdict`): whether the two virama code points come from the same
   glyph position (one glyph mapped to two code points by the font's ToUnicode table) or
   from two separately drawn marks.
3. Rendered page vs text: diagnostic local OCR (hin+eng) of the page image, i.e. what a
   reader sees. For every native word containing `््`, does OCR read the single-virama form
   or the doubled form? Character similarity of OCR to native text, before and after the
   proposed D-040 collapse, also estimates Tesseract's Hindi accuracy on clean pages.

`preview_d040()` and the glyph-aware preview show what each rule would change; this module
never changes text. D-044 itself is applied by `stages/repair_devanagari.py` (owner-approved);
`applied_repair` reports how the normalised (repaired) text agrees with OCR.

    python -m data_pipeline.hindi_diagnostics
"""

from __future__ import annotations

import collections
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pymupdf

from data_pipeline.authorization import check_use, load_records
from data_pipeline.stages import ocr_pages

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_MANIFEST = PROJECT_ROOT / "data_pipeline/data/logs/extraction_pilot/run_manifest.json"
OUTPUT_JSON = PROJECT_ROOT / "data_pipeline/data/logs/extraction_pilot/hindi_virama_diagnosis.json"
OUTPUT_MD = PROJECT_ROOT / "data_pipeline/data/logs/extraction_pilot/hindi_virama_diagnosis.md"
DIAGNOSTIC_VERSION = "hindi-diagnostics/1.3.0"
DOUBLED = "््"
VIRAMA = "्"
DIAGNOSTIC_OCR_PAGES = 3  # most-affected pages per document; evidence only, not pilot OCR
DPI = 300
WORD = re.compile(r"[ऀ-ॿ]+")
# The same dependent vowel sign / bindu twice in a row: never valid Hindi spelling.
REPEATED_SIGN = re.compile(r"([\u0901-\u0903\u093e-\u094c])\1")


def preview_d040(text: str) -> tuple[str, int]:
    """Proposed rule D-040 (NOT applied): collapse U+094D U+094D to U+094D."""
    count = 0
    while DOUBLED in text:
        count += text.count(DOUBLED)
        text = text.replace(DOUBLED, VIRAMA)
    return text, count


def is_devanagari(ch: str) -> bool:
    return "\u0900" <= ch <= "\u097f"


def same_position_duplicates(
    page: pymupdf.Page, devanagari_only: bool = True
) -> tuple[str, collections.Counter[str]]:
    """Page text with identical consecutive code points at the same glyph origin dropped.

    One glyph emitting the same code point twice is never legitimate text: a real doubled
    letter (e.g. मम in ममता) is two glyphs at different positions, and a real conjunct
    glyph emits *different* code points. Returns (preview text, dropped characters).
    With `devanagari_only` (the proposed scope) Latin text, spaces and digits are never
    touched: English chapters also contain same-position repeats (overprinted bold).
    Diagnostic preview only (candidate revision of D-040); never applied to pipeline text.
    """
    pairs, dropped = line_pairs(page, devanagari_only)
    return "\n".join(after for _, after in pairs), dropped


def line_pairs(
    page: pymupdf.Page, devanagari_only: bool = True
) -> tuple[list[tuple[str, str]], collections.Counter[str]]:
    """(extracted line, de-duplicated line) for every text line; see same_position_duplicates."""
    dropped: collections.Counter[str] = collections.Counter()
    pairs = []
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            out, original = [], []
            for span in line["spans"]:
                previous = None
                for ch in span["chars"]:
                    original.append(ch["c"])
                    if (
                        previous is not None
                        and ch["c"] == previous["c"]
                        and abs(ch["origin"][0] - previous["origin"][0]) < 0.01
                        and (is_devanagari(ch["c"]) or not devanagari_only)
                    ):
                        dropped[ch["c"]] += 1
                        continue
                    out.append(ch["c"])
                    previous = ch
            pairs.append(("".join(original), "".join(out)))
    return pairs, dropped


def glyph_aware_word_pairs(page: pymupdf.Page) -> list[tuple[str, str]]:
    """(extracted word, glyph-aware preview word) for words the proposal would change."""
    changed = []
    for before, after in line_pairs(page)[0]:
        old, new = WORD.findall(before), WORD.findall(after)
        if before != after and len(old) == len(new):
            changed += [(a, b) for a, b in zip(old, new, strict=True) if a != b]
    return changed


def doubled_words(text: str) -> list[str]:
    return [w for w in WORD.findall(text) if DOUBLED in w]


def glyph_diagnosis(page: pymupdf.Page) -> dict[str, Any]:
    """Classify each doubled virama by the positions of its two characters."""
    same_position = distinct = 0
    fonts: collections.Counter[str] = collections.Counter()
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                chars = span["chars"]
                for first, second in zip(chars, chars[1:], strict=False):
                    if first["c"] == VIRAMA and second["c"] == VIRAMA:
                        fonts[span["font"].split("+")[-1]] += 1
                        if abs(first["origin"][0] - second["origin"][0]) < 0.01:
                            same_position += 1
                        else:
                            distinct += 1
    return {
        "same_glyph_position": same_position,
        "distinct_positions": distinct,
        "fonts": dict(fonts),
    }


def similarity(a: str, b: str) -> float:
    a, b = "".join(a.split()), "".join(b.split())
    return round(SequenceMatcher(None, a, b, autojunk=False).ratio(), 4) if a or b else 0.0


def compare_with_ocr(native: str, ocr_text: str) -> dict[str, Any]:
    tokens = set(WORD.findall(ocr_text))
    words = doubled_words(native)
    single_seen = sum(1 for w in words if preview_d040(w)[0] in tokens)
    doubled_seen = sum(1 for w in words if w in tokens)
    collapsed, _ = preview_d040(native)
    return {
        "native_words_with_doubled_virama": len(words),
        "ocr_reads_single_virama_form": single_seen,
        "ocr_reads_doubled_form": doubled_seen,
        "neither_form_in_ocr": len(words) - single_seen - doubled_seen,
        "doubled_virama_in_ocr_text": ocr_text.count(DOUBLED),
        "similarity_ocr_vs_native": similarity(ocr_text, native),
        "similarity_ocr_vs_native_after_d040_preview": similarity(ocr_text, collapsed),
        "examples": [
            {
                "native": w,
                "d040_preview": preview_d040(w)[0],
                "ocr_has_single_form": preview_d040(w)[0] in tokens,
            }
            for w in sorted(set(words))[:6]
        ],
    }


def main() -> int:
    manifest = json.loads(RUN_MANIFEST.read_text(encoding="utf-8"))
    records = load_records()
    env = ocr_pages.detect_tesseract()
    documents = []
    for doc in manifest["documents"]:
        if doc["status"] != "processed":
            continue
        raw = json.loads((PROJECT_ROOT / doc["raw_path"]).read_text(encoding="utf-8"))
        norm = json.loads((PROJECT_ROOT / doc["normalized_path"]).read_text(encoding="utf-8"))
        meta = raw["document"]
        per_page = []
        for page, npage in zip(raw["pages"], norm["pages"], strict=True):
            ocr_text = (page.get("ocr") or {}).get("text") or ""
            counts = {
                "raw_native": page.get("text", "").count(DOUBLED),
                "normalized": npage["text"].count(DOUBLED),
                "pilot_ocr": ocr_text.count(DOUBLED),
            }
            if any(counts.values()):
                per_page.append({"pdf_page_index": page["page_index"], **counts})
        if not per_page:
            documents.append({"source_id": meta["source_id"], "affected_pages": 0})
            continue
        entry: dict[str, Any] = {
            "source_id": meta["source_id"],
            "inventory_id": meta["inventory_id"],
            "pdf_path": meta["pdf_path"],
            "pdf_sha256": meta["pdf_sha256"],
            "affected_pages": len(per_page),
            "pages": per_page,
            "totals": {
                k: sum(p[k] for p in per_page) for k in ("raw_native", "normalized", "pilot_ocr")
            },
        }
        permitted = check_use(meta["source_id"], meta["pdf_sha256"], "local_ocr", records).permitted
        ranked = sorted(per_page, key=lambda p: (-p["raw_native"], p["pdf_page_index"]))
        evidence = []
        with pymupdf.open(PROJECT_ROOT / meta["pdf_path"]) as pdf:
            for item in [p for p in ranked if p["raw_native"]][:DIAGNOSTIC_OCR_PAGES]:
                page = pdf[item["pdf_page_index"]]
                native = raw["pages"][item["pdf_page_index"]]["text"]
                result: dict[str, Any] = {
                    "pdf_page_index": item["pdf_page_index"],
                    "glyphs": glyph_diagnosis(page),
                }
                if permitted:
                    ocr = ocr_pages.ocr_page(
                        page,
                        "devanagari",
                        env,
                        enabled=True,
                        dpi=DPI,
                        approved_languages=["hin", "eng"],
                    )
                    result["diagnostic_ocr"] = {
                        k: ocr.get(k)
                        for k in (
                            "status",
                            "languages",
                            "mean_confidence",
                            "word_count",
                            "engine_version",
                        )
                    }
                    if ocr.get("text"):
                        result["comparison"] = compare_with_ocr(native, ocr["text"])
                        deduped, dropped = same_position_duplicates(page)
                        result["glyph_aware_preview"] = {
                            "dropped_same_position_duplicates": dict(dropped.most_common()),
                            "similarity_ocr_vs_preview": similarity(ocr["text"], deduped),
                            "doubled_virama_left": deduped.count(DOUBLED),
                        }
                        applied = norm["pages"][item["pdf_page_index"]]
                        if applied.get("devanagari_repair"):
                            # The repair actually applied (D-044) in the normalised text.
                            result["applied_repair"] = {
                                "corrections_on_page": applied["devanagari_repair"]["corrections"],
                                "similarity_ocr_vs_normalized": similarity(
                                    ocr["text"], applied["text"]
                                ),
                                "doubled_virama_in_normalized": applied["text"].count(DOUBLED),
                            }
                evidence.append(result)
        entry["evidence_pages"] = evidence
        entry["d040_preview_changes"] = preview_d040(
            "".join(p.get("text", "") for p in raw["pages"])
        )[1]
        documents.append(entry)

    scope = scope_survey(manifest)
    affected = [d for d in documents if d.get("affected_pages")]
    report = {
        "diagnostic_version": DIAGNOSTIC_VERSION,
        "rule_d040_applied": False,
        "documents": documents,
        "proposed_rule_scope_survey": scope,
        "summary": {
            "documents_affected": [d["source_id"] for d in affected],
            "raw_native_total": sum(d["totals"]["raw_native"] for d in affected),
            "normalized_total": sum(d["totals"]["normalized"] for d in affected),
            "pilot_ocr_total": sum(d["totals"]["pilot_ocr"] for d in affected),
        },
    }
    OUTPUT_JSON.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    OUTPUT_MD.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


def scope_survey(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Same-position repeats per pilot document, all scripts vs Devanagari-only scope.

    Counts only (glyph positions from the PDF); no text leaves this module except the
    short before/after word pairs of affected Hindi words recorded as rule evidence.
    """
    out = []
    for doc in manifest["documents"]:
        if doc["status"] != "processed":
            continue
        raw = json.loads((PROJECT_ROOT / doc["raw_path"]).read_text(encoding="utf-8"))
        meta = raw["document"]
        any_script: collections.Counter[str] = collections.Counter()
        scoped: collections.Counter[str] = collections.Counter()
        residual = 0
        word_pairs: dict[str, dict[str, Any]] = {}
        with pymupdf.open(PROJECT_ROOT / meta["pdf_path"]) as pdf:
            for page in pdf:
                any_script.update(same_position_duplicates(page, devanagari_only=False)[1])
                preview, dropped = same_position_duplicates(page)
                scoped.update(dropped)
                residual += len(REPEATED_SIGN.findall(preview))
                for word, fixed in glyph_aware_word_pairs(page):
                    if word not in word_pairs:
                        word_pairs[word] = {
                            "before": word,
                            "after_proposed_rule": fixed,
                            "after_d040": preview_d040(word)[0],
                            "pdf_page_index": page.number,
                        }
        out.append(
            {
                "source_id": meta["source_id"],
                "inventory_id": meta["inventory_id"],
                "same_position_repeats_any_script": sum(any_script.values()),
                "non_devanagari_repeats_excluded_by_scope": sum(
                    n for c, n in any_script.items() if not is_devanagari(c)
                ),
                "devanagari_repeats_dropped_by_proposal": dict(scoped.most_common()),
                "words_changed_by_proposal": len(word_pairs),
                "repeated_vowel_signs_left_after_proposal": residual,
                "words_where_d040_differs": sum(
                    1 for w in word_pairs.values() if w["after_d040"] != w["after_proposed_rule"]
                ),
                "example_word_pairs": sorted(
                    word_pairs.values(), key=lambda w: (w["pdf_page_index"], w["before"])
                )[:12],
            }
        )
    return out


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Hindi doubled-virama diagnosis (pilot)",
        "",
        f"Version `{report['diagnostic_version']}`. Proposed rule D-040 applied: **no**."
        " D-044 is applied to normalised text only (see `applied_repair`).",
        "",
        f"Summary: {json.dumps(report['summary'], ensure_ascii=False)}",
        "",
    ]
    lines += [
        "## Proposed revised rule: scope survey (all pilot documents; not applied)",
        "",
        "| Document | Repeats, any script | Non-Devanagari (excluded) | Devanagari dropped"
        " | Words changed | D-040 alone differs | Repeated signs left |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in report["proposed_rule_scope_survey"]:
        lines.append(
            f"| `{s['source_id']}` | {s['same_position_repeats_any_script']}"
            f" | {s['non_devanagari_repeats_excluded_by_scope']}"
            f" | {sum(s['devanagari_repeats_dropped_by_proposal'].values())}"
            f" | {s['words_changed_by_proposal']} | {s['words_where_d040_differs']}"
            f" | {s['repeated_vowel_signs_left_after_proposal']} |"
        )
    lines.append("")
    for s in report["proposed_rule_scope_survey"]:
        for w in s["example_word_pairs"]:
            lines.append(
                f"- `{s['source_id']}` p{w['pdf_page_index']}: `{w['before']}`"
                f" → proposed `{w['after_proposed_rule']}` (D-040 alone: `{w['after_d040']}`)"
            )
    lines.append("")
    for doc in report["documents"]:
        if not doc.get("affected_pages"):
            continue
        lines += [
            f"## `{doc['source_id']}` ({doc['inventory_id']})",
            "",
            f"- PDF: `{doc['pdf_path']}`",
            f"- Affected pages: {doc['affected_pages']}; totals: {doc['totals']}",
            "",
        ]
        for ev in doc["evidence_pages"]:
            lines.append(f"### PDF page index {ev['pdf_page_index']}")
            lines.append(f"- Glyph positions: {ev['glyphs']}")
            if "diagnostic_ocr" in ev:
                lines.append(f"- Diagnostic OCR: {ev['diagnostic_ocr']}")
            if "glyph_aware_preview" in ev:
                g = ev["glyph_aware_preview"]
                lines.append(
                    f"- Glyph-aware de-duplication preview: similarity to OCR"
                    f" {g['similarity_ocr_vs_preview']};"
                    f" dropped {g['dropped_same_position_duplicates']}"
                )
            if "applied_repair" in ev:
                lines.append(f"- Applied D-044 (normalised text): {ev['applied_repair']}")
            if "comparison" in ev:
                c = ev["comparison"]
                lines.append(
                    f"- Words with `््`: {c['native_words_with_doubled_virama']};"
                    f" OCR reads single form: {c['ocr_reads_single_virama_form']};"
                    f" doubled form: {c['ocr_reads_doubled_form']};"
                    f" `््` in OCR: {c['doubled_virama_in_ocr_text']}"
                )
                lines.append(
                    f"- Similarity OCR↔native: {c['similarity_ocr_vs_native']}"
                    f" → after D-040 preview: {c['similarity_ocr_vs_native_after_d040_preview']}"
                )
                for e in c["examples"]:
                    seen = e["ocr_has_single_form"]
                    lines.append(
                        f"  - `{e['native']}` → `{e['d040_preview']}` (OCR single form: {seen})"
                    )
            lines.append("")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
