"""Normalise raw page extraction into reviewable paragraphs (raw records are never edited).

Transformations, each recorded per page:

- `HEADER_FOOTER_REMOVED`: a page's own first or last line, when that line repeats
  (digits ignored) as a first/last line on at least HEADER_FOOTER_MIN_SHARE of the
  document's pages, or is the page's detected printed page number. Body lines are never
  removed, even if they look like a pattern (e.g. a lone equation number).
- `PROSE_LINES_JOINED`: lines of a prose block are joined with single spaces. A line
  ending in "-" is joined without a space and the hyphen is kept, so no characters are
  lost.
- `PROSE_SPACES_COLLAPSED`: runs of spaces/tabs inside prose blocks become one space.
- `LINE_ENDINGS_NORMALIZED`: CR/CRLF become LF.

Never changed: maths/symbol-dense blocks, table regions, Unicode normalisation form
(Devanagari is preserved exactly), punctuation, capitalisation. Pages whose raw text is
legacy-font Devanagari are passed through unchanged and flagged `text_unusable`.
"""

from __future__ import annotations

import collections
import hashlib
import re
from typing import Any

NORMALIZER_VERSION = "normalize-text/1.2.0"
HEADER_FOOTER_MIN_SHARE = 0.4
HEADER_FOOTER_MIN_PAGES = 3
PROSE_MIN_AVG_LINE = 25
PROSE_MAX_SYMBOL_SHARE = 0.03
SYMBOLS = re.compile(r"[=+×÷−±√∞≤≥≠≈∑∫∠△°^_/\\|<>{}\[\]]|\d")
DIGITS = re.compile(r"[0-9०-९]+")
PAGE_NUMBER = re.compile(r"^\s*(?:\d{1,3}|[०-९]{1,3})\s*$")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _edge_lines(page: dict[str, Any]) -> list[str]:
    blocks = sorted(
        (b for b in page.get("blocks", []) if b["type"] == "text" and b["text"].strip()),
        key=lambda b: (b["bbox"][1], b["bbox"][0]),
    )
    if not blocks:
        return []
    first = blocks[0]["text"].strip().splitlines()[0]
    last = blocks[-1]["text"].strip().splitlines()[-1]
    return list(dict.fromkeys([first.strip(), last.strip()]))


def header_footer_patterns(pages: list[dict[str, Any]]) -> set[str]:
    """Digit-insensitive first/last lines repeated across many pages of one document."""
    counts = collections.Counter(
        DIGITS.sub("#", line) for page in pages for line in _edge_lines(page) if line
    )
    threshold = max(HEADER_FOOTER_MIN_PAGES, HEADER_FOOTER_MIN_SHARE * len(pages))
    return {pattern for pattern, n in counts.items() if n >= threshold}


def _is_prose(lines: list[str]) -> bool:
    joined = "".join(lines)
    if len(lines) < 2 or not joined:
        return False
    avg = sum(len(line) for line in lines) / len(lines)
    symbol_share = len(SYMBOLS.findall(joined)) / len(joined)
    return avg >= PROSE_MIN_AVG_LINE and symbol_share <= PROSE_MAX_SYMBOL_SHARE


def _inside(bbox: list[float], regions: list[list[float]]) -> bool:
    x0, y0, x1, y1 = bbox
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return any(r[0] <= cx <= r[2] and r[1] <= cy <= r[3] for r in regions)


def join_prose(lines: list[str]) -> str:
    out = ""
    for line in lines:
        line = re.sub(r"[ \t]+", " ", line.strip())
        if not out:
            out = line
        elif out.endswith("-"):
            out += line  # keep the hyphen; never delete characters
        else:
            out += " " + line
    return out


def _ocr_summary(ocr: dict[str, Any]) -> dict[str, Any] | None:
    if not ocr or ocr.get("status") == "not_required":
        return None
    text = ocr.get("text") or ""
    return {
        "status": ocr.get("status"),
        "languages": ocr.get("languages"),
        "mean_confidence": ocr.get("mean_confidence"),
        "word_count": ocr.get("word_count"),
        "uncertain_words": ocr.get("uncertain_words"),
        "text": text,
        "text_sha256": _sha(text),
        "paragraphs": [p.strip() for p in text.split("\n\n") if p.strip()],
    }


def normalize_page(
    page: dict[str, Any], patterns: set[str], *, text_unusable: bool, raw_artifact: str
) -> dict[str, Any]:
    raw_text = page.get("text", "")
    transforms: collections.Counter[str] = collections.Counter()
    removed: list[str] = []
    paragraphs: list[dict[str, Any]] = []
    table_regions = [t["bbox"] for t in page.get("tables", {}).get("tables", [])]
    edges = set(_edge_lines(page))
    label = (page.get("page_label") or {}).get("value")
    blocks = sorted(
        (b for b in page.get("blocks", []) if b["type"] == "text" and b["text"].strip()),
        key=lambda b: (b["bbox"][1], b["bbox"][0]),
    )
    for block in blocks:
        text = block["text"]
        if "\r" in text:
            text = text.replace("\r\n", "\n").replace("\r", "\n")
            transforms["LINE_ENDINGS_NORMALIZED"] += 1
        lines = [line for line in text.split("\n") if line.strip()]
        kept = []
        for line in lines:
            stripped = line.strip()
            is_page_number = PAGE_NUMBER.match(stripped) and stripped == label
            if stripped in edges and (DIGITS.sub("#", stripped) in patterns or is_page_number):
                removed.append(stripped)
                transforms["HEADER_FOOTER_REMOVED"] += 1
            else:
                kept.append(line)
        if not kept:
            continue
        if _inside(block["bbox"], table_regions):
            kind, out = "table_region", "\n".join(kept)
        elif text_unusable:
            kind, out = "unusable_legacy_encoding", "\n".join(kept)
        elif _is_prose(kept):
            kind, out = "prose", join_prose(kept)
            transforms["PROSE_LINES_JOINED"] += 1
            if any(re.search(r"[ \t]{2,}", line.strip()) for line in kept):
                transforms["PROSE_SPACES_COLLAPSED"] += 1
        else:
            kind, out = "preserved_layout", "\n".join(kept)
        paragraphs.append({"kind": kind, "bbox": block["bbox"], "text": out})
    text = "\n\n".join(p["text"] for p in paragraphs)
    return {
        "page_index": page["page_index"],
        "page_label": page.get("page_label"),
        "raw_ref": {
            "artifact": raw_artifact,
            "page_index": page["page_index"],
            "raw_text_sha256": _sha(raw_text),
        },
        "paragraphs": paragraphs,
        "text": text,
        "text_sha256": _sha(text),
        "removed_header_footer_lines": removed,
        "transforms": dict(sorted(transforms.items())),
        "text_unusable": text_unusable,
        "classification": page.get("classification", {}).get("class"),
        "extraction_method": page.get("extraction_method"),
        "ocr_status": page.get("ocr", {}).get("status"),
        # OCR is kept beside, never instead of, the native text.
        "ocr": _ocr_summary(page.get("ocr", {})),
        "review_status": "needs_review"
        if page.get("classification", {}).get("needs_review") or text_unusable
        else "pending",
    }


def normalize_document(raw: dict[str, Any], raw_artifact: str) -> dict[str, Any]:
    pages = raw["pages"]
    patterns = header_footer_patterns(pages)
    normalized = []
    for page in pages:
        problems = page.get("classification", {}).get("quality_problems", [])
        unusable = "legacy_devanagari_font_encoding" in problems or (
            "devanagari_not_extracted" in problems
        )
        normalized.append(
            normalize_page(page, patterns, text_unusable=unusable, raw_artifact=raw_artifact)
        )
    return {
        "normalizer_version": NORMALIZER_VERSION,
        "header_footer_patterns": sorted(patterns),
        "pages": normalized,
    }
