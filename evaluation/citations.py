"""Citation checks for captured grounded answers (pure functions; no model is called).

A captured record: {"case_id", "class_level", "subject_id", "language", "answer": {"explanation",
"steps", "hint", "evidence_labels"}, "evidence": [{"label", "source_id", "pdf_page_index",
"text"}], "abstained": bool}.

What is automated here is only (1) whether every cited label is an evidence block that was
actually supplied and (2) a crude lexical overlap between each answer sentence and the cited text.
(2) is a PROXY: a sentence can reuse the page's words and still draw a wrong conclusion, so
"supported" is a human judgement (see `evaluation.catalog`). Nothing here scores correctness.
"""

from __future__ import annotations

import re
from typing import Any

_LABEL = re.compile(r"\bE\d{1,2}\b")
_WORD = re.compile(r"\w+", re.UNICODE)
OVERLAP_FLOOR = 0.5  # proxy threshold, not validated against human judgement


def sentences(answer: dict[str, Any]) -> list[str]:
    text = " ".join(
        [answer.get("explanation", ""), *answer.get("steps", []), answer.get("hint", "")]
    )
    return [s.strip() for s in re.split(r"(?<=[.!?।])\s+", text) if len(s.split()) >= 4]


def content_words(text: str) -> set[str]:
    return {w.casefold() for w in _WORD.findall(_LABEL.sub(" ", text)) if len(w) > 3}


def check_record(record: dict[str, Any]) -> dict[str, Any]:
    answer, evidence = record.get("answer") or {}, record.get("evidence") or []
    by_label = {e["label"]: e for e in evidence}
    declared = list(answer.get("evidence_labels") or [])
    inline = sorted(set(_LABEL.findall(" ".join(sentences(answer)))))
    cited = declared or inline
    out: dict[str, Any] = {
        "case_id": record.get("case_id"),
        "abstained": bool(record.get("abstained")),
        "cited_labels": cited,
        "all_cited_labels_were_supplied": bool(cited) and all(c in by_label for c in cited),
        "invented_labels": sorted(c for c in cited if c not in by_label),
        "answered_without_any_citation": not record.get("abstained") and not cited,
    }
    if out["all_cited_labels_were_supplied"]:
        cited_text = content_words(" ".join(by_label[c]["text"] for c in cited))
        overlaps = []
        for sentence in sentences(answer):
            words = content_words(sentence)
            if words:
                overlaps.append(len(words & cited_text) / len(words))
        out["sentences"] = len(overlaps)
        out["mean_overlap"] = round(sum(overlaps) / len(overlaps), 4) if overlaps else None
        out["sentences_below_overlap_floor"] = sum(o < OVERLAP_FLOOR for o in overlaps)
    return out
