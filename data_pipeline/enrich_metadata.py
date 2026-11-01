"""Evidence-backed enrichment of `topic_title`, `learning_objective`, `source_url`, `acquired_at`.

Every value carries a status from `VALUE_STATUSES`, an origin, page/evidence references,
a confidence and a review status. Nothing is invented: a field without evidence keeps an
explicit status and reason instead of a placeholder string.

Learning-objective origins:

- `official_source`: a CBSE/NCERT statement recorded with its URL in
  `data_pipeline/data/overrides/metadata_enrichment/official_learning_outcomes.json`.
- `textbook_explicit`: text the textbook itself presents as objectives/outcomes.
- `source_derived_candidate`: a deterministic draft built only from a detected topic
  heading (no LLM). Low confidence; never presented as an official outcome.
- `ai_generated`: owner-approved (D-049) objectives drafted by an AI model from the
  chapter's own text, read from `overrides/metadata_enrichment/ai_generated_learning_
  objectives.json`. Used only when no official or self-contained textbook statement
  exists, only when every evidence term is found in the chapter text, and always
  `pending_teacher_review`. Never presented as textbook-stated, official or approved.
- `human_approved`: set only by a reviewer.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from data_pipeline import teacher_validation as tv

ENRICHMENT_VERSION = "metadata-enrichment/1.8.0"
VALUE_STATUSES = (
    "verified",
    "source_explicit",
    "source_derived_candidate",
    "ai_generated",
    "not_yet_extracted",
    "not_found",
    "unknown",
    "not_applicable",
    "requires_human_review",
)
OBJECTIVE_ORIGINS = (
    "official_source",
    "textbook_explicit",
    "source_derived_candidate",
    "ai_generated",
    "human_approved",
)
MAX_DERIVED_OBJECTIVES = 6
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
OPENING_PAGES = 2  # stated objectives appear where a chapter opens, not mid-chapter
SENTENCE_END = re.compile(r"[.!?।]")
OBJECTIVE_MARKER = re.compile(
    r"learning\s+(?:objectives?|outcomes?)|in this (?:chapter|lesson|unit),?\s+(?:you|we) will"
    r"|after (?:studying|reading) this|you will (?:learn|be able)|by the end of this"
    r"|इस (?:पाठ|अध्याय) (?:में|को पढ़कर)|सीखने के प्रतिफल|अधिगम",
    re.IGNORECASE,
)
DERIVED_TEMPLATES = {
    "mathematics": "Solve problems that apply “{topic}”, as developed in “{chapter}”.",
    "science": "Explain “{topic}” and support the explanation with an observation or"
    " example from “{chapter}”.",
    "social_science": "Describe and explain “{topic}” using evidence presented in “{chapter}”.",
}
# Acquisition records are small text files (download logs, acquisition manifests).
RECORD_SUFFIXES = frozenset({".json", ".jsonl", ".csv", ".txt", ".log", ".md", ".yaml", ".yml"})
MAX_RECORD_BYTES = 5 * 1024 * 1024
REJECTED_ACQUISITION_EVIDENCE = {
    "file_modification_time": "reflects copying/extraction on this machine, not acquisition",
    "macos_quarantine_transfer": "records when the file arrived on this Mac (e.g. via a"
    " messaging app), not when it was acquired from the publisher",
    "pdf_creation_or_modification_date": "publisher production dates, not acquisition",
    "processing_or_cleaning_dates": "pipeline activity, not acquisition",
}

Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)


def _ref(entry: dict[str, Any], artifact: str) -> dict[str, Any]:
    return {
        "artifact": artifact,
        "pdf_page_index": entry.get("pdf_page_index"),
        "printed_page_label": entry.get("printed_page_label"),
    }


# --- topic_title -------------------------------------------------------------------------


def topic_records(
    doc: dict[str, Any], hierarchy: list[dict[str, Any]], artifact: str
) -> list[dict[str, Any]]:
    return [
        {
            "source_document_id": doc["source_id"],
            "inventory_id": doc["inventory_id"],
            "kind": e["kind"],
            "number": e.get("number"),
            "title": e["title"],  # verbatim, including any unmapped glyph codes
            # C0 control codes are unmapped glyphs (D-036 findings), not text.
            "display_title": CONTROL.sub("", e["title"]).strip(),
            "contains_control_characters": bool(CONTROL.search(e["title"])),
            "pdf_page_index": e.get("pdf_page_index"),
            "printed_page_label": e.get("printed_page_label"),
            "extraction_method": e["method"],
            "confidence": e["confidence"],
            # Verbatim heading text; unnumbered candidates still need a reviewer to confirm
            # they are topics at all.
            "value_status": "requires_human_review"
            if e["kind"] == "heading_candidate"
            else "source_explicit",
            "review_status": "requires_human_review",
            # Filled by apply_topic_validation only for covered topic/subtopic rows.
            "review_completion": None,
            "approval_outcome": None,
            "validation_record": None,
            "evidence_reference": artifact,
        }
        for e in hierarchy
        if e["kind"] in ("chapter", "topic", "subtopic", "heading_candidate")
    ]


def apply_topic_validation(
    topics: list[dict[str, Any]], attestation: dict[str, Any]
) -> list[dict[str, Any]]:
    """Record the owner-attested teacher review on a chapter's numbered topic/subtopic rows.

    Only rows covered by the attestation's topic-list digest change; chapter rows and
    `heading_candidate` rows (not topics) keep `requires_human_review`. No row is approved.
    """
    if not topics:
        return topics
    state = tv.topic_validation(attestation, topics[0]["source_document_id"], topics)
    if state is None:
        return topics
    for t in topics:
        if t["kind"] in tv.TOPIC_KINDS:
            t.update(state)
    return topics


def propose_topic_title(
    topics: list[dict[str, Any]], text_unusable: bool, artifact: str, ocr_available: bool = False
) -> dict[str, Any]:
    proposal = _propose_topic_title(topics, text_unusable, artifact, ocr_available)
    covered = [t for t in topics if t["kind"] in tv.TOPIC_KINDS and t.get("review_completion")]
    if covered and proposal["value_status"] == "requires_human_review" and proposal["topic_count"]:
        state = tv.aggregate(covered)
        proposal.update(
            review_status=state["review_status"],
            review_completion=state["review_completion"],
            approval_outcome=state["approval_outcome"],
        )
        if proposal["review_status"] != tv.PENDING_STATUS:
            proposal["reason"] = (
                f"chapter-level inventory row covers {proposal['topic_count']} topics; owner"
                " rule: one canonical row per PDF, so topics stay in topic_mapping.csv (not"
                " joined). The topic list was teacher-reviewed per the owner attestation"
                f" ({state['validation_record']}); the outcome is not individually recorded,"
                " so no approval is claimed"
            )
    return proposal


def _propose_topic_title(
    topics: list[dict[str, Any]], text_unusable: bool, artifact: str, ocr_available: bool = False
) -> dict[str, Any]:
    level_one = [t for t in topics if t["kind"] == "topic"]
    base = {
        "value": None,
        "value_origin": None,
        "evidence_reference": artifact,
        "pdf_page_index": None,
        "confidence": None,
        "topic_count": len(level_one),
    }
    if text_unusable and ocr_available:
        return {
            **base,
            "value_status": "requires_human_review",
            "review_status": "requires_human_review",
            "reason": "native text unusable; OCR text exists but carries no font/heading"
            " signals, so topic headings must be confirmed against the page images",
        }
    if text_unusable:
        return {
            **base,
            "value_status": "not_yet_extracted",
            "review_status": "needs_ocr",
            "reason": "native text unusable (legacy Devanagari font); Hindi OCR required",
        }
    if not level_one:
        return {
            **base,
            "value_status": "not_found",
            "review_status": "requires_human_review",
            "reason": "no topic-level heading detected in the chapter",
        }
    if len(level_one) == 1 and level_one[0]["confidence"] in ("medium", "high"):
        t = level_one[0]
        return {
            **base,
            "value": t["display_title"],
            "value_status": "source_explicit",
            "value_origin": "textbook_heading",
            "pdf_page_index": t["pdf_page_index"],
            "confidence": t["confidence"],
            "review_status": "requires_human_review",
            "reason": "single topic heading in chapter",
        }
    if len(level_one) == 1:
        return {
            **base,
            "value_status": "requires_human_review",
            "review_status": "requires_human_review",
            "reason": "only a low-confidence heading was found (it may be an author name,"
            " epigraph or caption); a reviewer must confirm it is a topic",
        }
    return {
        **base,
        "value_status": "requires_human_review",
        "review_status": "requires_human_review",
        "reason": f"chapter-level inventory row covers {len(level_one)} topics; owner rule:"
        " one canonical row per PDF, so topics stay in topic_mapping.csv (not joined);"
        " the topic list still needs reviewer confirmation",
    }


# --- learning_objective ------------------------------------------------------------------


def _marker_sentence(text: str, start: int) -> str:
    begin = max((m.end() for m in SENTENCE_END.finditer(text, 0, start)), default=0)
    end_match = SENTENCE_END.search(text, start)
    return text[begin : end_match.end() if end_match else len(text)].strip()


def explicit_objectives(
    doc: dict[str, Any], normalized: dict[str, Any], artifact: str
) -> list[dict[str, Any]]:
    """The sentence that states the objective, plus list items directly after it.

    Only the chapter's opening pages are searched: "you will learn more about this later"
    inside a chapter is an aside, not a statement of objectives.
    """
    from data_pipeline.stages.extract_pdf import LIST_ITEM

    def readable(page: dict[str, Any]) -> list[dict[str, Any]]:
        if not page["text_unusable"]:
            return page["paragraphs"] if page["text"].strip() else []
        ocr = page.get("ocr") or {}
        if ocr.get("status") in ("completed", "low_confidence"):
            return [{"kind": "ocr", "text": t} for t in ocr.get("paragraphs", [])]
        return []

    usable = [p for p in normalized["pages"] if readable(p)]
    found = []
    for page in usable[:OPENING_PAGES]:
        paragraphs = readable(page)
        from_ocr = page["text_unusable"]
        for i, para in enumerate(paragraphs):
            marker = OBJECTIVE_MARKER.search(para["text"])
            if not marker:
                continue
            statements = [_marker_sentence(para["text"], marker.start())]
            for follow in paragraphs[i + 1 :]:
                if not LIST_ITEM.match(follow["text"]):
                    break
                statements.append(follow["text"].strip())
            for text in statements:
                if text and len(text) <= 400:
                    found.append(
                        {
                            "objective": text,
                            "value_origin": "textbook_explicit",
                            "source_document_id": doc["source_id"],
                            "pdf_page_index": page["page_index"],
                            "printed_page_label": (page.get("page_label") or {}).get("value"),
                            "curriculum_version": doc.get("academic_session"),
                            "confidence": "low" if from_ocr else "medium",
                            "extraction_method": "ocr" if from_ocr else "native_text",
                            "review_status": "requires_human_review",
                            "evidence_reference": artifact,
                        }
                    )
    return found


def official_objectives(
    doc: dict[str, Any], catalogue: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    out = []
    for item in catalogue:
        if (
            item["class_level"] == doc["class_level"]
            and item["subject_id"] == doc["subject_id"]
            and item.get("academic_session") == doc.get("academic_session")
            and item["chapter_match"].casefold() in doc["chapter_title"].casefold()
        ):
            out.append(
                {
                    "objective": item["objective"],
                    "value_origin": "official_source",
                    "source_document_id": doc["source_id"],
                    "pdf_page_index": None,
                    "printed_page_label": None,
                    "curriculum_version": item.get("academic_session"),
                    "confidence": "high",
                    "review_status": "verified_source_citation",
                    "evidence_reference": f"{item['source_url']} ({item['source_title']},"
                    f" {item.get('source_page', 'n/a')})",
                }
            )
    return out


def derived_objectives(
    doc: dict[str, Any], topics: list[dict[str, Any]], artifact: str
) -> list[dict[str, Any]]:
    template = DERIVED_TEMPLATES.get(doc["subject_id"])
    if template is None:
        return []  # language chapters: no templated objectives (would be generic)
    ranked = sorted(
        (t for t in topics if t["kind"] == "topic" and t["confidence"] in ("medium", "high")),
        key=lambda t: (t["confidence"] != "medium", t["pdf_page_index"] or 0),
    )[:MAX_DERIVED_OBJECTIVES]
    return [
        {
            "objective": template.format(topic=t["display_title"], chapter=doc["chapter_title"]),
            "value_origin": "source_derived_candidate",
            "source_document_id": doc["source_id"],
            "pdf_page_index": t["pdf_page_index"],
            "printed_page_label": t.get("printed_page_label"),
            "curriculum_version": doc.get("academic_session"),
            "supporting_heading": t["display_title"],
            "confidence": "low",
            "review_status": "requires_human_review",
            "evidence_reference": artifact,
        }
        for t in ranked
    ]


# A lone marker sentence pointing at text outside itself ("we will try to answer these
# questions") is not a usable objective, even though it is verbatim textbook text.
ANAPHORIC_REFERENCE = re.compile(
    r"\b(?:these|those|them|the above|above|the following|following|such)\b", re.IGNORECASE
)


def self_contained(statements: list[str]) -> bool:
    """True unless the only statement is a marker sentence that refers elsewhere."""
    return len(statements) > 1 or not ANAPHORIC_REFERENCE.search(statements[0])


def load_generated_objectives(path: Path) -> dict[str, Any]:
    """The owner-approved AI-generated objective record, keyed by source_id ({} if absent)."""
    if not path.exists():
        return {}
    record = json.loads(path.read_text(encoding="utf-8"))
    meta = {k: v for k, v in record.items() if k != "chapters"}
    return {c["source_id"]: {"meta": meta, "chapter": c} for c in record["chapters"]}


def _squash(text: str) -> str:
    return " ".join(CONTROL.sub("", text).split())


def ai_generated_objectives(
    doc: dict[str, Any],
    normalized: dict[str, Any],
    generated: dict[str, Any],
    artifact: str,
    attestation: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Generated objectives for this chapter, each grounded in the chapter's own text.

    An objective is `grounded` only if every evidence term occurs in the chapter text
    (native normalised text; OCR text for unusable pages), after collapsing whitespace.
    The pages where each term occurs are recorded. Ungrounded objectives are kept as
    rejected evidence and never used.
    """
    entry = generated.get(doc["source_id"])
    if entry is None:
        return []
    meta, chapter = entry["meta"], entry["chapter"]
    if chapter["inventory_id"] != doc["inventory_id"]:
        raise ValueError(f"{doc['source_id']}: generated objectives name another inventory_id")
    pages = [
        (
            p["page_index"],
            _squash(
                p["text"] if not p["text_unusable"] else (p.get("ocr") or {}).get("text") or ""
            ),
        )
        for p in normalized["pages"]
    ]
    out = []
    for number, objective in enumerate(chapter["objectives"], 1):
        term_pages = {
            term: [i for i, text in pages if _squash(term) in text]
            for term in objective["evidence_terms"]
        }
        grounded = bool(term_pages) and all(term_pages.values())
        evidence_pages = sorted({i for found in term_pages.values() for i in found})
        oid = tv.objective_id(doc["inventory_id"], number)
        validation = (
            tv.objective_validation(attestation or {}, chapter, oid)
            if grounded
            else {
                "review_completion": "not_applicable",
                "approval_outcome": None,
                "review_status": "rejected_ungrounded",
                "validation_record": None,
            }
        )
        out.append(
            {
                "objective_id": oid,
                "objective": objective["text"],
                "value_origin": "ai_generated",
                "source_document_id": doc["source_id"],
                "curriculum_version": doc.get("academic_session"),
                "pdf_page_index": " ".join(str(i) for i in evidence_pages),
                "printed_page_label": None,
                "supporting_heading": None,
                "language": chapter.get("language"),
                "generation_method": meta["generation_method"],
                "generator": meta["generator"],
                "generation_record": meta["record_id"],
                "grounding": "grounded" if grounded else "rejected_ungrounded",
                "evidence_terms": term_pages,
                "confidence": None,
                # Current state comes from the owner attestation (if it still binds to this
                # exact text); the status at generation is kept as history.
                "review_status": validation["review_status"],
                "review_completion": validation["review_completion"],
                "approval_outcome": validation["approval_outcome"],
                "validation_record": validation["validation_record"],
                "review_status_at_generation": meta["review_status"],
                "evidence_reference": artifact,
            }
        )
    return out


def propose_objective(
    objectives: list[dict[str, Any]],
    text_unusable: bool,
    subject: str,
    ocr_available: bool = False,
) -> dict[str, Any]:
    counts = {o: sum(1 for x in objectives if x["value_origin"] == o) for o in OBJECTIVE_ORIGINS}
    usable = [
        x for x in objectives if x["value_origin"] in ("official_source", "textbook_explicit")
    ]
    base = {"value": None, "counts_by_origin": counts}
    explicit_ok = bool(usable) and self_contained([x["objective"] for x in usable])
    generated = [
        x
        for x in objectives
        if x["value_origin"] == "ai_generated" and x.get("grounding") == "grounded"
    ]
    # A teacher outcome of rejected or revision_required keeps an objective out of the value.
    writable = [
        x for x in generated if x.get("approval_outcome") not in ("rejected", "revision_required")
    ]
    if writable and not explicit_ok:
        state = tv.aggregate(generated)
        completed = state["review_completion"] == tv.REVIEW_COMPLETED
        return {
            **base,
            "value": " | ".join(x["objective"] for x in writable),
            "value_status": "ai_generated",
            "value_origin": "ai_generated",
            "review_status": state["review_status"],
            "review_completion": state["review_completion"],
            "approval_outcome": state["approval_outcome"],
            "reason": f"{len(writable)} of {len(generated)} AI-generated objective(s),"
            " owner-approved (D-049), grounded in the chapter text; not textbook-stated or"
            " official; "
            + (
                "teacher validation completed per owner attestation"
                f" ({state['validation_record']}); approval outcome:"
                f" {state['approval_outcome']}"
                if completed
                else "pending teacher review"
            ),
        }
    if usable and not self_contained([x["objective"] for x in usable]):
        return {
            **base,
            "value_status": "requires_human_review",
            "value_origin": usable[0]["value_origin"],
            "review_status": "requires_human_review",
            "reason": "explicit statement refers to text outside itself (not self-contained);"
            " kept in the objective mapping as evidence, not written",
        }
    if usable:
        return {
            **base,
            "value": " | ".join(x["objective"] for x in usable),
            "value_status": "verified"
            if usable[0]["value_origin"] == "official_source"
            else "source_explicit",
            "value_origin": usable[0]["value_origin"],
            "review_status": "requires_human_review",
            "reason": "explicit or official objectives",
        }
    if counts["source_derived_candidate"]:
        return {
            **base,
            "value_status": "source_derived_candidate",
            "value_origin": "source_derived_candidate",
            "review_status": "requires_human_review",
            "reason": "only derived candidates; not written to the inventory until approved",
        }
    if text_unusable and not ocr_available:
        return {
            **base,
            "value_status": "not_yet_extracted",
            "value_origin": None,
            "review_status": "needs_ocr",
            "reason": "text unusable until Hindi OCR",
        }
    reason = (
        "language chapter without stated objectives; needs teacher-authored objectives"
        if subject in ("english", "hindi")
        else "no explicit objectives or topic headings found"
    )
    return {
        **base,
        "value_status": "requires_human_review",
        "value_origin": None,
        "review_status": "requires_human_review",
        "reason": reason,
    }


# --- source_url ----------------------------------------------------------------------------


def propose_url(doc: dict[str, Any], evidence: dict[str, Any] | None) -> dict[str, Any]:
    if evidence is None:
        return {
            "value": None,
            "value_status": "unknown",
            "review_status": "needs_research",
            "reason": "source URL verification not yet run",
            "confidence": None,
            "evidence_reference": None,
        }
    result = next((r for r in evidence["results"] if r["source_id"] == doc["source_id"]), None)
    if result is None:
        return {
            "value": None,
            "value_status": "unknown",
            "review_status": "needs_research",
            "reason": "document not covered by URL verification",
            "confidence": None,
            "evidence_reference": None,
        }
    return {
        "value": result.get("url"),
        "value_status": result["url_value_status"],
        "review_status": result["review_status"],
        "reason": result["reason"],
        "confidence": result.get("confidence"),
        "source_organization": result.get("source_organization"),
        "source_title": result.get("source_title"),
        "book_page_url": result.get("book_page_url"),
        "verification_date": result.get("verification_date"),
        "verification_method": result.get("verification_method"),
        "evidence_reference": "source_url_evidence.json",
    }


# --- acquired_at -----------------------------------------------------------------------------


def quarantine_transfer(path: Path, run: Runner = _run) -> dict[str, Any] | None:
    """macOS quarantine attribute: transfer evidence only (never an acquisition date)."""
    try:
        out = run(["xattr", "-p", "com.apple.quarantine", str(path)])
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    parts = out.stdout.strip().split(";")
    when = None
    if len(parts) > 1:
        try:
            when = dt.datetime.fromtimestamp(int(parts[1], 16), dt.UTC).isoformat()
        except ValueError:
            when = None
    return {"agent": parts[2] if len(parts) > 2 else None, "arrived_on_this_machine_utc": when}


def acquisition_evidence(
    doc: dict[str, Any],
    pdf_path: Path,
    search_roots: list[Path],
    pdf_metadata: dict[str, Any],
    run: Runner = _run,
) -> dict[str, Any]:
    considered = []
    if doc.get("acquired_at"):
        return {
            "value": doc["acquired_at"],
            "acquisition_date_status": "verified",
            "reason": "inventory value",
            "review_status": "requires_human_review",
            "evidence_considered": [{"type": "inventory", "accepted": True}],
        }
    considered.append({"type": "inventory_acquired_at", "found": False, "accepted": False})
    hits = sorted(
        str(p)
        for root in search_roots
        if root.exists()
        for p in root.rglob("*")
        if p.suffix.lower() in RECORD_SUFFIXES
        and re.search(r"download|acquisition|acquired|\.log$", p.name, re.I)
        and p.is_file()
        and p.stat().st_size <= MAX_RECORD_BYTES
        and pdf_path.name in p.read_text(encoding="utf-8", errors="ignore")
    )
    considered.append(
        {
            "type": "acquisition_or_download_records",
            "found": hits,
            "accepted": False,
            "note": "none mention this file" if not hits else "requires manual review",
        }
    )
    transfer = quarantine_transfer(pdf_path, run)
    considered.append(
        {
            "type": "macos_quarantine_transfer",
            "found": transfer,
            "accepted": False,
            "why_rejected": REJECTED_ACQUISITION_EVIDENCE["macos_quarantine_transfer"],
        }
    )
    considered.append(
        {
            "type": "pdf_creation_or_modification_date",
            "found": {
                "creation_date": pdf_metadata.get("creation_date"),
                "modification_date": pdf_metadata.get("modification_date"),
            },
            "accepted": False,
            "why_rejected": REJECTED_ACQUISITION_EVIDENCE["pdf_creation_or_modification_date"],
        }
    )
    considered.append(
        {
            "type": "file_modification_time",
            "accepted": False,
            "why_rejected": REJECTED_ACQUISITION_EVIDENCE["file_modification_time"],
        }
    )
    if hits:
        return {
            "value": None,
            "acquisition_date_status": "requires_human_review",
            "reason": "possible acquisition records found; date not parsed automatically",
            "review_status": "needs_evidence",
            "evidence_considered": considered,
        }
    return {
        "value": None,
        "acquisition_date_status": "unknown",
        "reason": "acquisition_evidence_unavailable",
        "review_status": "needs_evidence",
        "evidence_considered": considered,
    }


def load_official_catalogue(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("outcomes", [])
