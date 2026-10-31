"""D-044: remove font-generated duplicate Devanagari code points (owner-approved 2026-10-31).

Some Devanagari fonts (Kokila in `IHGA1-02`) map one glyph to the same code point twice,
so extracted text reads `अन््य`, `अपनने`. Rule: a Devanagari code point (U+0900–U+097F)
identical to the previous character **of the same span at the same glyph origin** is
dropped. A genuinely doubled letter (`सुनने`) is two glyphs at different positions and is
kept; Latin text, digits and whitespace are never touched.

The repair works on a copy of the raw page: raw artifacts and PDFs are never modified.
Glyph positions come from the PDF (`rawdict`); the raw block text (`blocks`) is aligned to
the glyph stream on non-whitespace characters, so each correction lands on an exact offset.
A block whose characters cannot be aligned is left unrepaired and reported.

Repeats at *different* positions are not covered by the rule and are listed for human
review, never corrected: repeated vowel signs (`होों`), repeated sign pairs (`ांां`) and
consonants repeated after a virama (`ख्ययाति`; suspect only, since `अध्ययन` is genuine) and
a virama followed by a vowel sign (`कक्ाओं`: the conjunct's second consonant is missing).
"""

from __future__ import annotations

import copy
import re
from typing import Any

REPAIR_VERSION = "devanagari-glyph-repair/1.3.0"
RULE_ID = "D-044"
SAME_ORIGIN_TOLERANCE = 0.01
DEVANAGARI_WORD = re.compile(r"[ऀ-ॿ‌‍]+")
# The same dependent vowel sign or bindu twice in a row: never valid Hindi spelling.
REPEATED_SIGN = re.compile(r"([ँ-ःा-ौ])\1")


def is_devanagari(ch: str) -> bool:
    return "ऀ" <= ch <= "ॿ"


def glyph_blocks(page: Any) -> list[list[tuple[str, bool]]]:
    """Per text block: (character, drop?) in reading order, from the page's `rawdict`."""
    blocks = []
    for block in page.get_text("rawdict")["blocks"]:
        if block.get("type", 0) != 0:
            continue
        chars: list[tuple[str, bool]] = []
        for line in block.get("lines", []):
            for span in line["spans"]:
                previous = None
                for ch in span["chars"]:
                    drop = (
                        previous is not None
                        and ch["c"] == previous["c"]
                        and is_devanagari(ch["c"])
                        and abs(ch["origin"][0] - previous["origin"][0]) < SAME_ORIGIN_TOLERANCE
                    )
                    chars.append((ch["c"], drop))
                    if not drop:
                        previous = ch
        blocks.append(chars)
    return blocks


def _key(chars: list[tuple[str, bool]]) -> str:
    return "".join(c for c, _ in chars if not c.isspace())


def _word_at(text: str, offset: int) -> tuple[int, int]:
    start = offset
    while start > 0 and DEVANAGARI_WORD.fullmatch(text[start - 1]):
        start -= 1
    end = offset
    while end < len(text) and DEVANAGARI_WORD.fullmatch(text[end]):
        end += 1
    return start, end


def repair_text(
    text: str, chars: list[tuple[str, bool]]
) -> tuple[str, list[dict[str, Any]]] | None:
    """Apply drop flags to `text`; None when the non-whitespace streams differ."""
    glyphs = [(c, d) for c, d in chars if not c.isspace()]
    if "".join(c for c, _ in glyphs) != "".join(c for c in text if not c.isspace()):
        return None
    out: list[str] = []
    dropped: list[int] = []
    g = 0
    for offset, ch in enumerate(text):
        if ch.isspace():
            out.append(ch)
            continue
        if glyphs[g][1]:
            dropped.append(offset)
        else:
            out.append(ch)
        g += 1
    if not dropped:
        return text, []
    repaired = "".join(out)
    corrections = []
    for offset in dropped:
        start, end = _word_at(text, offset)
        # Position of the same word in the repaired text: earlier drops shift it left.
        shift = sum(1 for o in dropped if o < start)
        inside = sum(1 for o in dropped if start <= o < end)
        corrections.append(
            {
                "offset": offset,
                "character": text[offset],
                "codepoint": f"U+{ord(text[offset]):04X}",
                "word_before": text[start:end],
                "word_after": repaired[start - shift : end - shift - inside],
            }
        )
    return repaired, corrections


def repair_page(raw_page: dict[str, Any], pdf_page: Any) -> dict[str, Any]:
    """Repaired copy of one raw page, plus its correction log. The input is not modified."""
    page = copy.deepcopy(raw_page)
    available = glyph_blocks(pdf_page)
    used: set[int] = set()
    corrections: list[dict[str, Any]] = []
    unaligned: list[int] = []
    for block in page.get("blocks", []):
        if block.get("type") != "text" or not block["text"].strip():
            continue
        key = "".join(c for c in block["text"] if not c.isspace())
        match = next(
            (i for i, chars in enumerate(available) if i not in used and _key(chars) == key),
            None,
        )
        if match is None:
            if any(is_devanagari(c) for c in key):
                unaligned.append(block["block_no"])
            continue
        used.add(match)
        result = repair_text(block["text"], available[match])
        if result is None:  # pragma: no cover - keys are equal, so streams align
            unaligned.append(block["block_no"])
            continue
        block["text"], block_corrections = result
        corrections += [{"block_no": block["block_no"], **c} for c in block_corrections]
    # Heading candidates are copies of line text: repair them through the page stream.
    stream = [g for chars in glyph_blocks(pdf_page) for g in chars]
    page_key = _key(stream)
    for cand in page.get("heading_candidates", []):
        key = "".join(c for c in cand["text"] if not c.isspace())
        start = page_key.find(key) if key else -1
        if start < 0:
            continue
        flags = [g for g in stream if not g[0].isspace()][start : start + len(key)]
        result = repair_text(cand["text"], flags)
        if result is not None:
            cand["text"] = result[0]
    return {
        "page": page,
        "corrections": corrections,
        "unaligned_blocks": unaligned,
    }


def repeated_signs(text: str) -> list[dict[str, Any]]:
    """Remaining repeated vowel signs (not covered by D-044): offsets and words for review."""
    found = []
    for match in REPEATED_SIGN.finditer(text):
        start, end = _word_at(text, match.start())
        found.append(
            {
                "offset": match.start(),
                "sign": match.group(1),
                "codepoint": f"U+{ord(match.group(1)):04X}",
                "word": text[start:end],
            }
        )
    return found


# Further residue the rule does not cover. A repeated vowel-sign + bindu pair is never valid;
# a consonant repeated right after a virama is only *suspect* (`अध्ययन` is a real word).
REPEATED_SIGN_PAIR = re.compile(r"([\u093e-\u094c][\u0901-\u0903])\1")
SUSPECT_CONSONANT_REPEAT = re.compile(r"\u094d[\u200c\u200d]?([\u0915-\u0939])\1")
# A virama directly followed by a vowel sign is never valid: the conjunct's second
# consonant was lost by the font (क्ष -> क्ा, द्व -> द्ा). Only the page image can restore it.
SUSPECT_SYLLABLE_REPEAT = re.compile(r"([\u0915-\u0939][\u0901\u0902])\1")  # यंयं
MISSING_CONJUNCT_CONSONANT = re.compile(r"\u094d[\u093e-\u094c]")


def other_review_flags(text: str) -> list[dict[str, Any]]:
    """Residual repeats outside D-044 and outside the vowel-sign count; review only."""
    found = []
    for kind, pattern in (
        ("repeated_sign_pair", REPEATED_SIGN_PAIR),
        ("suspect_consonant_repeat_after_virama", SUSPECT_CONSONANT_REPEAT),
        ("suspect_syllable_repeat", SUSPECT_SYLLABLE_REPEAT),
        ("missing_conjunct_consonant", MISSING_CONJUNCT_CONSONANT),
    ):
        for match in pattern.finditer(text):
            start, end = _word_at(text, match.start())
            found.append({"kind": kind, "offset": match.start(), "word": text[start:end]})
    return sorted(found, key=lambda f: f["offset"])


def repair_document(raw: dict[str, Any], pdf: Any) -> dict[str, Any]:
    """Repaired raw view (for normalisation only) and the full correction log."""
    view = copy.deepcopy(raw)
    log_pages = []
    for index, raw_page in enumerate(raw["pages"]):
        result = repair_page(raw_page, pdf[index])
        view["pages"][index] = result["page"]
        log_pages.append(
            {
                "pdf_page_index": raw_page["page_index"],
                "printed_page_label": (raw_page.get("page_label") or {}).get("value"),
                "corrections": result["corrections"],
                "unaligned_blocks": result["unaligned_blocks"],
            }
        )
    return {
        "view": view,
        "log": {
            "repair_version": REPAIR_VERSION,
            "rule": RULE_ID,
            "source_id": raw["document"]["source_id"],
            "pdf_sha256": raw["document"]["pdf_sha256"],
            "corrections_total": sum(len(p["corrections"]) for p in log_pages),
            "unaligned_blocks_total": sum(len(p["unaligned_blocks"]) for p in log_pages),
            "pages": log_pages,
        },
    }
