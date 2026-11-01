"""Triage the 45-item baseline review queue against the current pilot state.

Every baseline item gets exactly one disposition, decided by rules over the current
enrichment records and the current queue (no judgement calls in code):

| Disposition | Meaning |
|---|---|
| `resolved` | The evidence that answers the item now exists; any follow-up is a new queue item |
| `open` | A reviewer still has to look at pages or existing candidate values |
| `owner_decision` | Only the owner can close it (author objectives, supply records) |

Current queue items that did not exist in the baseline are listed as `new`.
The baseline file is write-once and hash-pinned; it is never regenerated.

    python -m data_pipeline.triage_review_queue
"""

from __future__ import annotations

import collections
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from data_pipeline import owner_attestations as oa
from data_pipeline.clean_teammate_csv import atomic_write_bytes, csv_bytes, json_bytes

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENRICHMENT_DIR = PROJECT_ROOT / "data_pipeline/data/processed/metadata_enrichment"
BASELINE = ENRICHMENT_DIR / "human_review_queue.baseline_2026-10-31.csv"
BASELINE_SHA256 = "0571dd2199a668e60dda2cdd088a7dd20356138d62466eeb0f8d306a050ef805"
TRIAGE_VERSION = "review-triage/1.2.0"
OWNER_DECISIONS = (
    PROJECT_ROOT
    / "data_pipeline/data/overrides/metadata_enrichment/owner_decisions_2026-10-31.json"
)
DISPOSITIONS = ("resolved", "open", "owner_decision")
# Owner instruction (Phase 4 continuation): one canonical inventory row per PDF; several
# topics stay in the topic sidecar instead of being joined or split into new rows.
ONE_ROW_PER_PDF = "owner rule: one canonical row per PDF; topics stay in topic_mapping.csv"
HEADER = (
    "baseline_priority",
    "baseline_item",
    "source_document_id",
    "pdf_page_indexes",
    "disposition",
    "evidence",
    "follow_up_items",
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _page_review_covers(item: dict[str, str], d053: dict[str, Any] | None) -> bool:
    """True if the D-053 attestation is valid and covers every page the item lists."""
    if not d053 or d053.get("status") != "valid":
        return False
    pages = {int(i) for i in item["pdf_page_indexes"].split()}
    covered = {int(index) for sid, index in d053["pages"] if sid == item["source_document_id"]}
    return bool(pages) and pages <= covered


def triage_item(
    item: dict[str, str],
    record: dict[str, Any],
    current: dict[str, dict[str, str]],
    owner: dict[str, Any] | None = None,
    d053: dict[str, Any] | None = None,
) -> tuple[str, str, list[str]]:
    """(disposition, evidence, follow-up items) for one baseline queue row."""
    kind = item["item"].split(":")[0]
    if kind == "ocr_required":
        if "ocr_required" not in current and _page_review_covers(item, d053):
            return (
                "resolved",
                "OCR ran and every listed page is covered by the D-053 page review"
                " (owner attestation; individual findings not recorded)",
                [x for x in ("ocr_quality_review", "ocr_low_confidence_or_empty") if x in current],
            )
        if "ocr_required" in current:
            return "open", "OCR still not run: " + current["ocr_required"]["reason"], []
        if "ocr_low_confidence_or_empty" in current:
            weak = current["ocr_low_confidence_or_empty"]
            return "open", "OCR ran; weak result: " + weak["reason"], [weak["item"]]
        if "ocr_quality_review" in current:
            return "resolved", "local OCR completed for these pages", ["ocr_quality_review"]
        return "resolved", "pages no longer OCR candidates", []
    if kind == "page_review":
        # AI-assisted visual review (D-053) is evidence, never a human review.
        if _page_review_covers(item, d053):
            return (
                "resolved",
                "all listed pages are in the D-053 page review, completed per owner"
                " attestation; individual findings not recorded",
                [],
            )
        return (
            "open",
            "pages not covered by a valid D-053 page-review attestation"
            + (f" ({d053['status']})" if d053 else "")
            + "; AI-assisted findings are not a human review",
            [],
        )
    if kind == "chapter_title_check":
        check = record.get("chapter_title_check") or ""
        if check.startswith("consistent"):
            return "resolved", f"chapter title check: {check}", []
        return "open", f"chapter title check: {check}", []
    if kind == "topic_title":
        status = record["topic_value_status"]
        topics = record.get("topic_count") or 0
        if topics >= 2:
            return "resolved", f"{topics} numbered topics; {ONE_ROW_PER_PDF}", []
        return "open", f"topic status {status}: {record['reasons']['topic_title']}", []
    if kind == "learning_objective":
        status = record["objective_value_status"]
        counts = record.get("objective_counts_by_origin") or {}
        if status == "verified":
            return "resolved", "official objective with page evidence", []
        if status == "ai_generated":
            if (record.get("review_completion") or {}).get(
                "learning_objective"
            ) == "completed_owner_attested":
                outcome = (record.get("approval_outcome") or {}).get("learning_objective")
                return (
                    "resolved",
                    "AI-generated objectives; teacher validation completed per owner attestation"
                    f" (D-054); approval outcome: {outcome}; not individually approved",
                    [],
                )
            return (
                "open",
                "AI-generated objectives written (owner-approved D-049); pending teacher review",
                [],
            )
        if counts.get("textbook_explicit") or counts.get("source_derived_candidate"):
            return "open", f"status {status}; review {counts} in the objective mapping", []
        return "owner_decision", f"status {status}: {record['reasons']['learning_objective']}", []
    if kind == "acquired_at":
        if record["acquisition_date_status"] == "verified":
            return "resolved", "acquisition record found", []
        accepted = ((owner or {}).get("acquired_at") or {}).get("status") == "accept_unknown"
        if accepted and record["acquisition_date_status"] == "unknown":
            return "resolved", "owner accepted `unknown` (D-052); no acquisition record exists", []
        return (
            "owner_decision",
            "no acquisition record; provide one or accept `unknown`"
            f" ({record['reasons']['acquired_at']})",
            [],
        )
    return "open", f"unrecognised baseline item {item['item']}; review manually", []


def triage(
    baseline: list[dict[str, str]],
    records: list[dict[str, Any]],
    queue: list[dict[str, str]],
    owner: dict[str, Any] | None = None,
    d053: dict[str, Any] | None = None,
) -> dict[str, Any]:
    by_source = {r["source_document_id"]: r for r in records}
    current: dict[str, dict[str, dict[str, str]]] = collections.defaultdict(dict)
    for q in queue:
        current[q["source_document_id"]][q["item"].split(":")[0]] = q
    rows = []
    for item in baseline:
        sid = item["source_document_id"]
        disposition, evidence, follow_up = triage_item(
            item, by_source[sid], current[sid], owner, d053
        )
        rows.append(
            [
                item["priority"],
                item["item"],
                sid,
                item["pdf_page_indexes"],
                disposition,
                evidence,
                " ".join(follow_up),
            ]
        )
    baseline_keys = {(b["source_document_id"], b["item"].split(":")[0]) for b in baseline}
    new = [
        q for q in queue if (q["source_document_id"], q["item"].split(":")[0]) not in baseline_keys
    ]
    counts = collections.Counter(r[4] for r in rows)
    return {
        "rows": rows,
        "new_items": new,
        "summary": {
            "triage_version": TRIAGE_VERSION,
            "baseline_items": len(baseline),
            "dispositions": {d: counts.get(d, 0) for d in DISPOSITIONS},
            "by_item": _by_kind(rows),
            "current_queue_items": len(queue),
            "new_items": len(new),
            "new_items_by_kind": dict(collections.Counter(q["item"] for q in new)),
        },
    }


def _by_kind(rows: list[list[str]]) -> dict[str, dict[str, int]]:
    table: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for row in rows:
        table[row[1].split(":")[0]][row[4]] += 1
    return {k: dict(sorted(v.items())) for k, v in sorted(table.items())}


def main() -> int:
    digest = hashlib.sha256(BASELINE.read_bytes()).hexdigest()
    if digest != BASELINE_SHA256:
        raise SystemExit(f"baseline queue changed: {digest}")
    d053 = oa.verify_d053()
    result = triage(
        read_csv(BASELINE),
        json.loads((ENRICHMENT_DIR / "unified_enrichment.json").read_text(encoding="utf-8")),
        read_csv(ENRICHMENT_DIR / "human_review_queue.csv"),
        json.loads(OWNER_DECISIONS.read_text(encoding="utf-8"))["decisions"]
        if OWNER_DECISIONS.exists()
        else None,
        d053,
    )
    new_rows = [
        ["", "", q["source_document_id"], q["pdf_page_indexes"], "new", q["reason"], q["item"]]
        for q in result["new_items"]
    ]
    atomic_write_bytes(
        ENRICHMENT_DIR / "human_review_queue.triage.csv",
        csv_bytes(HEADER, result["rows"] + new_rows),
    )
    summary = {
        **result["summary"],
        "baseline": {"path": BASELINE.relative_to(PROJECT_ROOT).as_posix(), "sha256": digest},
        "d053_page_review": {
            "status": d053["status"],
            "problems": d053["problems"],
            "pages_in_scope": len(d053["pages"]),
            "attestation_sha256": d053.get("attestation_sha256"),
        },
        "owner_decisions_sha256": hashlib.sha256(OWNER_DECISIONS.read_bytes()).hexdigest()
        if OWNER_DECISIONS.exists()
        else None,
        "current_queue_sha256": hashlib.sha256(
            (ENRICHMENT_DIR / "human_review_queue.csv").read_bytes()
        ).hexdigest(),
    }
    atomic_write_bytes(ENRICHMENT_DIR / "human_review_queue.triage.json", json_bytes(summary))
    print(json.dumps(summary["dispositions"]), "new:", summary["new_items"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
