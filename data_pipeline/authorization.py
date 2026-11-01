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
    python -m data_pipeline.authorization record-owner-project-use --wording-file PRIVATE.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Overridable so a container can mount the private records read-only at a fixed path.
AUTHORIZATION_DIR = Path(
    os.environ.get(
        "CONCEPTTRAIL_AUTHORIZATION_DIR",
        str(PROJECT_ROOT / "data_pipeline/data/overrides/authorizations"),
    )
)
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

# Phase 5 local drafting with Qwen through Ollama (D17). Granted by neither existing record:
# only a separate owner record naming these uses can permit them.
DRAFTING_USES = ("local_llm_kc_drafting", "local_llm_prerequisite_edge_drafting")
# Local Qwen question drafting and evidence-grounded explanation generation from textbook
# content. Neither is implied by objective drafting or by indexing; no record grants them.
GENERATION_USES = ("local_llm_question_drafting", "local_llm_explanation_generation")

# Refused by the gate even if a record lists them: they need a dedicated authorisation.
SEPARATE_AUTHORIZATION_ONLY = ("model_training_or_fine_tuning", "redistribution")
KNOWN_USES = frozenset(
    LOCAL_USES + PROJECT_USES + EXTERNAL_OR_RESTRICTED_USES + DRAFTING_USES + GENERATION_USES
)

OWNER_LOCAL_RECORD_ID = "AUTH-2026-10-31-owner-local-hackathon-processing"
OWNER_PROJECT_RECORD_ID = "AUTH-2026-10-31-owner-project-use"


@dataclass(frozen=True)
class Decision:
    use: str
    permitted: bool
    reason: str
    record_id: str | None = None


# Public, generic wording for NEW records. The wording of the existing historical records is
# private: it is supplied at record time from a private file (`--wording-file`), never kept in
# published source. `check_use` never reads any of these fields.
GENERIC_WORDING = {
    "statement": "Owner-provided authorisation for the scope stated in this record.",
    "evidence_reference_status": "owner_statement_only",
    "review_status": "owner_attested",
}
WORDING_KEYS = frozenset({*GENERIC_WORDING, "decision_reference"})


def resolve_wording(wording: dict[str, str] | None) -> dict[str, str]:
    """Generic wording unless a private wording is supplied; unknown or empty keys are refused."""
    if wording is None:
        return dict(GENERIC_WORDING)
    if set(wording) - WORDING_KEYS or any(
        not isinstance(v, str) or not v for v in wording.values()
    ):
        raise ValueError(
            "wording may only set non-empty string values for " + ", ".join(sorted(WORDING_KEYS))
        )
    return {**GENERIC_WORDING, **wording}


def owner_local_processing_record(
    inventory_rows: list[dict[str, str]], wording: dict[str, str] | None = None
) -> dict[str, Any]:
    """Build the owner-attestation record for the accepted inventory rows (deterministic)."""
    w = resolve_wording(wording)
    documents = sorted(
        ({"source_id": r["source_id"], "sha256": r["sha256"]} for r in inventory_rows),
        key=lambda d: d["source_id"],
    )
    return {
        "record_id": OWNER_LOCAL_RECORD_ID,
        "recorded_on": "2026-10-31",
        "authorization_basis": "owner_attestation",
        "statement": w["statement"],
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
        "evidence_reference_status": w["evidence_reference_status"],
        "review_status": w["review_status"],
        "document_count": len(documents),
        "documents_sha256": hashlib.sha256(json.dumps(documents).encode()).hexdigest(),
        "documents": documents,
    }


def owner_project_use_record(
    inventory_rows: list[dict[str, str]], wording: dict[str, str] | None = None
) -> dict[str, Any]:
    """The owner's confirmation of rights for the intended ConceptTrail use (deterministic)."""
    w = resolve_wording(wording)
    documents = sorted(
        ({"source_id": r["source_id"], "sha256": r["sha256"]} for r in inventory_rows),
        key=lambda d: d["source_id"],
    )
    return {
        "record_id": OWNER_PROJECT_RECORD_ID,
        "recorded_on": "2026-10-31",
        "authorization_basis": "owner_attestation",
        "statement": w["statement"],
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
        "evidence_reference_status": w["evidence_reference_status"],
        "review_status": w["review_status"],
        **({"decision_reference": w["decision_reference"]} if "decision_reference" in w else {}),
        "document_count": len(documents),
        "documents_sha256": hashlib.sha256(json.dumps(documents).encode()).hexdigest(),
        "documents": documents,
    }


OWNER_DEMO_RECORD_ID = "AUTH-2026-11-01-owner-demo-content-generation"


def owner_demo_generation_record(inventory_rows: list[dict[str, str]]) -> dict[str, Any]:
    """The owner's instruction (2026-11-01) to generate original demo content locally.

    Grants only the local-model drafting and generation uses. It is a rights record, not a
    review: everything generated under it is AI-generated demo content, never human-approved.
    """
    documents = sorted(
        ({"source_id": r["source_id"], "sha256": r["sha256"]} for r in inventory_rows),
        key=lambda d: d["source_id"],
    )
    return {
        "record_id": OWNER_DEMO_RECORD_ID,
        "recorded_on": "2026-11-01",
        "authorization_basis": "owner_instruction",
        "statement": (
            "The project owner authorised using the supplied textbook PDFs as local educational"
            " references to generate original ConceptTrail learning content (knowledge"
            " components, prerequisite edges, questions, explanations) for a development/demo"
            " dataset, with the local model only."
        ),
        "nature": "Owner instruction given in a working session; not independent legal review.",
        "scope": "local_development_demo_content",
        "uses": dict.fromkeys(DRAFTING_USES + GENERATION_USES, PERMITTED),
        "conditions": [
            "local inference only (Ollama); no external or cloud provider",
            "original wording; no copying of exercises or long passages",
            "generated content is labelled AI-generated demo content and is never treated as"
            " human-approved or production-released",
        ],
        "not_covered": [
            "external_llm_processing",
            "model_training_or_fine_tuning",
            "redistribution",
            "production_release_or_human_approval",
        ],
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
    parser.add_argument(
        "--wording-file",
        type=Path,
        help="private JSON with wording for a legacy record; without it, generic wording is used",
    )
    args = parser.parse_args(argv)
    with args.inventory.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    try:
        build = (
            owner_project_use_record
            if args.command == "record-owner-project-use"
            else owner_local_processing_record
        )
        wording = (
            json.loads(args.wording_file.read_text(encoding="utf-8")) if args.wording_file else None
        )
        path = write_record(build(rows, wording))
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4
    print(f"{path.relative_to(PROJECT_ROOT)}: {len(rows)} documents")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
