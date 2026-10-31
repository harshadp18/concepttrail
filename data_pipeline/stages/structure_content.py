"""Chapter / topic / subtopic hierarchy from heading candidates (review-required drafts).

Titles are copied verbatim from the extracted text; only their classification is
automatic. Detection order:

1. `chapter`: the largest-font heading candidate on the first content pages, or the PDF
   outline's first entry when one exists.
2. `topic` / `subtopic`: numbered headings (`2.1 ...` = topic, `2.1.3 ...` = subtopic).
3. Unnumbered larger-font headings become `heading_candidate` (low confidence, never a
   topic). So do numbered lines that break the chapter's numbering sequence, e.g. an
   activity question beginning "1.7 ..." between sections 1.2.2 and 1.2.3.

Exercise/example/activity markers and captions are classified as `content_marker`, not
topics. Pages whose text is unusable (legacy-font Hindi) yield no titles.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

STRUCTURE_VERSION = "structure-content/1.6.0"
CHAPTER_SEARCH_PAGES = 2
CONTENT_MARKER = re.compile(
    r"^\s*(?:exercise|example|activity|let us|think|try|do this|project|summary|"
    r"what you have learnt|points to remember|questions|keywords|glossary|"
    r"अभ्यास|उदाहरण|गतिविधि|प्रश्न|शब्दार्थ)\b",
    re.IGNORECASE,
)
# Also NCERT page/file codes such as "iest206" printed on chapter pages.
# Unnumbered large-type lines that are clearly prose fragments (dialogue, mid-sentence).
PROSE_FRAGMENT = re.compile(r"^[\"“‘'(]|^[a-z]|[,;:]$")
NOISE = re.compile(r"^[\W\d_]+$|^[a-z]{4}\d{3}$|reprint|ncert|not to be republished", re.IGNORECASE)


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[\W_]+", " ", text).strip()


def _page_ref(page: dict[str, Any]) -> dict[str, Any]:
    label = (page.get("page_label") or {}).get("value")
    return {"pdf_page_index": page["page_index"], "printed_page_label": label}


def build_hierarchy(raw: dict[str, Any], unusable_pages: set[int]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    pages = [p for p in raw["pages"] if p.get("extraction_method") != "failed"]
    usable = [p for p in pages if p["page_index"] not in unusable_pages]

    toc = raw["document"]["pdf_metadata"].get("toc") or []
    # Only the first outline entry can name the chapter, and only when it is a real title:
    # some NCERT outlines start with the file code ("iest206") and then list figures/maps.
    outline_title = toc[0][1].strip() if toc else ""
    if outline_title and usable and not NOISE.search(outline_title):
        level, title, page_index = toc[0]
        entries.append(
            {
                "kind": "chapter",
                "title": title.strip(),
                "number": None,
                "pdf_page_index": page_index,
                "printed_page_label": None,
                "method": "pdf_outline",
                "confidence": "high",
            }
        )
    else:
        firsts = [
            (c, p)
            for p in usable
            if p.get("text_length", 0) > 0
            for c in p.get("heading_candidates", [])
            if not CONTENT_MARKER.match(c["text"]) and not NOISE.search(c["text"])
        ]
        early = (
            [
                (c, p)
                for c, p in firsts
                if p["page_index"] < firsts[0][1]["page_index"] + CHAPTER_SEARCH_PAGES
            ]
            if firsts
            else []
        )
        if early:
            top = max(c["size"] for c, _ in early)
            parts = [(c, p) for c, p in early if c["size"] >= top - 0.5]
            first_page = parts[0][1]
            entries.append(
                {
                    "kind": "chapter",
                    # identical spans (a title drawn twice) are joined once
                    "title": " ".join(dict.fromkeys(c["text"] for c, _ in parts if c["text"])),
                    "number": None,
                    **_page_ref(first_page),
                    "method": "largest_font_on_first_content_pages",
                    "confidence": "medium",
                }
            )

    chapter_titles = {_norm(e["title"]) for e in entries}
    seen: set[str] = set()
    for page in usable:
        for cand in page.get("heading_candidates", []):
            text = cand["text"].strip()
            key = _norm(text)
            if not key or key in chapter_titles or key in seen or NOISE.search(text):
                continue
            seen.add(key)
            if CONTENT_MARKER.match(text):
                kind, confidence, method = "content_marker", "medium", "marker_pattern"
            elif cand.get("number"):
                depth = cand["number"].count(".")
                kind = "topic" if depth == 1 else "subtopic"
                confidence, method = "medium", "numbered_heading"
            elif "larger_font" in cand.get("signals", []) and not PROSE_FRAGMENT.search(text):
                # Unnumbered large type is often a guiding question, title fragment or even
                # prose set in big type; it is kept for review but never counted as a topic.
                kind, confidence, method = "heading_candidate", "low", "larger_font_heading"
            else:
                continue  # bold-only lines are too noisy to propose as topics
            entries.append(
                {
                    "kind": kind,
                    "title": text,
                    "number": cand.get("number"),
                    **_page_ref(page),
                    "method": method,
                    "confidence": confidence,
                }
            )
    demote_out_of_sequence(entries)
    return entries


def _number_key(number: str) -> tuple[int, ...]:
    return tuple(int(part) for part in number.split("."))


def demote_out_of_sequence(entries: list[dict[str, Any]]) -> None:
    """Demote numbered entries that contradict the chapter's section numbering (in place).

    An entry is out of sequence when its leading number differs from the chapter's
    dominant leading number, or when it sorts after the next numbered entry although its
    two neighbours are themselves in order (a single outlier inside an ascending run).
    """
    numbered = [e for e in entries if e["kind"] in {"topic", "subtopic"}]
    if not numbered:
        return
    leads = [_number_key(e["number"])[0] for e in numbered]
    dominant = max(set(leads), key=lambda lead: (leads.count(lead), -lead))
    keys = [_number_key(e["number"]) for e in numbered]
    for i, entry in enumerate(numbered):
        before = keys[i - 1] if i else None
        after = keys[i + 1] if i + 1 < len(keys) else None
        outlier = keys[i][0] != dominant or (
            after is not None and keys[i] > after and (before is None or before <= after)
        )
        if outlier:
            entry.update(
                kind="heading_candidate",
                confidence="low",
                method="numbered_out_of_sequence",
            )


def chapter_title_check_ocr(inventory_title: str, ocr_text: str | None) -> dict[str, Any]:
    """When native text is unusable, look for the inventory title in OCR of the first pages.

    Parenthetical additions in the inventory title (author, genre) are ignored; the title
    must appear as a contiguous normalised token sequence in the OCR text.
    """
    if not ocr_text:
        return {"status": "cannot_compare_text_unusable", "similarity": None, "detected": None}
    core = _norm(re.sub(r"\([^)]*\)", " ", inventory_title))
    haystack = _norm(ocr_text)
    if core and f" {core} " in f" {haystack} ":
        return {"status": "consistent_via_ocr", "similarity": 1.0, "detected": core}
    words = haystack.split()
    n = max(len(core.split()), 1)
    best = max(
        (
            SequenceMatcher(None, core, " ".join(words[i : i + n])).ratio()
            for i in range(len(words))
        ),
        default=0.0,
    )
    status = "consistent_via_ocr" if best >= 0.8 else "conflict_requires_review_via_ocr"
    return {"status": status, "similarity": round(best, 3), "detected": None}


def chapter_title_check(
    inventory_title: str, hierarchy: list[dict[str, Any]], text_unusable: bool
) -> dict[str, Any]:
    """Compare the inventory chapter title with the detected chapter heading."""
    chapter = next((e for e in hierarchy if e["kind"] == "chapter"), None)
    if text_unusable:
        return {"status": "cannot_compare_text_unusable", "similarity": None, "detected": None}
    if chapter is None:
        return {"status": "chapter_heading_not_detected", "similarity": None, "detected": None}
    a, b = _norm(inventory_title), _norm(chapter["title"])
    similarity = round(SequenceMatcher(None, a, b).ratio(), 3)
    consistent = bool(a and b and (a in b or b in a or similarity >= 0.8))
    return {
        "status": "consistent" if consistent else "conflict_requires_review",
        "similarity": similarity,
        "detected": chapter["title"],
    }
