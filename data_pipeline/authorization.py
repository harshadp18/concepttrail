"""Purpose-specific authorisation overlay and the rights gate for local processing.

The inventory permission fields are never rewritten. Authorisations are separate,
append-only audit records in `data_pipeline/data/overrides/authorizations/`. Each record
names its basis, scope, uses and the exact documents (source_id + SHA-256) it covers.

`check_use()` is the gate every processing stage calls. A use is permitted only when a
record explicitly grants it for that document's exact bytes. Two owner records exist:

- `AUTH-2026-10-31-owner-local-hackathon-processing` (D-034): local extraction, OCR,
  normalisation and quality evaluation only.
- `AUTH-2026-10-31-owner-project-use` (D-050): the owner's confirmation of rights for the
  intended ConceptTrail use, adding metadata enrichment, AI-assisted objective drafting
  and quality review, indexing/retrieval and in-platform display.

Training/fine-tuning and redistribution are refused by the gate whatever a record says:
they need a dedicated authorisation that does not exist yet. External providers for
embeddings or answer generation are not granted by either record.

    python -m data_pipeline.authorization record-owner-local-processing
    python -m data_pipeline.authorization record-owner-project-use
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUTHORIZATION_DIR = PROJECT_ROOT / "data_pipeline/data/overrides/authorizations"
CLEANED_INVENTORY = (
    PROJECT_ROOT / "resources/teammate_csv/processed/cleaned/curriculum_inventory.cleaned.csv"
)

PERMITTED = "permitted"

LOCAL_USES = (
    "local_pdf_extraction",
    "local_ocr",
    "local_text_normalization",
    "local_extraction_quality_evaluation",
)
# Granted only by the owner project-use record (D-050), never by the local record.
PROJECT_USES = (
    "local_metadata_enrichment",
    "ai_assisted_objective_generation",
    "ai_assisted_quality_review",
    "indexing_retrieval",
    "student_facing_display",
)
# Never granted by a local-processing record; each needs its own reviewed authorisation.
EXTERNAL_OR_RESTRICTED_USES = (
    "external_gemini_processing",
    "external_groq_processing",
    "deepseek_processing",
    "third_party_ocr",
    "external_embedding",
    "cloud_ai_processing",
    "student_facing_display",
    "redistribution",
    "model_training_or_fine_tuning",
)

# Refused by the gate even if a record lists them: they need a dedicated authorisation.
SEPARATE_AUTHORIZATION_ONLY = ("model_training_or_fine_tuning", "redistribution")
KNOWN_USES = frozenset(LOCAL_USES + PROJECT_USES + EXTERNAL_OR_RESTRICTED_USES)

OWNER_LOCAL_RECORD_ID = "AUTH-2026-10-31-owner-local-hackathon-processing"
OWNER_PROJECT_RECORD_ID = "AUTH-2026-10-31-owner-project-use"


@dataclass(frozen=True)
class Decision:
    use: str
    permitted: bool
    reason: str
    record_id: str | None = None


def owner_local_processing_record(inventory_rows: list[dict[str, str]]) -> dict[str, Any]:
    """Build the owner-attestation record for the accepted inventory rows (deterministic)."""
    documents = sorted(
        ({"source_id": r["source_id"], "sha256": r["sha256"]} for r in inventory_rows),
        key=lambda d: d["source_id"],
    )
    return {
        "record_id": OWNER_LOCAL_RECORD_ID,
        "recorded_on": "2026-10-31",
        "authorization_basis": "owner_attestation",
        "statement": (
            "The project owner stated that the textbook documents are approved for hackathon"
            " use and instructed that local extraction and local processing be permitted."
        ),
        "nature": "Owner-provided authorisation assertion; not independent legal verification.",
        "scope": "local_hackathon_processing",
        "uses": dict.fromkeys(LOCAL_USES, PERMITTED),
        "not_covered": list(EXTERNAL_OR_RESTRICTED_USES),
        "inventory_field_overlay": {
            "permitted_processing": {
                "overlay_value": PERMITTED,
                "applies_to": "local extraction, OCR, normalisation and quality evaluation only",
                "original_value_preserved": "permission_required",
            },
            "permitted_indexing": {"overlay_value": None, "note": "unchanged; not covered"},
            "permitted_display": {"overlay_value": None, "note": "unchanged; not covered"},
            "permitted_training": {"overlay_value": None, "note": "stays not_permitted"},
        },
        "eligibility": (
            "Rows accepted by Phase 3 cleaning (`curriculum_inventory.cleaned.csv`). The three"
            " quarantined rows are excluded until their review issues are resolved."
        ),
        "evidence_reference_status": "owner_statement_only; no written licence or permission"
        " letter on file",
        "review_status": "owner_attested_pending_rights_review",
        "document_count": len(documents),
        "documents_sha256": hashlib.sha256(json.dumps(documents).encode()).hexdigest(),
        "documents": documents,
    }


def owner_project_use_record(inventory_rows: list[dict[str, str]]) -> dict[str, Any]:
    """The owner's confirmation of rights for the intended ConceptTrail use (deterministic)."""
    documents = sorted(
        ({"source_id": r["source_id"], "sha256": r["sha256"]} for r in inventory_rows),
        key=lambda d: d["source_id"],
    )
    return {
        "record_id": OWNER_PROJECT_RECORD_ID,
        "recorded_on": "2026-10-31",
        "authorization_basis": "owner_attestation",
        "statement": (
            "I confirm that we have the rights required to use these materials for the"
            " intended ConceptTrail project."
        ),
        "nature": "Owner-provided authorisation assertion; not independent legal verification.",
        "scope": "conceptrail_project_use",
        "uses": dict.fromkeys(LOCAL_USES + PROJECT_USES, PERMITTED),
        "use_definitions": {
            "local_metadata_enrichment": "derive inventory metadata from local extraction",
            "ai_assisted_objective_generation": (
                "an AI model may read chapter text to draft learning objectives; drafts carry"
                " AI provenance and stay pending teacher review"
            ),
            "ai_assisted_quality_review": (
                "an AI model may compare page images with extracted/OCR text; findings are"
                " recorded separately from human review"
            ),
            "indexing_retrieval": (
                "build and query a search index of this content inside ConceptTrail; the"
                " choice of an external embedding provider is not decided by this record"
            ),
            "student_facing_display": "display authorised content within the platform",
        },
        "not_covered": [
            "model_training_or_fine_tuning",
            "redistribution",
            "third_party_ocr",
            "external_embedding_provider_selection",
            "external_llm_answer_generation",
        ],
        "inventory_field_overlay": {
            "rights_status": {
                "overlay_value": "approved",
                "original_value_preserved": "review_required",
            },
            "permitted_processing": {
                "overlay_value": PERMITTED,
                "original_value_preserved": "permission_required",
            },
            "permitted_indexing": {
                "overlay_value": PERMITTED,
                "original_value_preserved": "permission_required",
            },
            "permitted_display": {
                "overlay_value": PERMITTED,
                "original_value_preserved": "permission_required",
            },
            "permitted_training": {"overlay_value": None, "note": "stays not_permitted"},
        },
        "eligibility": (
            "Rows accepted by Phase 3 cleaning (`curriculum_inventory.cleaned.csv`). The three"
            " quarantined rows are excluded until their review issues are resolved."
        ),
        "evidence_reference_status": "owner_statement_only; no written licence or permission"
        " letter on file",
        "review_status": "owner_attested",
        "decision_reference": "docs/DECISIONS.md D-050",
        "document_count": len(documents),
        "documents_sha256": hashlib.sha256(json.dumps(documents).encode()).hexdigest(),
        "documents": documents,
    }


def load_records(directory: Path = AUTHORIZATION_DIR) -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(directory.glob("*.json"))]


def check_use(
    source_id: str, sha256: str, use: str, records: list[dict[str, Any]] | None = None
) -> Decision:
    if use in SEPARATE_AUTHORIZATION_ONLY:
        return Decision(use, False, "requires a dedicated authorisation; none exists")
    if use not in KNOWN_USES:
        return Decision(use, False, "unknown use; refusing by default")
    for record in records if records is not None else load_records():
        if record.get("uses", {}).get(use) != PERMITTED:
            continue
        for doc in record.get("documents", []):
            if doc["source_id"] == source_id:
                if doc["sha256"] != sha256:
                    return Decision(
                        use, False, "authorised bytes differ from this file", record["record_id"]
                    )
                return Decision(use, True, record["authorization_basis"], record["record_id"])
    return Decision(use, False, "no authorisation record grants this use for this document")


def write_record(record: dict[str, Any], directory: Path = AUTHORIZATION_DIR) -> Path:
    """Write once. An existing record may only be rewritten with identical content."""
    path = directory / f"{record['record_id']}.json"
    data = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != data:
            raise RuntimeError(f"{path.name} exists with different content; records are immutable")
        return path
    directory.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record purpose-specific authorisations.")
    parser.add_argument(
        "command", choices=["record-owner-local-processing", "record-owner-project-use"]
    )
    parser.add_argument("--inventory", type=Path, default=CLEANED_INVENTORY)
    args = parser.parse_args(argv)
    with args.inventory.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    try:
        build = (
            owner_project_use_record
            if args.command == "record-owner-project-use"
            else owner_local_processing_record
        )
        path = write_record(build(rows))
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4
    print(f"{path.relative_to(PROJECT_ROOT)}: {len(rows)} documents")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
