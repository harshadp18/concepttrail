"""Owner attestation that teacher validation is complete, and how it reconciles review states.

The owner confirmed (2026-10-31) that teacher validation has been completed. The project holds
no teacher identities, comments, scores, dates or per-item outcomes, so this module records
two things **separately**:

- `review_completion`: `completed_owner_attested` (the owner's confirmation) or `pending`.
- `approval_outcome`: `approved`, `rejected`, `revision_required` or `not_individually_recorded`.

Completion never implies approval. An outcome other than `not_individually_recorded` is used
only if the attestation lists it for that exact objective ID (`individual_outcomes`); today the
list is empty, so every outcome is `not_individually_recorded`.

Historical records are not edited. `ai_generated_learning_objectives.json` keeps its original
`pending_teacher_review` (the truth when it was written) and its SHA-256, which the attestation
records. Current status is derived downstream from the attestation.

The attestation is bound to the content that was validated, not just to a file hash:

- AI-generated objectives: per chapter, a digest of the inventory ID, source ID and, for each
  objective, its ID, text and evidence terms. Any change to an ID, a text, an evidence term, the
  order or the chapter identity stops the attestation applying to that chapter.
- Topics: per chapter, a digest of the inventory ID, source ID and the numbered topic/subtopic
  list (kind, number, verbatim title). Only `topic` and `subtopic` rows are covered; chapter
  rows and `heading_candidate` rows are not topics and keep `requires_human_review`. Chapters
  with no numbered topic list get nothing.

    python -m data_pipeline.teacher_validation record
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OVERRIDES = PROJECT_ROOT / "data_pipeline/data/overrides/metadata_enrichment"
ATTESTATION_PATH = OVERRIDES / "teacher_validation_attestation_2026-10-31.json"
GENERATION_PATH = OVERRIDES / "ai_generated_learning_objectives.json"
TOPIC_MAPPING_PATH = (
    PROJECT_ROOT / "data_pipeline/data/processed/metadata_enrichment/topic_mapping.csv"
)

RECORD_ID = "OWNER-ATTESTATION-2026-10-31-teacher-validation"
DECISION_REFERENCE = "docs/DECISIONS.md D-054"
EXPECTED_OBJECTIVES = 51
EXPECTED_CHAPTERS = 9
REVIEW_COMPLETED = "completed_owner_attested"
REVIEW_PENDING = "pending"
OUTCOMES = ("approved", "rejected", "revision_required", "not_individually_recorded")
NOT_RECORDED = "not_individually_recorded"
PENDING_STATUS = "pending_teacher_review"
MIXED_STATUS = "teacher_reviewed_mixed_outcomes"
OUTCOME_STATUS = {
    "approved": "teacher_approved",
    "rejected": "teacher_rejected",
    "revision_required": "teacher_revision_required",
    NOT_RECORDED: "teacher_reviewed_outcome_not_recorded",
}
REVIEW_STATUSES = (PENDING_STATUS, MIXED_STATUS, *OUTCOME_STATUS.values())
TOPIC_KINDS = ("topic", "subtopic")
OUTCOME_ENTRY_KEYS = frozenset({"objective_id", "outcome", "evidence_reference"})
NOT_HELD = (
    "teacher identities",
    "teacher comments",
    "individual scores",
    "individual approval, rejection or revision decisions",
    "review dates",
    "review evidence documents",
)


def _digest(payload: Any) -> str:
    data = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def objective_id(inventory_id: str, number: int) -> str:
    """The ID the pipeline gives the `number`-th (1-based) generated objective of a chapter."""
    return f"{inventory_id}-AI-LO{number:02d}"


def chapter_objective_ids(chapter: dict[str, Any]) -> list[str]:
    return [
        objective_id(chapter["inventory_id"], n) for n in range(1, len(chapter["objectives"]) + 1)
    ]


def objectives_digest(chapter: dict[str, Any]) -> str:
    """Digest of one chapter's generated objectives: identity, IDs, text and evidence terms."""
    ids = chapter_objective_ids(chapter)
    return _digest(
        {
            "inventory_id": chapter["inventory_id"],
            "source_id": chapter["source_id"],
            "objectives": [
                {"objective_id": oid, "text": o["text"], "evidence_terms": o["evidence_terms"]}
                for oid, o in zip(ids, chapter["objectives"], strict=True)
            ],
        }
    )


def topic_list_digest(source_id: str, rows: list[dict[str, Any]]) -> str | None:
    """Digest of a chapter's numbered topic/subtopic list; None when it has none."""
    listed = [r for r in rows if r["kind"] in TOPIC_KINDS]
    if not listed:
        return None
    inventory_ids = {r["inventory_id"] for r in listed}
    if len(inventory_ids) != 1:
        raise ValueError(f"{source_id}: topic rows name several inventory IDs")
    return _digest(
        {
            "source_id": source_id,
            "inventory_id": next(iter(inventory_ids)),
            "topics": [
                {"kind": r["kind"], "number": r.get("number") or "", "title": r["title"]}
                for r in listed
            ],
        }
    )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_generation(generation: dict[str, Any]) -> list[str]:
    """Check the generation record has exactly 51 objectives in 9 chapters; return their IDs."""
    chapters = generation["chapters"]
    if len(chapters) != EXPECTED_CHAPTERS:
        raise ValueError(f"expected {EXPECTED_CHAPTERS} chapters, found {len(chapters)}")
    for key in ("source_id", "inventory_id"):
        values = [c[key] for c in chapters]
        if len(set(values)) != len(values):
            raise ValueError(f"duplicate {key} across chapters")
    ids = [oid for c in chapters for oid in chapter_objective_ids(c)]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate objective IDs")
    if len(ids) != EXPECTED_OBJECTIVES:
        raise ValueError(f"expected {EXPECTED_OBJECTIVES} objectives, found {len(ids)}")
    if any(
        not o["text"].strip() or not o["evidence_terms"] for c in chapters for o in c["objectives"]
    ):
        raise ValueError("every objective needs text and evidence terms")
    return ids


def build_attestation(
    generation: dict[str, Any], topic_rows: list[dict[str, Any]], generation_sha256: str
) -> dict[str, Any]:
    ids = validate_generation(generation)
    chapters = generation["chapters"]
    by_source: dict[str, list[dict[str, Any]]] = {}
    for row in topic_rows:
        by_source.setdefault(row["source_document_id"], []).append(row)
    topic_digests = {
        sid: digest
        for sid, rows in sorted(by_source.items())
        if (digest := topic_list_digest(sid, rows))
    }
    return {
        "record_id": RECORD_ID,
        "recorded_on": "2026-10-31",
        "authorization_basis": "owner_attestation",
        "statement": "The owner confirms that teacher validation has been completed.",
        "nature": (
            "Owner-provided attestation of review completion. It is not independent"
            " verification, not a teacher's own record, and not an approval of any individual"
            " objective or topic."
        ),
        "decision_reference": DECISION_REFERENCE,
        "supersedes_status": {
            "status": PENDING_STATUS,
            "applies_to": "current derived status only",
            "note": (
                "Historical records (the generation record, D-049 text and the earlier Phase 4"
                " reports) stated `pending_teacher_review` correctly when written and are not"
                " edited. Current downstream status is derived from this attestation."
            ),
        },
        "review_completion": REVIEW_COMPLETED,
        "default_approval_outcome": NOT_RECORDED,
        "individual_outcomes_status": "not_provided",
        "individual_outcomes": [],
        "individual_outcomes_schema": {
            "entry_keys": sorted(OUTCOME_ENTRY_KEYS),
            "outcomes": list(OUTCOMES),
            "rule": "Add an entry only when the owner supplies a real per-objective outcome.",
        },
        "not_held_by_the_project": list(NOT_HELD),
        "scope": {
            "ai_generated_objectives": {
                "generation_record_id": generation["record_id"],
                "generation_record_sha256": generation_sha256,
                "generation_record_status_preserved": PENDING_STATUS,
                "objective_count": len(ids),
                "chapter_count": len(chapters),
                "objective_ids": ids,
                "objectives_digest_by_source_id": {
                    c["source_id"]: objectives_digest(c) for c in chapters
                },
                "remain_labelled": "ai_generated (not official, not textbook-stated)",
            },
            "topics": {
                "applies_to_kinds": list(TOPIC_KINDS),
                "topic_list_digest_by_source_id": topic_digests,
                "not_covered": [
                    "chapter rows",
                    "heading_candidate rows",
                    "chapters without a numbered topic list",
                    "inventory topic_title (stays empty: one row per PDF)",
                ],
            },
            "not_covered": [
                "page quality review of OCR, maths or Hindi text"
                " (D-053; human_reviewed stays false)",
                "textbook-stated and source-derived objectives",
                "the inventory-level review_status column",
            ],
        },
    }


def write_once(path: Path, record: dict[str, Any]) -> tuple[Path, bool]:
    """Write the record unless identical content is already there; (path, was_written)."""
    data = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != data:
            raise RuntimeError(f"{path.name} exists with different content; records are immutable")
        return path, False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")
    return path, True


def validate_attestation(record: dict[str, Any]) -> None:
    """Raise ValueError if the attestation is malformed or claims more than it may."""
    if record.get("record_id") != RECORD_ID:
        raise ValueError("unexpected record_id")
    if record.get("review_completion") != REVIEW_COMPLETED:
        raise ValueError("review_completion must be completed_owner_attested")
    if record.get("default_approval_outcome") != NOT_RECORDED:
        raise ValueError("default approval outcome must stay not_individually_recorded")
    scope = record["scope"]["ai_generated_objectives"]
    known = scope["objective_ids"]
    if len(set(known)) != len(known) or len(known) != scope["objective_count"]:
        raise ValueError("attestation objective IDs are duplicated or miscounted")
    seen: set[str] = set()
    for entry in record.get("individual_outcomes", []):
        if set(entry) - OUTCOME_ENTRY_KEYS or not {"objective_id", "outcome"} <= set(entry):
            raise ValueError("individual outcome entries hold only objective_id/outcome/evidence")
        if entry["outcome"] not in OUTCOMES:
            raise ValueError(f"unknown outcome {entry['outcome']!r}")
        if entry["objective_id"] not in known:
            raise ValueError(f"outcome for unknown objective {entry['objective_id']!r}")
        if entry["objective_id"] in seen:
            raise ValueError(f"duplicate outcome for {entry['objective_id']!r}")
        seen.add(entry["objective_id"])


def load_attestation(path: Path = ATTESTATION_PATH) -> dict[str, Any]:
    """The validated attestation, or {} when absent (everything then stays pending)."""
    if not path.exists():
        return {}
    record = json.loads(path.read_text(encoding="utf-8"))
    validate_attestation(record)
    return record


def _pending() -> dict[str, Any]:
    return {
        "review_completion": REVIEW_PENDING,
        "approval_outcome": None,
        "review_status": PENDING_STATUS,
        "validation_record": None,
    }


def objective_validation(
    attestation: dict[str, Any], chapter: dict[str, Any], objective_id: str
) -> dict[str, Any]:
    """Review state of one generated objective; pending unless the attestation binds to it."""
    if not attestation:
        return _pending()
    scope = attestation["scope"]["ai_generated_objectives"]
    if scope["objectives_digest_by_source_id"].get(chapter["source_id"]) != objectives_digest(
        chapter
    ):
        return _pending()  # an ID, text, evidence term or the chapter identity changed
    if objective_id not in scope["objective_ids"]:
        return _pending()
    outcome = NOT_RECORDED
    for entry in attestation.get("individual_outcomes", []):
        if entry["objective_id"] == objective_id:
            outcome = entry["outcome"]
    return {
        "review_completion": REVIEW_COMPLETED,
        "approval_outcome": outcome,
        "review_status": OUTCOME_STATUS[outcome],
        "validation_record": attestation["record_id"],
    }


def topic_validation(
    attestation: dict[str, Any], source_id: str, rows: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Review state for a chapter's numbered topic list; None if it is not covered."""
    if not attestation:
        return None
    bound = attestation["scope"]["topics"]["topic_list_digest_by_source_id"]
    digest = topic_list_digest(source_id, rows)
    if digest is None or bound.get(source_id) != digest:
        return None
    return {
        "review_completion": REVIEW_COMPLETED,
        "approval_outcome": NOT_RECORDED,
        "review_status": OUTCOME_STATUS[NOT_RECORDED],
        "validation_record": attestation["record_id"],
    }


def aggregate(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Combined state for several items: completed only if all are, outcome only if uniform."""
    if not items or any(i.get("review_completion") != REVIEW_COMPLETED for i in items):
        return _pending()
    outcomes = {i["approval_outcome"] for i in items}
    outcome = next(iter(outcomes)) if len(outcomes) == 1 else "mixed"
    return {
        "review_completion": REVIEW_COMPLETED,
        "approval_outcome": outcome,
        "review_status": OUTCOME_STATUS.get(outcome, MIXED_STATUS),
        "validation_record": items[0]["validation_record"],
    }


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if args != ["record"]:
        print("usage: python -m data_pipeline.teacher_validation record", file=sys.stderr)
        return 2
    generation = json.loads(GENERATION_PATH.read_text(encoding="utf-8"))
    with TOPIC_MAPPING_PATH.open(encoding="utf-8", newline="") as handle:
        topic_rows = list(csv.DictReader(handle))
    try:
        record = build_attestation(generation, topic_rows, sha256_file(GENERATION_PATH))
        path, written = write_once(ATTESTATION_PATH, record)
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4
    print(f"{path.relative_to(PROJECT_ROOT)} ({'written' if written else 'unchanged'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
