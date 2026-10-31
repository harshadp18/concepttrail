"""Local, page-aware PDF extraction with PyMuPDF (raw stage; nothing is normalised here).

One record per page keeps the zero-based PDF page index, any printed page label, the raw
text exactly as PyMuPDF returns it, text blocks with bounding boxes, heading/caption/list
candidates, images, tables, fonts and character statistics. Pages are never concatenated.
Heading, caption and table detections are candidates for review, not facts.
"""

from __future__ import annotations

import re
import statistics
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf

EXTRACTOR_VERSION = "extract-pdf/1.3.0"

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
DEVANAGARI_MATRAS = re.compile(r"[ा-ौॢॣ]")
LATIN = re.compile(r"[A-Za-z]")
PRIVATE_USE = re.compile(r"[-]")
GREEK = re.compile(r"[Ͱ-Ͽ]")
MATH_SYMBOLS = re.compile(r"[=+×÷−±√∞≤≥≠≈∑∫∠△°′″∝∴∵⊥∥%<>]")
SUPERSCRIPT_DIGITS = re.compile(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]")
SUBSCRIPT_DIGITS = re.compile(r"[₀₁₂₃₄₅₆₇₈₉]")
VULGAR_FRACTIONS = re.compile(r"[½⅓⅔¼¾⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞]")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
CAPTION = re.compile(
    r"^\s*(?:fig(?:ure)?\.?|table|map|activity|चित्र|तालिका|मानचित्र|गतिविधि)\s*[\d.()-]*",
    re.IGNORECASE,
)
LIST_ITEM = re.compile(r"^\s*(?:[•●▪◦‣\-–]\s|\(?[ivx]{1,4}\)\s|\(?[a-h]\)\s|\d{1,2}[.)]\s)")
# "2.1 Introduction" and also "2.1Introduction" (no space before a capital/Devanagari letter).
NUMBERED_HEADING = re.compile(
    r"^\s*(?P<number>\d{1,2}(?:\.\d{1,2}){1,3})\.?(?:\s+\S|(?=[A-Z\u0900-\u097F]))"
)
PAGE_NUMBER = re.compile(r"^\s*(?:\d{1,3}|[०-९]{1,3})\s*$")
# Legacy (non-Unicode) Devanagari fonts: their glyphs extract as Latin/ASCII garbage.
LEGACY_DEVANAGARI_FONTS = re.compile(r"chanakya|kruti|devlys|shree[-_ ]?dev|akruti|shivaji", re.I)

SUPERSCRIPT_FLAG = 1
BOLD_FLAG = 16
MARGIN_FRACTION = 0.08


class ExtractionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class OpenedPdf:
    document: pymupdf.Document
    metadata: dict[str, Any]


def open_pdf(path: Path) -> OpenedPdf:
    """Open read-only; missing, corrupt and password-protected files raise ExtractionError."""
    if not path.is_file():
        raise ExtractionError("PDF_NOT_FOUND", "file does not exist")
    try:
        document = pymupdf.open(path, filetype="pdf")
    except Exception as exc:  # PyMuPDF raises several types for damaged files
        raise ExtractionError("PDF_OPEN_FAILED", f"cannot open PDF: {type(exc).__name__}") from None
    if document.needs_pass:
        document.close()
        raise ExtractionError("PDF_ENCRYPTED", "PDF requires a password")
    if document.page_count == 0:
        document.close()
        raise ExtractionError("PDF_NO_PAGES", "PDF has no pages")
    raw_meta = document.metadata or {}
    labels = document.get_page_labels()
    metadata = {
        "page_count": document.page_count,
        "pdf_format": raw_meta.get("format", ""),
        "title": raw_meta.get("title", ""),
        "author": raw_meta.get("author", ""),
        "subject": raw_meta.get("subject", ""),
        "creator": raw_meta.get("creator", ""),
        "producer": raw_meta.get("producer", ""),
        "creation_date": raw_meta.get("creationDate", ""),
        "modification_date": raw_meta.get("modDate", ""),
        "is_encrypted": bool(document.is_encrypted),
        "needs_password": False,
        "has_page_label_rules": bool(labels),
        "toc": [[level, title, page - 1] for level, title, page in document.get_toc()],
        "embedded_file_count": document.embfile_count(),
        "note": "PDF metadata is descriptive only; curriculum identity comes from the inventory",
    }
    return OpenedPdf(document, metadata)


def char_stats(text: str) -> dict[str, int]:
    return {
        "non_whitespace": len(re.sub(r"\s", "", text)),
        "devanagari": len(DEVANAGARI.findall(text)),
        "devanagari_matras": len(DEVANAGARI_MATRAS.findall(text)),
        "virama": text.count("्"),
        "nukta": text.count("़"),
        "danda": text.count("।") + text.count("॥"),
        "latin": len(LATIN.findall(text)),
        "digits": sum(ch.isdigit() for ch in text),
        "greek": len(GREEK.findall(text)),
        "math_symbols": len(MATH_SYMBOLS.findall(text)),
        "superscript_chars": len(SUPERSCRIPT_DIGITS.findall(text)),
        "subscript_chars": len(SUBSCRIPT_DIGITS.findall(text)),
        "vulgar_fractions": len(VULGAR_FRACTIONS.findall(text)),
        "private_use": len(PRIVATE_USE.findall(text)),
        "replacement": text.count("�"),
        "control": len(CONTROL.findall(text)),
        "not_nfc": int(unicodedata.normalize("NFC", text) != text),
    }


def _is_subscript(span: dict[str, Any], line_size: float, baseline_y: float) -> bool:
    """A noticeably smaller span sitting below the line's main baseline."""
    return span["size"] < 0.8 * line_size and span["origin"][1] > baseline_y + 0.15 * line_size


def _lines(page_dict: dict[str, Any]) -> list[dict[str, Any]]:
    """Text lines with their largest span size, bold flag and script-position signals."""
    lines = []
    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            sizes = [s["size"] for s in spans]
            max_size = max(sizes)
            superscripts = sum(1 for s in spans if s["flags"] & SUPERSCRIPT_FLAG)
            # Smaller spans sitting below the line's main baseline are subscript-like.
            main_y = max(spans, key=lambda s: s["size"])["origin"][1]

            subscripts = sum(1 for s in spans if _is_subscript(s, max_size, main_y))
            # Explicit ^{...}/_{...} markup keeps exponents and subscripts that plain text
            # flattens (x² -> "x2", H₂O -> "H2O"). Raw text itself is left untouched.
            markup = "".join(
                f"^{{{s['text']}}}"
                if s["flags"] & SUPERSCRIPT_FLAG
                else f"_{{{s['text']}}}"
                if _is_subscript(s, max_size, main_y)
                else s["text"]
                for s in spans
            ).strip()
            lines.append(
                {
                    "text": "".join(s["text"] for s in spans).strip(),
                    "size": round(max_size, 2),
                    "bold": any(s["flags"] & BOLD_FLAG for s in spans)
                    or any("bold" in s["font"].lower() for s in spans),
                    "bbox": [round(v, 2) for v in line["bbox"]],
                    "block_no": block.get("number"),
                    "superscript_spans": superscripts,
                    "subscript_like_spans": subscripts,
                    "markup": markup,
                    "chars": sum(len(s["text"]) for s in spans),
                }
            )
    return lines


def body_font_size(lines: list[dict[str, Any]]) -> float:
    weighted = [line["size"] for line in lines for _ in range(min(line["chars"], 200))]
    return round(statistics.median(weighted), 2) if weighted else 0.0


HEADING_MAX_CHARS = 120


def _continues(previous: dict[str, Any], line: dict[str, Any]) -> bool:
    """A wrapped heading line: same block, same size and weight, directly below."""
    gap = line["bbox"][1] - previous["bbox"][3]
    return (
        previous["block_no"] == line["block_no"]
        and abs(previous["size"] - line["size"]) < 0.2
        and previous["bold"] == line["bold"]
        and -0.5 * line["size"] <= gap <= 0.6 * line["size"]
        and not NUMBERED_HEADING.match(line["text"])
    )


def _overlap_join(left: str, right: str) -> str:
    for k in range(min(len(left), len(right)), 0, -1):
        if left.endswith(right[:k]):
            return left + right[k:]
    return left + right


def merge_layered_fragments(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reassemble text drawn as stacked, horizontally overlapping layers on one baseline.

    Styled headings are sometimes painted several times (shadow/outline effects) and come
    back as overlapping fragments ("1.1 CHEMIC", "AL EQUA", "TIONS"). Distinct text on one
    baseline never overlaps horizontally, so overlapping fragments in the same block, size
    and baseline are joined by suffix/prefix overlap. Used for heading candidates only;
    raw page text is left exactly as extracted.
    """
    out: list[dict[str, Any]] = []
    for line in lines:
        last = out[-1] if out else None
        if (
            last is not None
            and last["block_no"] == line["block_no"]
            and abs(last["size"] - line["size"]) < 0.2
            and abs(last["bbox"][1] - line["bbox"][1]) < 0.3 * line["size"]
            and line["bbox"][0] < last["bbox"][2] - 0.5  # horizontal overlap
        ):
            texts = sorted([(last["bbox"][0], last["text"]), (line["bbox"][0], line["text"])])
            last["text"] = _overlap_join(texts[0][1], texts[1][1])
            last["bbox"] = [
                min(last["bbox"][0], line["bbox"][0]),
                last["bbox"][1],
                max(last["bbox"][2], line["bbox"][2]),
                last["bbox"][3],
            ]
            last["layers_merged"] = last.get("layers_merged", 1) + 1
            continue
        out.append(dict(line))
    return out


def heading_candidates(lines: list[dict[str, Any]], body_size: float) -> list[dict[str, Any]]:
    """Heading-styled lines; wrapped heading lines are joined, long runs are dropped.

    Joining matters both ways: "4.3 Factorisation ... Using" is completed by its second
    line, and large-font *prose* (e.g. a story set in big type) merges into a long run
    that exceeds HEADING_MAX_CHARS and is therefore not proposed as a heading.
    """
    styled = []
    for line in merge_layered_fragments(lines):
        numbered = NUMBERED_HEADING.match(line["text"])
        larger = bool(body_size) and line["size"] >= 1.2 * body_size
        bold_short = line["bold"] and bool(body_size) and line["size"] >= body_size
        if larger or numbered or bold_short:
            styled.append({**line, "larger": larger, "numbered": numbered})
    merged: list[dict[str, Any]] = []
    for line in styled:
        if merged and _continues(merged[-1], line):
            last = merged[-1]
            last["text"] = f"{last['text']} {line['text']}"
            last["bbox"] = [
                min(last["bbox"][0], line["bbox"][0]),
                min(last["bbox"][1], line["bbox"][1]),
                max(last["bbox"][2], line["bbox"][2]),
                max(last["bbox"][3], line["bbox"][3]),
            ]
            last["lines_joined"] = last.get("lines_joined", 1) + 1
        else:
            merged.append(dict(line))
    candidates = []
    for line in merged:
        text = line["text"]
        if (
            not 2 <= len(text) <= HEADING_MAX_CHARS
            or PAGE_NUMBER.match(text)
            or CAPTION.match(text)
        ):
            continue
        numbered, larger = line["numbered"], line["larger"]
        if line["bold"] and not (larger or numbered) and len(text) > 80:
            continue  # long bold runs are emphasis, not headings
        candidates.append(
            {
                "text": text,
                "size": line["size"],
                "size_ratio": round(line["size"] / body_size, 2) if body_size else None,
                "bold": line["bold"],
                "number": numbered["number"] if numbered else None,
                "bbox": line["bbox"],
                "block_no": line["block_no"],
                "lines_joined": line.get("lines_joined", 1),
                "signals": [
                    s
                    for s, on in (
                        ("larger_font", larger),
                        ("numbered", bool(numbered)),
                        ("bold", line["bold"]),
                    )
                    if on
                ],
            }
        )
    return candidates


def printed_page_label(page: pymupdf.Page, lines: list[dict[str, Any]]) -> dict[str, Any]:
    label = page.get_label() if page.parent.get_page_labels() else ""
    if label:
        return {"value": label, "method": "pdf_page_label_rules", "confidence": "high"}
    height = page.rect.height
    margin_numbers = [
        line["text"]
        for line in lines
        if PAGE_NUMBER.match(line["text"])
        and (
            line["bbox"][1] < MARGIN_FRACTION * height
            or line["bbox"][3] > (1 - MARGIN_FRACTION) * height
        )
    ]
    if len(margin_numbers) == 1:
        return {
            "value": margin_numbers[0].strip(),
            "method": "margin_number_heuristic",
            "confidence": "medium",
        }
    return {"value": None, "method": "none_found", "confidence": None}


def page_images(page: pymupdf.Page) -> tuple[list[dict[str, Any]], float]:
    area = page.rect.width * page.rect.height or 1.0
    images, covered = [], 0.0
    for info in page.get_image_info(xrefs=True):
        box = pymupdf.Rect(info["bbox"]) & page.rect
        if box.is_empty:
            continue
        covered += box.get_area()
        images.append(
            {
                "xref": info.get("xref"),
                "bbox": [round(v, 2) for v in box],
                "pixel_width": info.get("width"),
                "pixel_height": info.get("height"),
                "page_coverage": round(box.get_area() / area, 4),
            }
        )
    return images, round(min(covered / area, 1.0), 4)


def page_tables(page: pymupdf.Page) -> dict[str, Any]:
    try:
        found = page.find_tables()
    except Exception as exc:  # table detection is best-effort; record, do not fail the page
        return {"status": "failed", "error": type(exc).__name__, "tables": []}
    tables = []
    for table in found.tables:
        cells = table.extract()
        filled = sum(1 for row in cells for cell in row if (cell or "").strip())
        if min(table.row_count, table.col_count) == 1:
            kind = "box_or_frame"  # usually a decorative frame around text
        elif filled >= 0.5 * table.row_count * table.col_count:
            kind = "data_grid"
        else:
            kind = "sparse_grid"
        tables.append(
            {
                "bbox": [round(v, 2) for v in table.bbox],
                "kind": kind,
                "filled_cells": filled,
                "row_count": table.row_count,
                "col_count": table.col_count,
                "header": list(table.header.names) if table.header else [],
                "header_is_external": bool(table.header and table.header.external),
                "rows": [[cell if cell is not None else "" for cell in row] for row in cells],
            }
        )
    return {"status": "completed", "strategy": "pymupdf_find_tables_default", "tables": tables}


def extract_page(page: pymupdf.Page) -> dict[str, Any]:
    text = page.get_text("text")
    page_dict = page.get_text("dict")
    lines = _lines(page_dict)
    body_size = body_font_size(lines)
    images, coverage = page_images(page)
    blocks = [
        {
            "block_no": block_no,
            "type": "image" if block_type == 1 else "text",
            "bbox": [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)],
            "text": block_text if block_type == 0 else "",
        }
        for x0, y0, x1, y1, block_text, block_no, block_type in page.get_text("blocks")
    ]
    fonts = sorted({font[3].split("+")[-1] for font in page.get_fonts()})
    return {
        "page_index": page.number,
        "page_label": printed_page_label(page, lines),
        "width": round(page.rect.width, 2),
        "height": round(page.rect.height, 2),
        "rotation": page.rotation,
        "text": text,
        "text_length": len(re.sub(r"\s", "", text)),
        "char_stats": char_stats(text),
        "body_font_size": body_size,
        "blocks": blocks,
        "text_block_count": sum(1 for b in blocks if b["type"] == "text" and b["text"].strip()),
        "heading_candidates": heading_candidates(lines, body_size),
        "caption_candidates": [
            {"text": line["text"], "bbox": line["bbox"]}
            for line in lines
            if CAPTION.match(line["text"]) and len(line["text"]) <= 200
        ],
        "list_item_lines": sum(1 for line in lines if LIST_ITEM.match(line["text"])),
        "superscript_spans": sum(line["superscript_spans"] for line in lines),
        "script_markup_text": "\n".join(line["markup"] for line in lines)
        if any(line["superscript_spans"] or line["subscript_like_spans"] for line in lines)
        else None,
        "subscript_like_spans": sum(line["subscript_like_spans"] for line in lines),
        "images": images,
        "image_coverage": coverage,
        "drawing_count": len(page.get_drawings()),
        "tables": page_tables(page),
        "fonts": fonts,
        "legacy_devanagari_font": any(LEGACY_DEVANAGARI_FONTS.search(f) for f in fonts),
        "extraction_method": "pymupdf_native_text",
    }


def extract_document(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return (document metadata, page records). Raises ExtractionError on open failure."""
    opened = open_pdf(path)
    pages = []
    errors = []
    try:
        for page in opened.document:
            try:
                pages.append(extract_page(page))
            except Exception as exc:  # keep the failed page explicit; never drop it
                errors.append({"page_index": page.number, "error": type(exc).__name__})
                pages.append(
                    {
                        "page_index": page.number,
                        "extraction_method": "failed",
                        "error": type(exc).__name__,
                        "text": "",
                        "text_length": 0,
                    }
                )
    finally:
        opened.document.close()
    opened.metadata["page_errors"] = errors
    return opened.metadata, pages
