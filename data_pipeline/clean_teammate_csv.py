"""Profile, clean and validate teammate inventory CSVs; never modifies originals.

    python -m data_pipeline.clean_teammate_csv                  # all CSVs in the incoming dir
    python -m data_pipeline.clean_teammate_csv --file <csv>     # one file
    python -m data_pipeline.clean_teammate_csv --profile-only   # snapshot + profile only
    python -m data_pipeline.clean_teammate_csv --dry-run        # compute, write nothing
    python -m data_pipeline.clean_teammate_csv --force          # replace outputs of another run

For each `<stem>.csv` the outputs are (paths relative to the output root,
`resources/teammate_csv/` by default):

    processed/cleaned/<stem>.cleaned.csv          accepted rows, canonical 29 columns
    processed/rejected/<stem>.rejected.csv        rejected rows + reasons
    processed/rejected/<stem>.quarantined.csv     quarantined rows + review reasons
    processed/reports/<stem>.*                    profile, quality, duplicates, missing
                                                  fields, coverage, PDF paths, SHA-256,
                                                  reviewer notes
    processed/manifests/<stem>.manifest.json      hashes, versions, counts, reconciliation
    processed/manifests/<stem>.decisions.jsonl    per-row transformations and findings
    processed/manifests/<stem>.reconciliation.csv one line per input row
    mappings/<stem>.field_mapping.json            source -> canonical field mapping
    mappings/<stem>.merge_proposal.{json,md}      proposal only; master is never written

A byte-identical snapshot of every input is kept under
`data_pipeline/data/raw/teammate_csv/<stem>/<sha256>/`. Exit codes: 0 success,
2 unreadable input, 3 field mapping required, 4 refused overwrite, 5 original changed
during the run, 6 unsafe configuration, 7 no input found.
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
import io
import json
import os
import shutil
import stat
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from data_pipeline import inventory_schema
from data_pipeline.inventory_schema import (
    CANONICAL_HEADER,
    PERMISSION_CATEGORY_COLUMNS,
    REQUIRED_FIELDS,
    RULES_VERSION,
)
from data_pipeline.stages import clean_csv, profile_csv, validate_csv
from data_pipeline.stages.profile_csv import CsvReadError, ParsedCsv, read_csv, sha256_file
from data_pipeline.stages.validate_csv import (
    ACCEPTED,
    QUARANTINED,
    REJECTED,
    WARNING,
    Issue,
    PdfCheck,
    RowView,
)

PIPELINE_VERSION = "teammate-csv-cleaner/1.0.0"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INCOMING = PROJECT_ROOT / "resources/teammate_csv/incoming"
DEFAULT_PDF_ROOT = PROJECT_ROOT / "resources/textbook_pdfs"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "resources/teammate_csv"
DEFAULT_SNAPSHOT_ROOT = PROJECT_ROOT / "data_pipeline/data/raw/teammate_csv"
DEFAULT_MASTER = PROJECT_ROOT / "data_pipeline/curriculum.csv"
DEFAULT_CONFIG = PROJECT_ROOT / "data_pipeline/config.yaml"
RULE_SOURCES = (
    Path(inventory_schema.__file__),
    Path(profile_csv.__file__),
    Path(clean_csv.__file__),
    Path(validate_csv.__file__),
    Path(__file__),
)

# `csv_cleaning` settings this implementation honours. Any other value is refused rather
# than silently ignored (exit 6).
EXPECTED_CSV_CLEANING_CONFIG = {
    "output_encoding": "utf-8",
    "preserve_headers": True,
    "preserve_column_order": True,
    "read_identifiers_as_strings": True,
    "trim_outer_whitespace": True,
    "normalize_internal_whitespace": False,
    "auto_correct_factual_values": False,
    "near_duplicate_action": "flag_for_review",
    "exact_duplicate_action": "quarantine_extra_occurrences",
    "require_row_reconciliation": True,
    "compare_to_pdfs_requires_permitted_processing": True,
}

# Recorded verbatim in manifests and merge proposals; see docs/DECISIONS.md D-031.
OWNER_RIGHTS_ASSERTION = {
    "recorded_on": "2026-10-31",
    "reference": "docs/DECISIONS.md D-031",
    "statement": "The owner stated that the textbook PDFs are approved for hackathon use.",
    "nature": "Owner-provided authorisation assertion; not independent legal verification.",
    "applied_to_inventory_fields": False,
    "used_by_this_phase_for": [
        "inventory metadata cleaning",
        "file existence and readability checks",
        "SHA-256 integrity checks",
    ],
    "not_authorised_by_this_phase": [
        "PDF text extraction or OCR",
        "external AI/model processing",
        "external embeddings or indexing",
        "student-facing display",
        "redistribution",
        "LLM training or fine-tuning (inventory says permitted_training=not_permitted)",
    ],
}

META_COLUMNS = (
    "__source_file",
    "__source_row",
    "__source_line",
    "__disposition",
    "__reason_codes",
    "__failed_fields",
    "__reasons",
    "__suggested_actions",
    "__related_rows",
    "__raw_record_json",
)


class PipelineError(Exception):
    def __init__(self, exit_code: int, message: str) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass
class RowResult:
    data_index: int
    line: int
    raw: tuple[str, ...]
    cleaned: dict[str, str] | None = None
    transforms: list[clean_csv.Transform] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    pdf: PdfCheck | None = None

    @property
    def disposition(self) -> str:
        return validate_csv.disposition(self.issues)

    @property
    def blocking_issues(self) -> list[Issue]:
        return [i for i in self.issues if i.severity != WARNING]


# --- helpers --------------------------------------------------------------------------------


def rel(path: Path) -> str:
    resolved = path.resolve()
    return (
        resolved.relative_to(PROJECT_ROOT).as_posix()
        if resolved.is_relative_to(PROJECT_ROOT)
        else str(resolved)
    )


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def csv_bytes(header: tuple[str, ...], rows: list[list[str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def load_config(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    config = yaml.safe_load(raw) or {}
    settings = config.get("csv_cleaning", {})
    unsafe = {
        key: settings.get(key)
        for key, expected in EXPECTED_CSV_CLEANING_CONFIG.items()
        if settings.get(key) != expected
    }
    if unsafe:
        raise PipelineError(6, f"config.yaml csv_cleaning not supported by this cleaner: {unsafe}")
    if config.get("pipeline", {}).get("fail_on_unknown_rights") is not True:
        raise PipelineError(6, "config.yaml pipeline.fail_on_unknown_rights must be true")
    return settings, hashlib.sha256(raw).hexdigest()


def rules_sha256() -> str:
    digest = hashlib.sha256()
    for source in RULE_SOURCES:
        digest.update(source.name.encode())
        digest.update(source.read_bytes())
    return digest.hexdigest()


def discover(incoming: Path, single: Path | None) -> list[Path]:
    if single is not None:
        if not single.is_file() or single.suffix.lower() != ".csv":
            raise PipelineError(7, f"input is not a CSV file: {rel(single)}")
        return [single]
    found = sorted(
        p
        for p in incoming.rglob("*")
        if p.is_file() and p.suffix.lower() == ".csv" and not p.name.startswith(".")
    )
    if not found:
        raise PipelineError(7, f"no incoming CSV found under {rel(incoming)}")
    return found


def snapshot(source: Path, sha: str, snapshot_root: Path) -> dict[str, Any]:
    """Byte-identical, read-only copy addressed by content hash; reused when present."""
    target = snapshot_root / source.stem / sha / source.name
    reused = target.exists()
    if not reused:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.tmp")
        shutil.copyfile(source, tmp)
        os.replace(tmp, target)
        target.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    if sha256_file(target) != sha:
        raise PipelineError(5, f"snapshot hash mismatch: {rel(target)}")
    return {"path": rel(target), "sha256": sha, "reused_existing": reused}


# --- core processing -------------------------------------------------------------------------


def evaluate_rows(parsed: ParsedCsv, pdf_root: Path) -> tuple[list[RowResult], dict[str, Any]]:
    header_ok = parsed.header == CANONICAL_HEADER
    results = [RowResult(r.data_index, r.start_line, r.values) for r in parsed.records]
    if not header_ok:
        for row in results:
            row.issues.append(
                Issue("SCHEMA_MAPPING_REQUIRED", None, "header is not the canonical 29 columns")
            )
        return results, {"skipped": "header does not match the canonical schema"}

    hash_cache: dict[Path, str] = {}
    views: list[RowView] = []
    for row in results:
        if len(row.raw) != len(CANONICAL_HEADER):
            row.issues.append(
                Issue(
                    "ROW_WIDTH_MISMATCH",
                    None,
                    f"{len(row.raw)} fields, expected {len(CANONICAL_HEADER)}",
                )
            )
            continue
        row.cleaned, row.transforms, findings = clean_csv.clean_row(CANONICAL_HEADER, row.raw)
        row.issues += [Issue(f.code, f.column, f"{f.code} in {f.column}") for f in findings]
        row.issues += validate_csv.validate_fields(row.cleaned)
        local_path = validate_csv.parse_local_path(row.cleaned["notes"])
        row.pdf = validate_csv.check_pdf(pdf_root, local_path, row.cleaned["sha256"], hash_cache)
        row.issues += row.pdf.issues
        views.append(
            RowView(row.data_index, row.cleaned, row.pdf.resolved_path, row.pdf.computed_sha256)
        )
    duplicate_issues, duplicate_report = validate_csv.duplicate_analysis(views)
    for row in results:
        row.issues += duplicate_issues.get(row.data_index, [])
    return results, duplicate_report


def unreferenced_files(pdf_root: Path, results: list[RowResult]) -> list[str]:
    referenced = {r.pdf.resolved_path for r in results if r.pdf and r.pdf.resolved_path}
    root = pdf_root.resolve()
    return sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file()
        and not p.name.startswith(".")
        and p.name != "README.md"
        and p.relative_to(root).as_posix() not in referenced
    )


def missing_field_rows(results: list[RowResult]) -> list[list[str]]:
    rows = [r for r in results if r.cleaned is not None]
    accepted = [r for r in rows if r.disposition == ACCEPTED]
    table = []
    for column in CANONICAL_HEADER:
        empty = sum(1 for r in rows if not r.cleaned[column])  # type: ignore[index]
        table.append(
            [
                column,
                "required" if column in REQUIRED_FIELDS else "optional",
                str(len(rows)),
                str(empty),
                f"{100 * empty / max(len(rows), 1):.1f}",
                str(sum(1 for r in accepted if not r.cleaned[column])),  # type: ignore[index]
            ]
        )
    return table


def reviewer_note_rows(results: list[RowResult], source_name: str) -> list[list[str]]:
    rows = []
    for row in results:
        if row.cleaned is None:
            continue
        for column, annotation in validate_csv.find_reviewer_notes(row.cleaned):
            original = row.cleaned[column]
            candidate = " ".join(original.replace(annotation, " ").split())
            rows.append(
                [
                    source_name,
                    str(row.data_index),
                    str(row.line),
                    row.cleaned["inventory_id"],
                    column,
                    original,
                    annotation,
                    candidate,
                    "false",
                    row.cleaned["validation_status"],
                    row.disposition,
                ]
            )
    return rows


def permission_matrix(results: list[RowResult]) -> dict[str, Any]:
    rows = [r.cleaned for r in results if r.cleaned is not None]
    matrix = {}
    for category, column in PERMISSION_CATEGORY_COLUMNS.items():
        if column is None:
            matrix[category] = {
                "inventory_column": None,
                "values": {},
                "status": "not_authorised (no column in the 29-column inventory)",
            }
            continue
        values = collections.Counter(r[column] for r in rows)
        permitted = values.get("permitted", 0)
        matrix[category] = {
            "inventory_column": column,
            "values": dict(sorted(values.items())),
            "status": "permitted for all rows"
            if rows and permitted == len(rows)
            else f"blocked for {len(rows) - permitted} of {len(rows)} rows",
        }
    matrix["rights_status_values"] = dict(
        sorted(collections.Counter(r["rights_status"] for r in rows).items())
    )
    return matrix


def master_state(master: Path) -> dict[str, Any]:
    parsed = read_csv(master)
    return {
        "path": rel(master),
        "sha256": parsed.sha256,
        "header_matches_canonical": parsed.header == CANONICAL_HEADER,
        "data_rows": len(parsed.records),
        "inventory_ids": {
            dict(zip(parsed.header, r.values, strict=False)).get("inventory_id", "")
            for r in parsed.records
        },
    }


def row_output(row: RowResult, source_name: str) -> list[str]:
    blocking = row.blocking_issues
    # Original (uncleaned) values under the canonical columns when the row is well formed;
    # otherwise the raw record is kept verbatim as JSON.
    canonical = list(row.raw) if row.cleaned is not None else []
    return [
        source_name,
        str(row.data_index),
        str(row.line),
        row.disposition,
        ";".join(dict.fromkeys(i.code for i in blocking)),
        ";".join(dict.fromkeys(i.field for i in blocking if i.field)),
        " | ".join(i.message for i in blocking),
        " | ".join(dict.fromkeys(i.suggested_action for i in blocking)),
        ";".join(str(n) for n in sorted({n for i in blocking for n in i.related_rows})),
        "" if canonical else json.dumps(list(row.raw), ensure_ascii=False),
        *(canonical or [""] * len(CANONICAL_HEADER)),
    ]


def process_file(source: Path, options: argparse.Namespace) -> dict[str, Any]:
    stem = source.stem
    out = options.output_root
    paths = {
        "cleaned": out / "processed/cleaned" / f"{stem}.cleaned.csv",
        "rejected": out / "processed/rejected" / f"{stem}.rejected.csv",
        "quarantined": out / "processed/rejected" / f"{stem}.quarantined.csv",
        "profile": out / "processed/reports" / f"{stem}.profile.json",
        "quality_json": out / "processed/reports" / f"{stem}.quality.json",
        "quality_md": out / "processed/reports" / f"{stem}.quality.md",
        "duplicates": out / "processed/reports" / f"{stem}.duplicates.json",
        "missing_fields": out / "processed/reports" / f"{stem}.missing_fields.csv",
        "coverage": out / "processed/reports" / f"{stem}.coverage.csv",
        "pdf_paths": out / "processed/reports" / f"{stem}.pdf_paths.csv",
        "sha256": out / "processed/reports" / f"{stem}.sha256.csv",
        "reviewer_notes": out / "processed/reports" / f"{stem}.reviewer_notes.csv",
        "decisions": out / "processed/manifests" / f"{stem}.decisions.jsonl",
        "reconciliation": out / "processed/manifests" / f"{stem}.reconciliation.csv",
        "field_mapping": out / "mappings" / f"{stem}.field_mapping.json",
        "merge_json": out / "mappings" / f"{stem}.merge_proposal.json",
        "merge_md": out / "mappings" / f"{stem}.merge_proposal.md",
    }
    manifest_path = out / "processed/manifests" / f"{stem}.manifest.json"

    original_sha_before = sha256_file(source)
    try:
        parsed = read_csv(source)
    except CsvReadError as exc:
        raise PipelineError(2, f"{rel(source)}: {exc.code}: {exc}") from None
    if parsed.sha256 != original_sha_before:
        raise PipelineError(5, f"{rel(source)} changed while being read")

    settings, config_sha = load_config(options.config)
    rules_sha = rules_sha256()
    run_id = hashlib.sha256(
        json.dumps([parsed.sha256, PIPELINE_VERSION, RULES_VERSION, rules_sha, config_sha]).encode()
    ).hexdigest()[:16]

    if not options.dry_run and manifest_path.exists() and not options.force:
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous.get("run_id") != run_id:
            raise PipelineError(
                4,
                f"outputs for {source.name} come from run {previous.get('run_id')} (different"
                " input, rules or config); re-run with --force to replace them",
            )

    profile = profile_csv.profile_csv(parsed)
    profile["file"] = rel(source)
    snap = None
    profile_payload = json_bytes(profile)
    if not options.dry_run:
        snap = snapshot(source, parsed.sha256, options.snapshot_root)
        atomic_write_bytes(paths["profile"], profile_payload)
    if options.profile_only:
        return {"file": rel(source), "mode": "profile-only", "profile": rel(paths["profile"])}

    header = validate_csv.check_header(parsed.header)
    results, duplicate_report = evaluate_rows(parsed, options.pdf_root)
    counts = collections.Counter(r.disposition for r in results)
    # Rows affected per (severity, code); a row counts once per code.
    reason_counts = collections.Counter(
        (i.severity, i.code) for r in results for i in {x.code: x for x in r.issues}.values()
    )
    well_formed = [r for r in results if r.cleaned is not None]
    coverage = validate_csv.coverage_report([(r.cleaned, r.disposition) for r in well_formed])
    master_before = master_state(options.master)
    accepted = [r for r in results if r.disposition == ACCEPTED]

    # --- tables
    cleaned_rows = [[r.cleaned[c] for c in CANONICAL_HEADER] for r in accepted]  # type: ignore[index]
    rejected_rows = [row_output(r, source.name) for r in results if r.disposition == REJECTED]
    quarantined_rows = [row_output(r, source.name) for r in results if r.disposition == QUARANTINED]
    pdf_rows, sha_rows = [], []
    for r in results:
        pdf = r.pdf or PdfCheck(local_path=None)
        ident = [str(r.data_index), str(r.line), (r.cleaned or {}).get("inventory_id", "")]
        pdf_rows.append(
            ident
            + [
                pdf.local_path or "",
                pdf.resolved_path or "",
                *(
                    str(x).lower()
                    for x in (
                        pdf.inside_root,
                        pdf.exists,
                        pdf.is_file,
                        pdf.readable,
                        pdf.extension_ok,
                        pdf.signature_ok,
                    )
                ),
                ";".join(i.code for i in pdf.issues),
            ]
        )
        sha_rows.append(
            ident
            + [
                pdf.resolved_path or "",
                pdf.expected_sha256,
                pdf.computed_sha256 or "",
                "match"
                if pdf.sha256_match
                else ("not_computed" if pdf.computed_sha256 is None else "mismatch"),
            ]
        )
    coverage_rows = [
        [
            e["class_level"],
            e["subject_id"],
            e["status"],
            *(
                str(e[k])
                for k in (
                    "rows",
                    "chapter_pdf_rows",
                    "other_resource_rows",
                    "accepted",
                    "quarantined",
                    "rejected",
                    "subject_median_chapter_pdfs",
                )
            ),
            " | ".join(e["courses"]),
            " | ".join(e["books"]),
        ]
        for e in coverage
    ]
    reconciliation_rows = [
        [
            str(r.data_index),
            str(r.line),
            (r.cleaned or {}).get("inventory_id", ""),
            (r.cleaned or {}).get("source_id", ""),
            r.disposition,
            ";".join(dict.fromkeys(i.code for i in r.blocking_issues)),
            ";".join(dict.fromkeys(i.code for i in r.issues if i.severity == WARNING)),
        ]
        for r in results
    ]

    pdf_summary = {
        "rows_with_path": sum(1 for r in results if r.pdf and r.pdf.local_path),
        "inside_root": sum(1 for r in results if r.pdf and r.pdf.inside_root),
        "exists": sum(1 for r in results if r.pdf and r.pdf.exists),
        "readable": sum(1 for r in results if r.pdf and r.pdf.readable),
        "extension_pdf": sum(1 for r in results if r.pdf and r.pdf.extension_ok),
        "pdf_signature": sum(1 for r in results if r.pdf and r.pdf.signature_ok),
        "sha256_match": sum(1 for r in results if r.pdf and r.pdf.sha256_match),
        "sha256_mismatch": sum(
            1 for r in results if r.pdf and r.pdf.computed_sha256 and not r.pdf.sha256_match
        ),
        "unreferenced_files_in_pdf_root": unreferenced_files(options.pdf_root, results),
    }
    reconciliation = {
        "input_rows": len(results),
        "accepted": counts[ACCEPTED],
        "rejected": counts[REJECTED],
        "quarantined": counts[QUARANTINED],
        "exact_duplicate_extra_copies_in_quarantine": duplicate_report.get("counts", {}).get(
            "exact_duplicate_extra_copies", 0
        ),
        "blank_lines_skipped": parsed.blank_lines,
    }
    reconciliation["balanced"] = reconciliation["input_rows"] == (
        reconciliation["accepted"] + reconciliation["rejected"] + reconciliation["quarantined"]
    )
    reconciliation["equation"] = (
        f"{reconciliation['input_rows']} input = {reconciliation['accepted']} accepted"
        f" + {reconciliation['rejected']} rejected + {reconciliation['quarantined']} quarantined"
    )
    if not reconciliation["balanced"]:
        raise PipelineError(5, f"reconciliation failed: {reconciliation['equation']}")

    field_mapping = {
        "source_file": rel(source),
        "header_check": header,
        "mapping": [
            {
                "canonical_column": c,
                "source_column": c if c in parsed.header else None,
                "status": "identity" if c in parsed.header else "missing_in_source",
                "policy": "required" if c in REQUIRED_FIELDS else "optional",
            }
            for c in CANONICAL_HEADER
        ],
        "unmapped_source_columns": [
            {"source_column": c, "status": "unmapped; preserved in __raw_record_json"}
            for c in header["unexpected_columns"]
        ],
        "derived_values": [
            {
                "name": "local_path",
                "from": "notes",
                "rule": "teammate convention `local_path: <path>`; path relative to"
                " resources/textbook_pdfs/; used only for file integrity checks",
            }
        ],
        "permission_categories": {
            k: v or "no column (stays unauthorised)" for k, v in PERMISSION_CATEGORY_COLUMNS.items()
        },
        "approved": False,
    }

    rights = {
        "inventory_permission_matrix": permission_matrix(results),
        "owner_assertion": OWNER_RIGHTS_ASSERTION,
        "original_permission_fields_modified": False,
    }
    conflicts = sorted(
        r.cleaned["inventory_id"]  # type: ignore[index]
        for r in accepted
        if r.cleaned["inventory_id"] in master_before["inventory_ids"]  # type: ignore[index]
    )
    merge = {
        "applied": False,
        "requires": "explicit owner approval; master is never written by this pipeline",
        "master": {k: v for k, v in master_before.items() if k != "inventory_ids"},
        "proposed_additions": {
            "rows": len(accepted),
            "source": rel(paths["cleaned"]),
            "by_class_subject": {
                f"{e['class_level']}/{e['subject_id']}": e["accepted"] for e in coverage
            },
        },
        "inventory_id_collisions_with_master": conflicts,
        "held_back": {
            "quarantined": [
                {"row": r.data_index, "inventory_id": (r.cleaned or {}).get("inventory_id", "")}
                for r in results
                if r.disposition == QUARANTINED
            ],
            "rejected": [
                {"row": r.data_index, "inventory_id": (r.cleaned or {}).get("inventory_id", "")}
                for r in results
                if r.disposition == REJECTED
            ],
        },
        "known_gaps_carried_as_empty": [
            row[0] for row in missing_field_rows(results) if row[1] == "optional" and row[5] != "0"
        ],
        "decisions_needed": [
            "Approve merging the accepted rows into data_pipeline/curriculum.csv.",
            "Resolve each quarantined row (see the quarantined CSV and reviewer-note report).",
            "Decide whether to record the owner's hackathon-use assertion as purpose-specific"
            " permissions (permitted_processing etc.) with a permission_reference; fields are"
            " unchanged until then.",
            "Confirm optional fields (topic_title, learning_objective, source_url, acquired_at)"
            " stay empty until an authoritative source supplies them.",
        ],
        "rights": rights,
    }

    quality = {
        "source_file": rel(source),
        "source_sha256": parsed.sha256,
        "pipeline_version": PIPELINE_VERSION,
        "rules_version": RULES_VERSION,
        "run_id": run_id,
        "reconciliation": reconciliation,
        "issue_counts": [
            {"severity": sev, "code": code, "rows": n}
            for (sev, code), n in sorted(reason_counts.items())
        ],
        "header_check": header,
        "transformations": dict(
            sorted(collections.Counter(t.rule for r in results for t in r.transforms).items())
        ),
        "duplicates": duplicate_report.get("counts", {}),
        "pdf_integrity": pdf_summary,
        "coverage": coverage,
        "rights": rights,
    }

    decisions = b"".join(
        json_bytes_line(
            {
                "data_row": r.data_index,
                "line": r.line,
                "inventory_id": (r.cleaned or {}).get("inventory_id", ""),
                "disposition": r.disposition,
                "transforms": [t.__dict__ for t in r.transforms],
                "issues": [i.as_dict() for i in r.issues],
            }
        )
        for r in results
    )

    payloads: dict[str, bytes] = {
        "cleaned": csv_bytes(CANONICAL_HEADER, cleaned_rows),
        "rejected": csv_bytes(META_COLUMNS + CANONICAL_HEADER, rejected_rows),
        "quarantined": csv_bytes(META_COLUMNS + CANONICAL_HEADER, quarantined_rows),
        "quality_json": json_bytes(quality),
        "duplicates": json_bytes(duplicate_report),
        "missing_fields": csv_bytes(
            (
                "column",
                "policy",
                "rows_checked",
                "empty",
                "empty_pct",
                "empty_in_accepted",
            ),
            missing_field_rows(results),
        ),
        "coverage": csv_bytes(
            (
                "class_level",
                "subject_id",
                "status",
                "rows",
                "chapter_pdf_rows",
                "other_resource_rows",
                "accepted",
                "quarantined",
                "rejected",
                "subject_median_chapter_pdfs",
                "courses",
                "books",
            ),
            coverage_rows,
        ),
        "pdf_paths": csv_bytes(
            (
                "data_row",
                "line",
                "inventory_id",
                "local_path",
                "resolved_path",
                "inside_root",
                "exists",
                "is_file",
                "readable",
                "extension_pdf",
                "pdf_signature",
                "issues",
            ),
            pdf_rows,
        ),
        "sha256": csv_bytes(
            (
                "data_row",
                "line",
                "inventory_id",
                "resolved_path",
                "recorded_sha256",
                "computed_sha256",
                "result",
            ),
            sha_rows,
        ),
        "reviewer_notes": csv_bytes(
            (
                "source_file",
                "data_row",
                "line",
                "inventory_id",
                "field",
                "original_value",
                "annotation",
                "candidate_value_if_annotation_removed",
                "applied",
                "teammate_validation_status",
                "disposition",
            ),
            reviewer_note_rows(results, source.name),
        ),
        "decisions": decisions,
        "reconciliation": csv_bytes(
            (
                "data_row",
                "line",
                "inventory_id",
                "source_id",
                "disposition",
                "blocking_codes",
                "warning_codes",
            ),
            reconciliation_rows,
        ),
        "field_mapping": json_bytes(field_mapping),
        "merge_json": json_bytes(merge),
    }
    payloads["merge_md"] = merge_markdown(merge, reconciliation).encode("utf-8")
    payloads["quality_md"] = quality_markdown(quality, merge, paths).encode("utf-8")

    summary = {
        "file": rel(source),
        "run_id": run_id,
        "header_matches_canonical": header["matches_canonical"],
        **reconciliation,
    }
    if options.dry_run:
        return {**summary, "mode": "dry-run (nothing written)"}

    for key, data in payloads.items():
        atomic_write_bytes(paths[key], data)

    original_sha_after = sha256_file(source)
    master_after = sha256_file(options.master)
    if original_sha_after != original_sha_before:
        raise PipelineError(5, f"{rel(source)} changed during processing")
    if master_after != master_before["sha256"]:
        raise PipelineError(5, "data_pipeline/curriculum.csv changed during processing")

    manifest = {
        "pipeline_version": PIPELINE_VERSION,
        "rules_version": RULES_VERSION,
        "rules_sha256": rules_sha,
        "config_path": rel(options.config),
        "config_sha256": config_sha,
        "csv_cleaning_config": settings,
        "run_id": run_id,
        "generated_at_utc": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "input": {
            "path": rel(source),
            "sha256_before": original_sha_before,
            "sha256_after": original_sha_after,
            "unchanged": True,
            "size_bytes": parsed.size_bytes,
            "encoding": parsed.encoding,
            "utf8_bom": parsed.has_bom,
            "delimiter": parsed.delimiter,
            "line_endings": parsed.line_endings,
            "header": list(parsed.header),
            "data_rows": len(parsed.records),
        },
        "snapshot": snap,
        "pdf_root": rel(options.pdf_root),
        "master_inventory": {
            "path": rel(options.master),
            "sha256_before": master_before["sha256"],
            "sha256_after": master_after,
            "unchanged": True,
            "data_rows": master_before["data_rows"],
        },
        "reconciliation": reconciliation,
        "output_format": "UTF-8 without BOM, LF line endings, RFC 4180 minimal quoting",
        "outputs": {
            rel(paths[k]): hashlib.sha256(v).hexdigest()
            for k, v in sorted({**payloads, "profile": profile_payload}.items())
        },
        "rights": {
            "owner_assertion": OWNER_RIGHTS_ASSERTION,
            "original_permission_fields_modified": False,
        },
        "database_writes": "none",
        "pdf_content_extraction": "none (bytes read only for SHA-256 and %PDF- signature)",
    }
    atomic_write_bytes(manifest_path, json_bytes(manifest))
    return {**summary, "manifest": rel(manifest_path)}


def json_bytes_line(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


# --- markdown reports -----------------------------------------------------------------------


def merge_markdown(merge: dict[str, Any], reconciliation: dict[str, Any]) -> str:
    lines = [
        "# Proposed master inventory merge (NOT APPLIED)",
        "",
        f"- Requires: {merge['requires']}.",
        f"- Master: `{merge['master']['path']}` — {merge['master']['data_rows']} data rows,"
        f" header canonical: {merge['master']['header_matches_canonical']},"
        f" sha256 `{merge['master']['sha256']}`.",
        f"- Proposed additions: **{merge['proposed_additions']['rows']} accepted rows** from"
        f" `{merge['proposed_additions']['source']}`.",
        "- inventory_id collisions with master:"
        f" {len(merge['inventory_id_collisions_with_master'])}.",
        f"- Held back: {len(merge['held_back']['quarantined'])} quarantined,"
        f" {len(merge['held_back']['rejected'])} rejected.",
        f"- Reconciliation: {reconciliation['equation']}.",
        "",
        "## Held back for review",
        "",
    ]
    for kind in ("quarantined", "rejected"):
        for item in merge["held_back"][kind]:
            lines.append(f"- {kind}: data row {item['row']} `{item['inventory_id']}`")
    if not any(merge["held_back"].values()):
        lines.append("- none")
    lines += ["", "## Optional fields carried as empty (never filled automatically)", ""]
    lines += [f"- `{c}`" for c in merge["known_gaps_carried_as_empty"]] or ["- none"]
    lines += ["", "## Decisions needed", ""]
    lines += [f"{n}. {d}" for n, d in enumerate(merge["decisions_needed"], 1)]
    lines += ["", "## Rights", ""]
    for category, entry in merge["rights"]["inventory_permission_matrix"].items():
        if category == "rights_status_values":
            lines.append(f"- rights_status values: {entry}")
        else:
            lines.append(f"- {category} (`{entry['inventory_column']}`): {entry['status']}")
    assertion = merge["rights"]["owner_assertion"]
    lines += [
        "",
        f"Owner assertion ({assertion['recorded_on']}, {assertion['reference']}):"
        f" {assertion['statement']} {assertion['nature']} Applied to inventory fields: no.",
        "",
    ]
    return "\n".join(lines)


def quality_markdown(quality: dict[str, Any], merge: dict[str, Any], paths: dict[str, Path]) -> str:
    rec = quality["reconciliation"]
    pdf = quality["pdf_integrity"]
    lines = [
        f"# Data quality report — `{quality['source_file']}`",
        "",
        f"- Source SHA-256: `{quality['source_sha256']}`",
        f"- Pipeline `{quality['pipeline_version']}`, rules `{quality['rules_version']}`,"
        f" run `{quality['run_id']}`",
        f"- **Reconciliation: {rec['equation']}** (balanced: {rec['balanced']}; exact-duplicate"
        f" extra copies in quarantine: {rec['exact_duplicate_extra_copies_in_quarantine']};"
        f" blank lines skipped: {len(rec['blank_lines_skipped'])})",
        "- Header matches the canonical 29 columns:"
        f" {quality['header_check']['matches_canonical']}",
        f"- Transformations applied: {quality['transformations'] or 'none'}",
        "",
        "## Findings by code",
        "",
        "| Severity | Code | Rows |",
        "|---|---|---|",
    ]
    lines += [f"| {i['severity']} | {i['code']} | {i['rows']} |" for i in quality["issue_counts"]]
    lines += [
        "",
        "## PDF integrity (bytes only; no content extracted)",
        "",
        f"- Paths: {pdf['rows_with_path']}; inside root: {pdf['inside_root']}; exist:"
        f" {pdf['exists']}; readable: {pdf['readable']}; `.pdf`: {pdf['extension_pdf']};"
        f" `%PDF-` signature: {pdf['pdf_signature']}",
        f"- SHA-256 match: {pdf['sha256_match']}; mismatch: {pdf['sha256_mismatch']}",
        f"- Files in the PDF root not referenced by any row:"
        f" {len(pdf['unreferenced_files_in_pdf_root'])}",
        "",
        "## Duplicates",
        "",
    ]
    lines += [f"- {k}: {v}" for k, v in quality["duplicates"].items()]
    lines += [
        "",
        "## Class × subject coverage",
        "",
        "| Class | Subject | Status | Rows | Chapters | Accepted | Quarantined | Rejected |",
        "|---|---|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {e['class_level']} | {e['subject_id']} | {e['status']} | {e['rows']} |"
        f" {e['chapter_pdf_rows']} | {e['accepted']} | {e['quarantined']} | {e['rejected']} |"
        for e in quality["coverage"]
    ]
    lines += ["", "## Outputs", ""]
    lines += [f"- `{rel(p)}`" for p in paths.values()]
    lines += ["", "See the merge proposal for rights and the decisions still needed.", ""]
    return "\n".join(lines)


# --- CLI ------------------------------------------------------------------------------------


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean and validate teammate inventory CSVs.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INCOMING)
    parser.add_argument("--file", type=Path, default=None, help="process a single CSV")
    parser.add_argument("--pdf-root", type=Path, default=DEFAULT_PDF_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--snapshot-root", type=Path, default=DEFAULT_SNAPSHOT_ROOT)
    parser.add_argument("--master", type=Path, default=DEFAULT_MASTER)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--profile-only", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="replace outputs of another run")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    options = parse_args(argv)
    try:
        mapping_required = []
        for source in discover(options.input_dir, options.file):
            summary = process_file(source, options)
            print(json.dumps(summary, ensure_ascii=False))
            if summary.get("header_matches_canonical") is False:
                mapping_required.append(summary["file"])
        if mapping_required:
            print("field mapping required for: " + ", ".join(mapping_required), file=sys.stderr)
            return 3
        return 0
    except PipelineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
