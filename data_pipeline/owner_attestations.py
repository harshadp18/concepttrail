"""Owner attestations that close the Phase 4 extraction pilot: D-053 page review and sign-off.

Two write-once, evidence-bound records, in the private overrides area (same pattern as
`teacher_validation.py`):

1. **D-053 page-quality review.** The owner confirms the human page-quality review is
   completed. The AI-assisted review CSV is never edited: its `human_reviewed=false` rows stay
   as the historical evidence. The attestation sets the *effective* state
   (`human_reviewed=true`, basis `owner_attestation`) for exactly the 22 pages in that CSV and
   is bound to the SHA-256 of the CSV, its summary and the inspection index. Individual page
   findings, reviewer identities and corrections are **not** held by the project and are
   recorded as not recorded, never invented.
2. **Phase 4 pilot sign-off.** The owner approves the pilot and its recorded quality-gate
   results. The record binds to the pilot reports, manifests and the other attestations by
   SHA-256 and carries the recorded warnings and limitations computed from that evidence. It
   does not claim that any page or objective was individually approved.

Both fail closed: a missing, edited-evidence (`stale`) or malformed (`invalid`) attestation
never counts as completed review or approval. Records are written once; a repeat run with the
same evidence changes nothing, and with changed evidence refuses to overwrite.

    python -m data_pipeline.owner_attestations record-d053
    python -m data_pipeline.owner_attestations record-signoff
    python -m data_pipeline.owner_attestations verify
"""

from __future__ import annotations

import collections
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from data_pipeline import teacher_validation as tv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ME = "data_pipeline/data/overrides/metadata_enrichment"
QR = "data_pipeline/data/overrides/quality_review"
EP = "data_pipeline/data/logs/extraction_pilot"
PE = "data_pipeline/data/processed/metadata_enrichment"
REL = {
    "d053": f"{ME}/d053_page_review_attestation_2026-10-31.json",
    "signoff": f"{ME}/phase4_pilot_signoff_2026-10-31.json",
    "teacher": f"{ME}/teacher_validation_attestation_2026-10-31.json",
    "review_csv": f"{QR}/ai_assisted_page_review_2026-10-31.csv",
    "review_md": f"{QR}/ai_assisted_page_review_2026-10-31.md",
    "inspection_index": f"{EP}/inspection/index.json",
}
D053_RECORD_ID = "OWNER-ATTESTATION-2026-10-31-d053-page-review"
SIGNOFF_RECORD_ID = "OWNER-SIGNOFF-2026-10-31-phase4-pilot"
D053_REFERENCE = "private decision register, D-053"
SIGNOFF_DATE = "2026-10-31"
VALID, ABSENT, STALE, INVALID = "valid", "absent", "stale", "invalid"
# Evidence the sign-off is bound to. Reports are private; their hashes are not content.
SIGNOFF_EVIDENCE = {
    "pilot_report": "docs/reports/PHASE_4_EXTRACTION_PILOT_REPORT.md",
    "continuation_report": "docs/reports/PHASE_4_CONTINUATION_REPORT.md",
    "owner_decisions_report": "docs/reports/PHASE_4_OWNER_DECISIONS_REPORT.md",
    "reconciliation_report": "docs/reports/PHASE_4_FINAL_RECONCILIATION_REPORT.md",
    "run_manifest": f"{EP}/run_manifest.json",
    "quality_report": f"{EP}/quality_report.json",
    "provenance_manifest": f"{PE}/provenance_manifest.json",
    "pilot_csv_manifest": f"{PE}/curriculum_inventory.pilot_enriched.manifest.json",
    "review_triage": f"{PE}/human_review_queue.triage.json",
    "page_review_csv": REL["review_csv"],
    "d053_attestation": REL["d053"],
    "teacher_validation_attestation": REL["teacher"],
    "project_use_authorization": (
        "data_pipeline/data/overrides/authorizations/AUTH-2026-10-31-owner-project-use.json"
    ),
}
NOT_HELD_D053 = (
    "reviewer identities",
    "per-page human findings (accurate, missing, incorrect, layout)",
    "corrections made as a result of the review",
    "OCR, Hindi or maths accuracy measurements",
    "review dates or durations",
)
NOT_CLAIMED = (
    "that every reviewed page passed or is free of defects",
    "that any text was corrected",
    "that any individual page, objective or topic was separately approved",
    "independent verification of the owner's confirmation",
    "that Phase 5 has started or that its prerequisites are validated",
)


class AttestationError(RuntimeError):
    """Evidence is missing or inconsistent; nothing was written."""


def _ref(root: Path, rel: str) -> dict[str, str]:
    path = root / rel
    if not path.is_file():
        raise AttestationError(f"required evidence is missing: {rel}")
    return {"path": rel, "sha256": tv.sha256_file(path)}


def _digest(payload: Any) -> str:
    data = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def reviewed_pages(root: Path = PROJECT_ROOT) -> list[tuple[str, int]]:
    """The pages in the AI-assisted review record, sorted: the attested page set."""
    with (root / REL["review_csv"]).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return sorted({(r["source_id"], int(r["pdf_page_index"])) for r in rows})


# --- D-053 --------------------------------------------------------------------------------


def build_d053(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    refs = {name: _ref(root, REL[name]) for name in ("review_csv", "review_md", "inspection_index")}
    with (root / REL["review_csv"]).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or any(
        r["human_reviewed"] != "false" or not r["reviewer"].startswith("ai_assisted:") for r in rows
    ):
        raise AttestationError("the page-review CSV must be the unedited AI-assisted record")
    pages = [[sid, index] for sid, index in reviewed_pages(root)]
    return {
        "record_id": D053_RECORD_ID,
        "recorded_on": SIGNOFF_DATE,
        "authorization_basis": "owner_attestation",
        "decision_reference": D053_REFERENCE,
        "statement": (
            "The owner confirms that the D-053 human page-quality review has been completed."
        ),
        "nature": (
            "Owner-provided attestation of review completion. It is not an independently"
            " verified reviewer record and carries no reviewer identity."
        ),
        "review_completion": tv.REVIEW_COMPLETED,
        "effective_status": {"human_reviewed": True, "basis": "owner_attestation"},
        "historical_evidence_preserved": (
            "The AI-assisted review CSV keeps human_reviewed=false on every row. That is the"
            " historical value; the effective state comes from this attestation."
        ),
        "bound_evidence": refs,
        "pages_in_scope": pages,
        "page_count": len(pages),
        "pages_digest": _digest(pages),
        "individual_findings_status": "not_recorded",
        "not_held_by_the_project": list(NOT_HELD_D053),
        "not_claimed": list(NOT_CLAIMED),
        "not_covered": [
            "pages outside the page set above (other queue items stay open)",
            "proofreading of the flagged Hindi words and transcription of maths equations",
            "teacher validation of objectives and topics (separate attestation)",
        ],
    }


def _validate_d053_shape(record: dict[str, Any]) -> None:
    if record.get("record_id") != D053_RECORD_ID:
        raise ValueError("unexpected record_id")
    if record.get("authorization_basis") != "owner_attestation":
        raise ValueError("basis must be owner_attestation")
    if record.get("effective_status") != {"human_reviewed": True, "basis": "owner_attestation"}:
        raise ValueError("effective_status must name owner_attestation as the basis")
    if record.get("individual_findings_status") != "not_recorded":
        raise ValueError("individual findings must stay not_recorded")
    if _digest(record["pages_in_scope"]) != record.get("pages_digest"):
        raise ValueError("page set does not match its digest")


def _verify_bound(root: Path, refs: dict[str, dict[str, str]]) -> list[str]:
    problems = []
    for name, ref in sorted(refs.items()):
        path = root / ref["path"]
        if not path.is_file():
            problems.append(f"{name}: evidence file is missing ({ref['path']})")
        elif tv.sha256_file(path) != ref["sha256"]:
            problems.append(f"{name}: evidence changed since attestation ({ref['path']})")
    return problems


def verify_d053(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """`valid` only if the attestation exists, is well formed and its evidence is unchanged."""
    path = root / REL["d053"]
    if not path.exists():
        return {"status": ABSENT, "problems": ["D-053 attestation file not found"], "pages": []}
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        _validate_d053_shape(record)
    except (ValueError, KeyError, TypeError) as exc:
        return {"status": INVALID, "problems": [f"malformed attestation: {exc}"], "pages": []}
    problems = _verify_bound(root, record["bound_evidence"])
    if not problems and [list(p) for p in reviewed_pages(root)] != record["pages_in_scope"]:
        problems.append("page set in the review CSV changed since attestation")
    return {
        "status": STALE if problems else VALID,
        "problems": problems,
        "attestation_sha256": tv.sha256_file(path),
        "pages": record["pages_in_scope"] if not problems else [],
    }


def effective_page_review(
    rows: list[dict[str, str]], verdict: dict[str, Any]
) -> list[dict[str, Any]]:
    """Each review row with its historical and effective `human_reviewed` (never edits `rows`)."""
    covered = {(sid, index) for sid, index in verdict.get("pages", [])}
    out = []
    for row in rows:
        key = (row["source_id"], int(row["pdf_page_index"]))
        effective = verdict["status"] == VALID and key in covered
        out.append(
            {
                **row,
                "human_reviewed_historical": row["human_reviewed"],
                "human_reviewed_effective": effective,
                "effective_basis": "owner_attestation" if effective else None,
            }
        )
    return out


# --- sign-off ----------------------------------------------------------------------------


def quality_gate_summary(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """The recorded quality-gate results, computed from the bound evidence (nothing added)."""
    quality = json.loads((root / SIGNOFF_EVIDENCE["quality_report"]).read_text(encoding="utf-8"))
    run = json.loads((root / SIGNOFF_EVIDENCE["run_manifest"]).read_text(encoding="utf-8"))
    triage = json.loads((root / SIGNOFF_EVIDENCE["review_triage"]).read_text(encoding="utf-8"))
    prov = json.loads((root / SIGNOFF_EVIDENCE["provenance_manifest"]).read_text(encoding="utf-8"))
    ocr: collections.Counter[str] = collections.Counter()
    findings: collections.Counter[str] = collections.Counter()
    for metrics in quality.values():
        ocr.update(metrics["ocr"]["statuses"])
        findings.update(f["code"] for f in metrics["findings"])
    repair = next(
        (d["devanagari_repair"] for d in run["documents"] if d.get("devanagari_repair")), None
    )
    return {
        "documents": len(quality),
        "pages_processed": sum(m["pages"] for m in quality.values()),
        "extraction_failures": sum(m["extraction_failures"] for m in quality.values()),
        "ocr_page_statuses": dict(sorted(ocr.items())),
        "quality_findings_by_code": dict(sorted(findings.items())),
        "pipeline_versions": run["versions"],
        "database_writes": run["database_writes"],
        "external_ai_calls": run["external_ai_calls"],
        "review_triage": triage["dispositions"],
        "review_triage_by_item": triage["by_item"],
        "new_review_items": triage["new_items_by_kind"],
        "teacher_validation": prov.get("teacher_validation"),
        "hindi_repair": repair
        and {
            k: repair[k]
            for k in (
                "rule",
                "corrections_total",
                "repeated_vowel_signs_remaining",
                "other_repeats_flagged",
            )
        },
    }


def build_signoff(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    d053 = verify_d053(root)
    if d053["status"] != VALID:
        raise AttestationError(f"D-053 attestation is not valid ({d053['status']})")
    try:
        tv.load_attestation(root / REL["teacher"])
    except (ValueError, KeyError) as exc:
        raise AttestationError(f"teacher-validation attestation is invalid: {exc}") from None
    evidence = {name: _ref(root, rel) for name, rel in SIGNOFF_EVIDENCE.items()}
    gate = quality_gate_summary(root)
    if (gate["teacher_validation"] or {}).get("status") != "applied":
        raise AttestationError("pipeline provenance does not show teacher validation applied")
    run = json.loads((root / SIGNOFF_EVIDENCE["run_manifest"]).read_text(encoding="utf-8"))
    documents = [
        {
            "source_id": d["source_id"],
            "inventory_id": d["inventory_id"],
            "pdf_sha256": d["sha256_before"],
        }
        for d in run["documents"]
        if d["status"] == "processed"
    ]
    return {
        "record_id": SIGNOFF_RECORD_ID,
        "recorded_on": SIGNOFF_DATE,
        "decision": "approved",
        "signed_off_on": SIGNOFF_DATE,
        "basis": "owner_approval",
        "statement": (
            "The project owner approves the Phase 4 extraction pilot and its recorded"
            " quality-gate results."
        ),
        "nature": "Owner approval. It is not an independent audit and not legal verification.",
        "scope": {"pilot_documents": documents, "pages_processed": gate["pages_processed"]},
        "bound_evidence": evidence,
        "recorded_quality_gate_results": gate,
        "retained_limitations": [
            "individual page findings of the D-053 review are not recorded",
            "individual teacher approval outcomes are not recorded (completion is attested only)",
            "Hindi residue is flagged for proofreading, not corrected",
            "maths display equations need transcription from the page image",
            "review-queue items that are still open are listed in recorded_quality_gate_results",
            "test-suite and fresh-clone results are not part of the bound evidence",
        ],
        "does_not_claim": list(NOT_CLAIMED),
        "next_phase": (
            "Phase 5 is the next phase; it has not started and its prerequisites are not validated"
        ),
    }


def verify_signoff(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    path = root / REL["signoff"]
    if not path.exists():
        return {"status": ABSENT, "problems": ["sign-off file not found"]}
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("record_id") != SIGNOFF_RECORD_ID or record.get("decision") != "approved":
            raise ValueError("record_id or decision is not as expected")
        if record.get("basis") != "owner_approval" or record.get("signed_off_on") != SIGNOFF_DATE:
            raise ValueError("basis or sign-off date is not as expected")
        refs = record["bound_evidence"]
        if set(refs) != set(SIGNOFF_EVIDENCE):
            raise ValueError("bound evidence set differs from the required set")
    except (ValueError, KeyError, TypeError) as exc:
        return {"status": INVALID, "problems": [f"malformed sign-off: {exc}"]}
    problems = _verify_bound(root, refs)
    d053 = verify_d053(root)
    if d053["status"] != VALID:
        problems.append(f"D-053 attestation is {d053['status']}")
    return {
        "status": STALE if problems else VALID,
        "problems": problems,
        "signoff_sha256": tv.sha256_file(path),
    }


# --- CLI -----------------------------------------------------------------------------------


def _write(rel: str, record: dict[str, Any], root: Path = PROJECT_ROOT) -> tuple[Path, bool]:
    return tv.write_once(root / rel, record)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    commands = {"record-d053", "record-signoff", "verify"}
    if len(args) != 1 or args[0] not in commands:
        print(
            "usage: python -m data_pipeline.owner_attestations [record-d053|record-signoff|verify]",
            file=sys.stderr,
        )
        return 2
    try:
        if args[0] == "record-d053":
            path, written = _write(REL["d053"], build_d053())
        elif args[0] == "record-signoff":
            path, written = _write(REL["signoff"], build_signoff())
        else:
            report = {"d053": verify_d053(), "signoff": verify_signoff()}
            report["teacher_validation"] = {
                "status": VALID if tv.load_attestation(PROJECT_ROOT / REL["teacher"]) else ABSENT
            }
            report["d053"] = {k: v for k, v in report["d053"].items() if k != "pages"}
            print(json.dumps(report, indent=2, default=str))
            return 0 if all(v["status"] == VALID for v in report.values()) else 1
    except (AttestationError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4
    print(f"{path.relative_to(PROJECT_ROOT)} ({'written' if written else 'unchanged'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
