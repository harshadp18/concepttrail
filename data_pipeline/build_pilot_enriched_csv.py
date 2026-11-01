"""Derived, enriched copy of the 10 pilot inventory rows (never the master inventory).

Starts from the Phase 3 cleaned CSV and writes, in `data_pipeline/data/processed/
metadata_enrichment/`:

- `curriculum_inventory.pilot_enriched.csv`: the pilot rows in the exact 29 canonical
  columns, in cleaned-CSV order, one row per PDF.
- `.status.csv`: per row and field, whether a value was written, its value class
  (`verified`, `source_explicit`, `ai_generated`, `human_approved`, `candidate`,
  `unresolved`, `authorization_overlay`, `rule_derived`), status, origin, candidate count,
  evidence and reason.
- `.changes.csv`: every cell that differs from the cleaned CSV, with its basis.
- `.manifest.json`: input, output and sidecar hashes, IDs, rules and versions;
  `generated_at` is kept apart from the content digest.

Write rules (one canonical row per PDF):

- `topic_title`, `learning_objective`, `source_url`, `acquired_at` are written only when the
  value class is `verified`, `source_explicit`, `ai_generated` (D-049) or `human_approved`
  and the cleaned cell is empty. Candidates are never written; a non-empty cleaned value is
  never replaced. Only `learning_objective` may hold several values (` | `-separated);
  several topics stay in `topic_mapping.csv` (owner rule).
- Rights fields take the `inventory_field_overlay` values of every authorisation record
  that covers the document's exact bytes (D-034 local processing; D-050 owner project use).
  Each overlaid field must still hold the value the record says it overlays, and records
  must not disagree. `permission_reference` and `permitted_training` are never changed.
- `extraction_status` becomes `extracted` only when the D-051 rule passes (see
  `extraction_check`); review and OCR-quality state stay in their own fields and queue.
- `acquired_at` stays empty; the owner accepted `unknown` where no record exists (D-052).

Every input is hash-checked first; any mismatch stops the build without writing. Outputs
are rewritten whole on every run (never appended), so a rerun cannot duplicate rows.

    python -m data_pipeline.build_pilot_enriched_csv
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_pipeline.authorization import AUTHORIZATION_DIR, LOCAL_USES, check_use, load_records
from data_pipeline.clean_teammate_csv import atomic_write_bytes, csv_bytes, json_bytes
from data_pipeline.inventory_schema import CANONICAL_HEADER

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILDER_VERSION = "pilot-enriched-csv/2.1.0"
OUTPUT_STEM = "curriculum_inventory.pilot_enriched"

ENRICHED_FIELDS: dict[str, str] = {
    "topic_title": "topic_value_status",
    "learning_objective": "objective_value_status",
    "source_url": "url_value_status",
    "acquired_at": "acquisition_date_status",
}
WRITABLE_STATUSES = ("verified", "source_explicit", "ai_generated")
MULTI_VALUE_FIELDS = frozenset({"learning_objective"})
EXTRACTION_RULE = "D-051 pilot-extracted/1"
PAGE_PROVENANCE_KEYS = (
    "source_id",
    "pdf_sha256",
    "page_index",
    "extraction_method",
    "extracted_at",
    "pipeline_version",
)
TOPIC_KINDS = ("topic", "subtopic", "heading_candidate")
MULTI_VALUE_SEPARATOR = " | "
OVERLAY_FIELDS = (
    "rights_status",
    "permitted_processing",
    "permitted_indexing",
    "permitted_display",
)
NEVER_CHANGED = ("permission_reference", "permitted_training")
STATUS_HEADER = (
    "inventory_id",
    "source_id",
    "field",
    "written",
    "value_class",
    "value_status",
    "value_origin",
    "review_status",
    "review_completion",
    "approval_outcome",
    "confidence",
    "original_value",
    "written_value",
    "candidate_count",
    "candidate_reference",
    "evidence_reference",
    "reason",
)
CHANGES_HEADER = (
    "inventory_id",
    "source_id",
    "field",
    "original_value",
    "new_value",
    "change_basis",
    "authorization_record",
    "authorization_record_sha256",
    "evidence_reference",
)


@dataclass(frozen=True)
class Paths:
    cleaned_csv: Path
    phase3_manifest: Path
    run_manifest: Path
    enrichment_dir: Path
    authorization_dir: Path
    output_dir: Path
    owner_decisions: Path | None = None
    teacher_validation: Path | None = None
    artifact_root: Path = PROJECT_ROOT

    @classmethod
    def default(cls) -> Paths:
        enrichment = PROJECT_ROOT / "data_pipeline/data/processed/metadata_enrichment"
        return cls(
            cleaned_csv=PROJECT_ROOT
            / "resources/teammate_csv/processed/cleaned/curriculum_inventory.cleaned.csv",
            phase3_manifest=PROJECT_ROOT
            / "resources/teammate_csv/processed/manifests/curriculum_inventory.manifest.json",
            run_manifest=PROJECT_ROOT
            / "data_pipeline/data/logs/extraction_pilot/run_manifest.json",
            enrichment_dir=enrichment,
            authorization_dir=AUTHORIZATION_DIR,
            output_dir=enrichment,
            owner_decisions=PROJECT_ROOT
            / "data_pipeline/data/overrides/metadata_enrichment/owner_decisions_2026-10-31.json",
            teacher_validation=PROJECT_ROOT
            / "data_pipeline/data/overrides/metadata_enrichment"
            / "teacher_validation_attestation_2026-10-31.json",
        )


class BuildError(RuntimeError):
    """An input failed verification; nothing was written."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    resolved = path.resolve()
    if resolved.is_relative_to(PROJECT_ROOT):
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    return str(resolved)


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def value_class(status: str | None, origin: str | None) -> str:
    if origin == "human_approved":
        return "human_approved"
    if status in WRITABLE_STATUSES:
        return status
    if status == "source_derived_candidate":
        return "candidate"
    return "unresolved"


def decide(
    original: str,
    value: str | None,
    status: str | None,
    origin: str | None,
    field: str = "",
) -> tuple[bool, str]:
    """(written, reason) for one enriched field."""
    if value_class(status, origin) not in (*WRITABLE_STATUSES, "human_approved"):
        return False, f"status {status}: not written"
    if not value:
        return False, "no value"
    if MULTI_VALUE_SEPARATOR in value and field not in MULTI_VALUE_FIELDS:
        return False, "multiple values; kept in the sidecar mapping"
    if original and original != value:
        return False, "cleaned CSV already holds a different value; conflict left for review"
    if original == value:
        return False, "cleaned CSV already holds this value"
    return True, "written"


def candidate_summary(
    field: str, record: dict[str, Any], topics: list[dict[str, str]]
) -> tuple[int, str]:
    sid = record["source_document_id"]
    if field == "topic_title":
        rows = [t for t in topics if t["source_document_id"] == sid]
        kinds = {k: sum(1 for t in rows if t["kind"] == k) for k in TOPIC_KINDS}
        return sum(kinds.values()), "topic_mapping.csv: " + ", ".join(
            f"{n} {k}" for k, n in kinds.items()
        )
    if field == "learning_objective":
        counts = record.get("objective_counts_by_origin") or {}
        return sum(counts.values()), "learning_objective_mapping.csv: " + ", ".join(
            f"{k} {v}" for k, v in counts.items()
        )
    return 0, ""


def extraction_check(doc: dict[str, Any], row: dict[str, str], root: Path) -> dict[str, bool]:
    """D-051: may this pilot record be marked `extracted`? Each check is reported.

    OCR confidence and human review are deliberately not checks: they are recorded in the
    review queue and `review_status`, and `extracted` never means review-approved.
    """
    checks = {"processed_successfully": doc.get("status") == "processed"}
    checks["pdf_unchanged_during_processing"] = (
        doc.get("sha256_before") == doc.get("sha256_after") == row["sha256"]
    )
    raw_path = root / doc.get("raw_path", "")
    norm_path = root / doc.get("normalized_path", "")
    checks["raw_and_normalized_outputs_exist"] = raw_path.is_file() and norm_path.is_file()
    if not checks["raw_and_normalized_outputs_exist"]:
        return checks
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    norm = json.loads(norm_path.read_text(encoding="utf-8"))
    pages = raw["pages"]
    expected = (raw["document"].get("pdf_metadata") or {}).get("page_count")
    checks["every_page_has_a_result"] = bool(pages) and len(pages) == expected
    checks["page_provenance_recorded"] = all(
        all(p.get(k) is not None for k in PAGE_PROVENANCE_KEYS) and p["pdf_sha256"] == row["sha256"]
        for p in pages
    )
    checks["no_blocking_extraction_failures"] = not any(
        p.get("extraction_method") == "failed" for p in pages
    )
    checks["normalized_pages_reference_raw"] = len(norm["pages"]) == len(pages) and all(
        n["raw_ref"]["raw_text_sha256"] == hashlib.sha256(p.get("text", "").encode()).hexdigest()
        for n, p in zip(norm["pages"], pages, strict=False)
    )
    return checks


def rights_overlays(
    sid: str, digest: str, row: dict[str, str], records: list[dict[str, Any]], directory: Path
) -> dict[str, dict[str, Any]]:
    """Overlay value and granting records per field, from records covering these bytes."""
    found: dict[str, dict[str, Any]] = {}
    for record in records:
        if not any(
            d["source_id"] == sid and d["sha256"] == digest for d in record.get("documents", [])
        ):
            continue
        uses = [u for u, v in record.get("uses", {}).items() if v == "permitted"]
        if not uses or not all(check_use(sid, digest, u, [record]).permitted for u in uses):
            continue
        path = directory / f"{record['record_id']}.json"
        for field, overlay in record.get("inventory_field_overlay", {}).items():
            value = overlay.get("overlay_value")
            if value is None:
                continue
            if field not in OVERLAY_FIELDS:
                raise BuildError(f"{record['record_id']}: overlay of {field} is not allowed")
            if overlay.get("original_value_preserved") != row[field]:
                raise BuildError(f"{sid}: {field} is not the value {record['record_id']} overlays")
            entry = found.setdefault(field, {"value": value, "records": []})
            if entry["value"] != value:
                raise BuildError(f"{sid}: authorisation records disagree on {field}")
            entry["records"].append(
                {
                    "record_id": record["record_id"],
                    "sha256": sha256(path),
                    "path": rel(path),
                    "basis": record["authorization_basis"],
                    "scope": record["scope"],
                    "review_status": record["review_status"],
                    "applies_to": overlay.get("applies_to", record["scope"]),
                }
            )
    return found


def verify_inputs(paths: Paths) -> dict[str, Any]:
    """Check every input against the hash its producer recorded. Raises BuildError."""
    phase3 = json.loads(paths.phase3_manifest.read_text(encoding="utf-8"))
    cleaned_rel = rel(paths.cleaned_csv)
    recorded = phase3.get("outputs", {}).get(cleaned_rel)
    actual = sha256(paths.cleaned_csv)
    if recorded != actual:
        raise BuildError(f"cleaned CSV hash {actual} != Phase 3 manifest {recorded}")
    run = json.loads(paths.run_manifest.read_text(encoding="utf-8"))
    sidecars = {}
    for name in ("unified_enrichment.json", "topic_mapping.csv", "learning_objective_mapping.csv"):
        path = paths.enrichment_dir / name
        recorded_sidecar = run.get("enrichment_outputs", {}).get(name)
        actual_sidecar = sha256(path)
        if recorded_sidecar != actual_sidecar:
            raise BuildError(f"{name} hash {actual_sidecar} != pilot run manifest")
        sidecars[rel(path)] = actual_sidecar
    return {
        "phase3_run_id": phase3.get("run_id"),
        "cleaned_csv": {cleaned_rel: actual},
        "phase3_manifest": {rel(paths.phase3_manifest): sha256(paths.phase3_manifest)},
        "pilot_run_manifest_versions": run.get("versions"),
        "sidecars": sidecars,
        "run": run,
    }


def build(paths: Paths, now: datetime | None = None) -> dict[str, Any]:
    checks = verify_inputs(paths)
    run = checks.pop("run")
    header, cleaned = read_csv(paths.cleaned_csv)
    if tuple(header) != CANONICAL_HEADER:
        raise BuildError("cleaned CSV header differs from the 29-column canonical header")

    pilot = [d for d in run["documents"] if d["status"] == "processed"]
    pilot_ids = {d["inventory_id"]: d for d in pilot}
    if len(pilot_ids) != len(pilot):
        raise BuildError("duplicate inventory_id in the pilot run manifest")
    by_id: dict[str, list[dict[str, str]]] = {}
    for row in cleaned:
        by_id.setdefault(row["inventory_id"], []).append(row)
    for inventory_id, doc in pilot_ids.items():
        rows = by_id.get(inventory_id, [])
        if len(rows) != 1:
            raise BuildError(f"{inventory_id}: {len(rows)} cleaned rows (expected exactly 1)")
        row = rows[0]
        if row["source_id"] != doc["source_id"] or row["sha256"] != doc["sha256_before"]:
            raise BuildError(f"{inventory_id}: source_id/sha256 differ from the pilot run")

    records = load_records(paths.authorization_dir)
    owner = (
        json.loads(paths.owner_decisions.read_text(encoding="utf-8"))
        if paths.owner_decisions is not None and paths.owner_decisions.exists()
        else {"decisions": {}}
    )
    decisions = owner["decisions"]
    accept_unknown = (decisions.get("acquired_at") or {}).get("status") == "accept_unknown"
    extraction_approved = (decisions.get("extraction_status") or {}).get("status") == "approved"
    unified = json.loads((paths.enrichment_dir / "unified_enrichment.json").read_text("utf-8"))
    by_source = {u["source_document_id"]: u for u in unified}
    _, topics = read_csv(paths.enrichment_dir / "topic_mapping.csv")

    out_rows, status_rows, change_rows, auth_used = [], [], [], {}
    for row in cleaned:  # cleaned-CSV order; only pilot rows are emitted
        if row["inventory_id"] not in pilot_ids:
            continue
        sid = row["source_id"]
        record = by_source.get(sid)
        if record is None or record["inventory_id"] != row["inventory_id"]:
            raise BuildError(f"{sid}: no matching enrichment record")
        new = dict(row)

        for field, status_key in ENRICHED_FIELDS.items():
            status = record.get(status_key)
            origin = (record.get("value_origin") or {}).get(field)
            value = record.get(field)
            written, reason = decide(row[field], value, status, origin, field)
            if written:
                new[field] = value
                change_rows.append(
                    [
                        row["inventory_id"],
                        sid,
                        field,
                        row[field],
                        value,
                        f"enrichment:{status}",
                        "",
                        "",
                        (record.get("evidence_reference") or {}).get(field) or "",
                    ]
                )
            elif status not in WRITABLE_STATUSES and origin != "human_approved":
                reason = (record.get("reasons") or {}).get(field) or reason
            review = (record.get("review_status") or {}).get(field) or ""
            if field == "acquired_at" and not written and status == "unknown" and accept_unknown:
                review = "owner_accepted_unknown"
                reason = (
                    f"{reason}; owner accepted `unknown` (D-052): no genuine acquisition record;"
                    " file timestamps and transfer dates are not acquisition dates"
                )
            count, reference = candidate_summary(field, record, topics)
            status_rows.append(
                [
                    row["inventory_id"],
                    sid,
                    field,
                    str(written).lower(),
                    value_class(status, origin),
                    status or "",
                    origin or "",
                    review,
                    (record.get("review_completion") or {}).get(field) or "",
                    (record.get("approval_outcome") or {}).get(field) or "",
                    (record.get("confidence") or {}).get(field) or "",
                    row[field],
                    new[field] if written else "",
                    str(count),
                    reference,
                    (record.get("evidence_reference") or {}).get(field) or "",
                    reason,
                ]
            )

        # Rights overlays: only the fields and values the covering records name.
        if not all(check_use(sid, row["sha256"], u, records).permitted for u in LOCAL_USES):
            raise BuildError(f"{sid}: local uses not authorised for these exact bytes")
        overlays = rights_overlays(sid, row["sha256"], row, records, paths.authorization_dir)
        for field in OVERLAY_FIELDS:
            if field not in overlays:
                continue
            entry = overlays[field]
            granting = entry["records"]
            for g in granting:
                auth_used[g["record_id"]] = g["sha256"]
            new[field] = entry["value"]
            change_rows.append(
                [
                    row["inventory_id"],
                    sid,
                    field,
                    row[field],
                    new[field],
                    "authorization_overlay:"
                    + "; ".join(f"{g['basis']} ({g['scope']})" for g in granting),
                    ";".join(g["record_id"] for g in granting),
                    ";".join(g["sha256"] for g in granting),
                    ";".join(g["path"] for g in granting),
                ]
            )
            status_rows.append(
                [
                    row["inventory_id"],
                    sid,
                    field,
                    "true",
                    "authorization_overlay",
                    ";".join(g["review_status"] for g in granting),
                    ";".join(g["basis"] for g in granting),
                    ";".join(g["review_status"] for g in granting),
                    "",
                    "",
                    "",
                    row[field],
                    new[field],
                    "0",
                    "",
                    ";".join(g["path"] for g in granting),
                    "; ".join(f"{g['record_id']}: {g['applies_to']}" for g in granting)
                    + "; owner attestation, not legal verification",
                ]
            )

        # D-051 extraction status.
        doc = pilot_ids[row["inventory_id"]]
        checks_passed = extraction_check(doc, row, paths.artifact_root)
        eligible = extraction_approved and all(checks_passed.values())
        if eligible and row["extraction_status"] != "extracted":
            new["extraction_status"] = "extracted"
            change_rows.append(
                [
                    row["inventory_id"],
                    sid,
                    "extraction_status",
                    row["extraction_status"],
                    "extracted",
                    f"rule:{EXTRACTION_RULE}",
                    "",
                    "",
                    doc.get("raw_path", ""),
                ]
            )
        failed = [k for k, ok in checks_passed.items() if not ok]
        status_rows.append(
            [
                row["inventory_id"],
                sid,
                "extraction_status",
                str(new["extraction_status"] != row["extraction_status"]).lower(),
                "rule_derived",
                "extracted" if eligible else "not_eligible",
                EXTRACTION_RULE,
                row["review_status"],
                "",
                "",
                "",
                row["extraction_status"],
                new["extraction_status"] if eligible else "",
                "0",
                "",
                f"{doc.get('raw_path', '')} {doc.get('normalized_path', '')}".strip(),
                "all checks passed: " + ", ".join(checks_passed)
                if eligible
                else f"not marked: failed {failed or ['owner approval missing']}"
                + "; OCR quality and human review are tracked separately",
            ]
        )
        for field in NEVER_CHANGED:
            if new[field] != row[field]:
                raise BuildError(f"{sid}: {field} must never change")
        out_rows.append([new[c] for c in CANONICAL_HEADER])

    self_check(out_rows, cleaned, change_rows, len(pilot_ids))
    outputs = {
        f"{OUTPUT_STEM}.csv": csv_bytes(CANONICAL_HEADER, out_rows),
        f"{OUTPUT_STEM}.status.csv": csv_bytes(STATUS_HEADER, status_rows),
        f"{OUTPUT_STEM}.changes.csv": csv_bytes(CHANGES_HEADER, change_rows),
    }
    content = {
        "builder_version": BUILDER_VERSION,
        "phase3_run_id": checks["phase3_run_id"],
        "inputs": {
            **checks["cleaned_csv"],
            **checks["phase3_manifest"],
            rel(paths.run_manifest): sha256(paths.run_manifest),
            **(
                {rel(paths.owner_decisions): sha256(paths.owner_decisions)}
                if paths.owner_decisions is not None and paths.owner_decisions.exists()
                else {}
            ),
            **(
                {rel(paths.teacher_validation): sha256(paths.teacher_validation)}
                if paths.teacher_validation is not None and paths.teacher_validation.exists()
                else {}
            ),
        },
        "sidecars": checks["sidecars"],
        "authorization_records": auth_used,
        "pipeline_versions": checks["pilot_run_manifest_versions"],
        "rules": {
            "enriched_fields": list(ENRICHED_FIELDS),
            "writable_statuses": list(WRITABLE_STATUSES),
            "also_writable_origin": "human_approved",
            "multi_value_fields": sorted(MULTI_VALUE_FIELDS),
            "multi_value_separator": MULTI_VALUE_SEPARATOR,
            "never_replace_non_empty_cleaned_value": True,
            "rights_overlay_fields": list(OVERLAY_FIELDS),
            "never_changed": list(NEVER_CHANGED),
            "extraction_rule": EXTRACTION_RULE,
            "acquired_at_owner_accepted_unknown": accept_unknown,
        },
        "pilot": [
            {"inventory_id": r[0], "source_id": r[CANONICAL_HEADER.index("source_id")]}
            for r in out_rows
        ],
        "row_count": len(out_rows),
        "column_count": len(CANONICAL_HEADER),
        "outputs": {
            rel(paths.output_dir / name): hashlib.sha256(data).hexdigest()
            for name, data in outputs.items()
        },
        "database_writes": "none",
        "master_inventory_written": False,
    }
    digest = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
    manifest_path = paths.output_dir / f"{OUTPUT_STEM}.manifest.json"
    generated_at = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous.get("content_digest") == digest:
            generated_at = previous["generated_at"]  # unchanged content keeps its timestamp
    manifest = {"content": content, "content_digest": digest, "generated_at": generated_at}

    for name, data in outputs.items():
        atomic_write_bytes(paths.output_dir / name, data)
    atomic_write_bytes(manifest_path, json_bytes(manifest))
    return manifest


def self_check(
    out_rows: list[list[str]],
    cleaned: list[dict[str, str]],
    changes: list[list[str]],
    expected_rows: int,
) -> None:
    """Every differing cell must be a recorded change; IDs unique; exact row count."""
    ids = [r[0] for r in out_rows]
    if len(ids) != expected_rows or len(set(ids)) != len(ids):
        raise BuildError(f"expected {expected_rows} unique rows, built {len(ids)}")
    original = {r["inventory_id"]: r for r in cleaned}
    changed = {(c[0], c[2]) for c in changes}
    for row in out_rows:
        for column, value in zip(CANONICAL_HEADER, row, strict=True):
            differs = value != original[row[0]][column]
            if differs != ((row[0], column) in changed):
                raise BuildError(f"{row[0]}.{column}: unrecorded or missing change")


def main(argv: list[str] | None = None) -> int:
    try:
        manifest = build(Paths.default())
    except BuildError as exc:
        print(f"build refused: {exc}", file=sys.stderr)
        return 2
    content = manifest["content"]
    print(f"{content['row_count']} rows x {content['column_count']} columns")
    print("\n".join(f"  {path}" for path in content["outputs"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
