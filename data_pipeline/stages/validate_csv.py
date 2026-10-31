"""Validation rules for inventory CSV rows: fields, PDF integrity, duplicates and coverage.

Every finding is an `Issue` whose severity comes from `ISSUE_CATALOG`:

- `reject`: a documented validation failure; the row cannot enter the inventory as-is.
- `quarantine`: structurally valid but needs a human decision (conflicts, annotations,
  unknown vocabulary, teammate review flags). Never merged or "fixed" automatically.
- `warning`: accepted, but reported (missing optional metadata, rights not granted, ...).

A row's disposition is `rejected` if any issue rejects, else `quarantined` if any issue
quarantines, else `accepted`. PDF checks read file bytes only for SHA-256 and the 5-byte
`%PDF-` signature; no textbook content is extracted or inspected.
"""

from __future__ import annotations

import collections
import datetime as dt
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from data_pipeline.inventory_schema import (
    ACADEMIC_SESSION_PATTERN,
    BOARDS,
    CANONICAL_HEADER,
    CHAPTER_CODE_PATTERN,
    CLASS_LEVELS,
    FACTUAL_TEXT_FIELDS,
    INVENTORY_ID_PATTERN,
    ISO_DATE_PATTERN,
    LOCAL_PATH_PATTERN,
    OPTIONAL_FIELDS,
    OTHER_RESOURCE_CODE_PATTERN,
    PDF_SIGNATURE,
    PERMISSION_CATEGORY_COLUMNS,
    PERMISSION_FIELDS,
    REQUIRED_FIELDS,
    REVIEWER_NOTE_PATTERN,
    SHA256_PATTERN,
    SOURCE_ID_PATTERN,
    SUBJECT_CODES,
    SUBJECT_IDS,
    URL_PATTERN,
    VOCABULARIES,
)
from data_pipeline.stages.profile_csv import sha256_file

REJECT, QUARANTINE, WARNING = "reject", "quarantine", "warning"
ACCEPTED, REJECTED, QUARANTINED = "accepted", "rejected", "quarantined"

# code -> (severity, suggested manual action)
ISSUE_CATALOG: dict[str, tuple[str, str]] = {
    # structure / schema
    "SCHEMA_MAPPING_REQUIRED": (QUARANTINE, "Define and approve an explicit field mapping."),
    "ROW_WIDTH_MISMATCH": (REJECT, "Fix quoting/delimiters in the source export and re-run."),
    # field rules
    "REQUIRED_FIELD_MISSING": (REJECT, "Supply the value from an authoritative source."),
    "METADATA_MISSING": (WARNING, "Optional; supply from an authoritative source if available."),
    "CLASS_LEVEL_INVALID": (REJECT, "Use one of 6, 7, 8, 9, 10 (no leading zeros)."),
    "SUBJECT_ID_UNKNOWN": (REJECT, "Use one of the five agreed subject identifiers."),
    "BOARD_OUT_OF_SCOPE": (QUARANTINE, "Confirm whether this board is in scope."),
    "ACADEMIC_SESSION_INVALID": (REJECT, "Use YYYY-YY with consecutive years, e.g. 2026-27."),
    "INVENTORY_ID_FORMAT_INVALID": (REJECT, "Use CT-C<class>-<SUBJ>-<nnn>."),
    "SOURCE_ID_FORMAT_INVALID": (REJECT, "Use SRC-C<class>-<SUBJ>-<BOOK>-<PART>."),
    "ID_CLASS_MISMATCH": (QUARANTINE, "Reconcile the ID class prefix with class_level."),
    "ID_SUBJECT_MISMATCH": (QUARANTINE, "Reconcile the ID subject code with subject_id."),
    "SHA256_FORMAT_INVALID": (REJECT, "Record the lowercase 64-hex SHA-256 of the PDF."),
    "URL_INVALID": (REJECT, "Record an http(s) URL or leave the field empty."),
    "DATE_FORMAT_INVALID": (REJECT, "Use an ISO 8601 date (YYYY-MM-DD); do not guess."),
    "VOCABULARY_UNKNOWN": (QUARANTINE, "Use a documented value or approve a vocabulary change."),
    "ITEM_CODE_MISMATCH": (QUARANTINE, "Align item_type with chapter_or_unit_code."),
    "REVIEWER_NOTE_IN_FACTUAL_FIELD": (
        QUARANTINE,
        "Move the annotation to `notes` and confirm the factual value (owner approval).",
    ),
    "TEAMMATE_FLAGGED_FOR_REVIEW": (QUARANTINE, "Resolve the teammate's review flag."),
    "TEAMMATE_VALIDATION_FAILED": (QUARANTINE, "Resolve the teammate's validation failure."),
    "RIGHTS_NOT_GRANTED": (WARNING, "Record purpose-specific permission before that use."),
    # text
    "CONTROL_CHARACTER": (QUARANTINE, "Remove control characters in the source export."),
    "ENCODING_SUSPECT": (QUARANTINE, "Re-export as UTF-8; text looks mis-decoded."),
    "UNICODE_NOT_NFC": (WARNING, "Informational; text is preserved as supplied."),
    "NULL_LIKE_TOKEN": (WARNING, "Confirm whether the token means 'missing'."),
    # PDF integrity
    "PDF_PATH_MISSING": (REJECT, "Add `local_path: <path>` to notes."),
    "PDF_PATH_UNSAFE": (REJECT, "Use a relative path inside the PDF drop-zone."),
    "PDF_NOT_FOUND": (REJECT, "Copy the PDF into the drop-zone or correct the path."),
    "PDF_NOT_A_FILE": (REJECT, "Point local_path at a file, not a directory."),
    "PDF_NOT_READABLE": (REJECT, "Fix file permissions."),
    "PDF_EXTENSION_INVALID": (REJECT, "Reference a .pdf file."),
    "PDF_SIGNATURE_INVALID": (REJECT, "File is not a PDF; replace it with the original."),
    "SHA256_MISMATCH": (REJECT, "Re-hash the original PDF or restore the recorded file."),
    "FILENAME_IRREGULAR": (WARNING, "Filename is preserved; consider documenting it."),
    # duplicates
    "EXACT_DUPLICATE_EXTRA_COPY": (QUARANTINE, "Confirm and drop the extra copy at source."),
    "DUPLICATE_INVENTORY_ID_CONFLICT": (QUARANTINE, "Assign unique IDs or reconcile records."),
    "DUPLICATE_SOURCE_ID_CONFLICT": (QUARANTINE, "Assign unique source IDs or reconcile."),
    "DUPLICATE_SHA256": (QUARANTINE, "Same PDF bytes listed more than once; reconcile."),
    "SAME_PDF_DIFFERENT_SOURCE_ID": (QUARANTINE, "Decide which source ID owns the PDF."),
    "HASH_PERMISSION_CONFLICT": (QUARANTINE, "Same PDF with different rights; reconcile."),
    "DUPLICATE_PDF_CONTENT": (QUARANTINE, "Different files have identical bytes; reconcile."),
    "DUPLICATE_PDF_PATH": (QUARANTINE, "One file referenced by several rows; reconcile."),
    "POSSIBLE_NEAR_DUPLICATE": (WARNING, "Review signal only; not merged."),
}


@dataclass(frozen=True)
class Issue:
    code: str
    field: str | None
    message: str
    related_rows: tuple[int, ...] = ()

    @property
    def severity(self) -> str:
        return ISSUE_CATALOG[self.code][0]

    @property
    def suggested_action(self) -> str:
        return ISSUE_CATALOG[self.code][1]

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "field": self.field,
            "message": self.message,
            "related_rows": list(self.related_rows),
            "suggested_action": self.suggested_action,
        }


def disposition(issues: Iterable[Issue]) -> str:
    severities = {i.severity for i in issues}
    if REJECT in severities:
        return REJECTED
    if QUARANTINE in severities:
        return QUARANTINED
    return ACCEPTED


# --- Header -------------------------------------------------------------------------------


def check_header(header: Sequence[str]) -> dict[str, Any]:
    counts = collections.Counter(header)
    common = [c for c in header if c in CANONICAL_HEADER]
    return {
        "matches_canonical": tuple(header) == CANONICAL_HEADER,
        "column_count": len(header),
        "canonical_column_count": len(CANONICAL_HEADER),
        "missing_columns": [c for c in CANONICAL_HEADER if c not in counts],
        "unexpected_columns": [c for c in header if c not in CANONICAL_HEADER],
        "duplicate_columns": sorted(c for c, n in counts.items() if n > 1),
        "order_matches_for_common_columns": common == [c for c in CANONICAL_HEADER if c in counts],
    }


# --- Field rules ----------------------------------------------------------------------------


def _valid_iso_date(value: str) -> bool:
    if not ISO_DATE_PATTERN.fullmatch(value):
        return False
    try:
        dt.date.fromisoformat(value[:10])
    except ValueError:
        return False
    return True


def _check_id(row: dict[str, str], column: str, pattern: Any, format_code: str) -> list[Issue]:
    value = row[column]
    if not value:
        return []
    match = pattern.fullmatch(value)
    if not match:
        return [Issue(format_code, column, f"{column} does not match the documented format")]
    issues = []
    if row["class_level"] and match["cls"].lstrip("0") != row["class_level"]:
        issues.append(Issue("ID_CLASS_MISMATCH", column, f"{column} class prefix != class_level"))
    if row["subject_id"] and SUBJECT_CODES.get(match["subj"]) != row["subject_id"]:
        issues.append(Issue("ID_SUBJECT_MISMATCH", column, f"{column} subject code != subject_id"))
    return issues


def parse_local_path(notes: str) -> str | None:
    match = LOCAL_PATH_PATTERN.search(notes)
    if not match or not match["path"].strip():
        return None
    return match["path"].strip()


def find_reviewer_notes(row: dict[str, str]) -> list[tuple[str, str]]:
    """(field, annotation text) pairs found in factual fields."""
    found = []
    for column in FACTUAL_TEXT_FIELDS:
        for match in REVIEWER_NOTE_PATTERN.finditer(row[column]):
            found.append((column, match.group(0)))
    return found


def validate_fields(row: dict[str, str]) -> list[Issue]:
    """Rules for one well-formed, cleaned row (keys are the canonical columns)."""
    issues: list[Issue] = []
    for column in REQUIRED_FIELDS:
        if not row[column]:
            issues.append(Issue("REQUIRED_FIELD_MISSING", column, f"{column} is empty"))
    for column in OPTIONAL_FIELDS:
        if not row[column]:
            issues.append(Issue("METADATA_MISSING", column, f"{column} is empty"))

    if row["class_level"] and row["class_level"] not in CLASS_LEVELS:
        issues.append(Issue("CLASS_LEVEL_INVALID", "class_level", "class_level not in 6-10"))
    if row["subject_id"] and row["subject_id"] not in SUBJECT_IDS:
        issues.append(Issue("SUBJECT_ID_UNKNOWN", "subject_id", "subject_id not agreed"))
    if row["board"] and row["board"] not in BOARDS:
        issues.append(Issue("BOARD_OUT_OF_SCOPE", "board", "board is not CBSE"))
    if row["academic_session"]:
        match = ACADEMIC_SESSION_PATTERN.fullmatch(row["academic_session"])
        if not match or (int(match["start"]) + 1) % 100 != int(match["end"]):
            issues.append(
                Issue("ACADEMIC_SESSION_INVALID", "academic_session", "not YYYY-YY consecutive")
            )

    issues += _check_id(row, "inventory_id", INVENTORY_ID_PATTERN, "INVENTORY_ID_FORMAT_INVALID")
    issues += _check_id(row, "source_id", SOURCE_ID_PATTERN, "SOURCE_ID_FORMAT_INVALID")

    if row["sha256"] and not SHA256_PATTERN.fullmatch(row["sha256"]):
        issues.append(Issue("SHA256_FORMAT_INVALID", "sha256", "not lowercase 64-hex"))
    if row["source_url"] and not URL_PATTERN.fullmatch(row["source_url"]):
        issues.append(Issue("URL_INVALID", "source_url", "not an http(s) URL"))
    reference = row["permission_reference"]
    if reference.lower().startswith(("http:", "https:")) and not URL_PATTERN.fullmatch(reference):
        issues.append(Issue("URL_INVALID", "permission_reference", "malformed URL"))
    for column in ("acquired_at", "last_verified_at"):
        if row[column] and not _valid_iso_date(row[column]):
            issues.append(Issue("DATE_FORMAT_INVALID", column, f"{column} is not ISO 8601"))

    for column, vocabulary in VOCABULARIES.items():
        if row[column] and row[column] not in vocabulary:
            issues.append(Issue("VOCABULARY_UNKNOWN", column, f"{column} value not documented"))

    code = row["chapter_or_unit_code"]
    if code and row["item_type"] == "chapter_pdf" and not CHAPTER_CODE_PATTERN.fullmatch(code):
        issues.append(Issue("ITEM_CODE_MISMATCH", "chapter_or_unit_code", "not Chapter/Unit N"))
    if (
        code
        and row["item_type"] == "other_resource"
        and not OTHER_RESOURCE_CODE_PATTERN.fullmatch(code)
    ):
        issues.append(Issue("ITEM_CODE_MISMATCH", "chapter_or_unit_code", "not a resource code"))

    for column, annotation in find_reviewer_notes(row):
        issues.append(
            Issue(
                "REVIEWER_NOTE_IN_FACTUAL_FIELD",
                column,
                f"annotation {annotation!r} found in {column}; original value preserved",
            )
        )
    if row["validation_status"] == "needs_review":
        issues.append(Issue("TEAMMATE_FLAGGED_FOR_REVIEW", "validation_status", "needs_review"))
    elif row["validation_status"] == "failed":
        issues.append(Issue("TEAMMATE_VALIDATION_FAILED", "validation_status", "failed"))

    blocked = rights_blocked_categories(row)
    if blocked:
        issues.append(
            Issue("RIGHTS_NOT_GRANTED", None, "not authorised by inventory: " + ", ".join(blocked))
        )
    if row["notes"] and parse_local_path(row["notes"]) is None:
        issues.append(Issue("PDF_PATH_MISSING", "notes", "no `local_path:` in notes"))
    return issues


def rights_blocked_categories(row: dict[str, str]) -> list[str]:
    """Permission categories the row does NOT authorise (only `permitted` opens a gate)."""
    blocked = []
    for category, column in PERMISSION_CATEGORY_COLUMNS.items():
        if column is None or row.get(column) != "permitted" or row["rights_status"] != "approved":
            blocked.append(category)
    return blocked


# --- PDF integrity ------------------------------------------------------------------------------


@dataclass
class PdfCheck:
    local_path: str | None
    resolved_path: str | None = None  # relative to the PDF root
    inside_root: bool = False
    exists: bool = False
    is_file: bool = False
    readable: bool = False
    extension_ok: bool = False
    signature_ok: bool = False
    expected_sha256: str = ""
    computed_sha256: str | None = None
    sha256_match: bool = False
    issues: list[Issue] = field(default_factory=list)


def check_pdf(
    pdf_root: Path, local_path: str | None, expected_sha256: str, hash_cache: dict[Path, str]
) -> PdfCheck:
    result = PdfCheck(local_path=local_path, expected_sha256=expected_sha256)
    if local_path is None:
        return result  # PDF_PATH_MISSING is raised by validate_fields
    pure = PurePosixPath(local_path)
    root = pdf_root.resolve()
    if pure.is_absolute() or ".." in pure.parts or "\\" in local_path:
        result.issues.append(Issue("PDF_PATH_UNSAFE", "notes", "absolute or parent-relative path"))
        return result
    candidate = (root / Path(*pure.parts)).resolve()
    if not candidate.is_relative_to(root):
        result.issues.append(Issue("PDF_PATH_UNSAFE", "notes", "path escapes the PDF root"))
        return result
    result.inside_root = True
    result.resolved_path = candidate.relative_to(root).as_posix()
    if pure.name != pure.name.strip() or ".." in pure.name:
        result.issues.append(Issue("FILENAME_IRREGULAR", "notes", "irregular filename"))
    result.exists = candidate.exists()
    if not result.exists:
        result.issues.append(Issue("PDF_NOT_FOUND", "notes", "file does not exist"))
        return result
    result.is_file = candidate.is_file()
    if not result.is_file:
        result.issues.append(Issue("PDF_NOT_A_FILE", "notes", "path is not a regular file"))
        return result
    result.extension_ok = candidate.suffix.lower() == ".pdf"
    if not result.extension_ok:
        result.issues.append(Issue("PDF_EXTENSION_INVALID", "notes", "extension is not .pdf"))
    try:
        with candidate.open("rb") as handle:
            signature = handle.read(len(PDF_SIGNATURE))
        if candidate not in hash_cache:
            hash_cache[candidate] = sha256_file(candidate)
    except OSError:
        result.issues.append(Issue("PDF_NOT_READABLE", "notes", "file cannot be read"))
        return result
    result.readable = True
    result.signature_ok = signature == PDF_SIGNATURE
    if not result.signature_ok:
        result.issues.append(Issue("PDF_SIGNATURE_INVALID", "notes", "missing %PDF- signature"))
    result.computed_sha256 = hash_cache[candidate]
    result.sha256_match = result.computed_sha256 == expected_sha256
    # A malformed recorded hash is reported once, as SHA256_FORMAT_INVALID.
    if SHA256_PATTERN.fullmatch(expected_sha256) and not result.sha256_match:
        result.issues.append(Issue("SHA256_MISMATCH", "sha256", "file hash != recorded sha256"))
    return result


# --- Duplicates ------------------------------------------------------------------------------


@dataclass
class RowView:
    """A well-formed row as seen by cross-row checks."""

    data_index: int
    values: dict[str, str]
    resolved_path: str | None
    computed_sha256: str | None


def _groups(rows: Sequence[RowView], key: Any) -> list[list[RowView]]:
    buckets: dict[Any, list[RowView]] = collections.defaultdict(list)
    for row in rows:
        k = key(row)
        if k:
            buckets[k].append(row)
    return [group for _, group in sorted(buckets.items()) if len(group) > 1]


def duplicate_analysis(rows: Sequence[RowView]) -> tuple[dict[int, list[Issue]], dict[str, Any]]:
    issues: dict[int, list[Issue]] = collections.defaultdict(list)
    report: dict[str, Any] = {}

    def flag(group: list[RowView], code: str, label: str) -> list[int]:
        members = tuple(r.data_index for r in group)
        for row in group:
            issues[row.data_index].append(
                Issue(code, None, f"{label}; rows {list(members)}", members)
            )
        return list(members)

    # 1. Exact duplicates: the first occurrence stays eligible; extra copies are quarantined.
    exact_groups = _groups(rows, lambda r: tuple(r.values[c] for c in CANONICAL_HEADER))
    extra_copies: set[int] = set()
    report["exact_duplicate_groups"] = []
    for group in exact_groups:
        first, *extras = group
        for row in extras:
            extra_copies.add(row.data_index)
            issues[row.data_index].append(
                Issue(
                    "EXACT_DUPLICATE_EXTRA_COPY",
                    None,
                    f"identical to data row {first.data_index}",
                    (first.data_index,),
                )
            )
        report["exact_duplicate_groups"].append(
            {"kept_row": first.data_index, "extra_copies": [r.data_index for r in extras]}
        )
    unique = [r for r in rows if r.data_index not in extra_copies]

    report["duplicate_inventory_ids"] = [
        flag(g, "DUPLICATE_INVENTORY_ID_CONFLICT", "inventory_id shared with conflicting content")
        for g in _groups(unique, lambda r: r.values["inventory_id"])
    ]
    report["duplicate_source_ids"] = [
        flag(g, "DUPLICATE_SOURCE_ID_CONFLICT", "source_id shared with conflicting content")
        for g in _groups(unique, lambda r: r.values["source_id"])
    ]

    report["duplicate_recorded_sha256"] = []
    report["same_pdf_different_source_id"] = []
    report["sha256_permission_conflicts"] = []
    for group in _groups(unique, lambda r: r.values["sha256"]):
        report["duplicate_recorded_sha256"].append(
            flag(group, "DUPLICATE_SHA256", "recorded sha256 shared")
        )
        if len({r.values["source_id"] for r in group}) > 1:
            report["same_pdf_different_source_id"].append(
                flag(group, "SAME_PDF_DIFFERENT_SOURCE_ID", "same PDF under different source IDs")
            )
        rights = {tuple(r.values[c] for c in ("rights_status", *PERMISSION_FIELDS)) for r in group}
        if len(rights) > 1:
            report["sha256_permission_conflicts"].append(
                flag(group, "HASH_PERMISSION_CONFLICT", "same PDF with different permissions")
            )

    recorded_groups = {tuple(g) for g in report["duplicate_recorded_sha256"]}
    report["duplicate_pdf_content"] = [
        flag(g, "DUPLICATE_PDF_CONTENT", "different rows' files have identical bytes")
        for g in _groups(unique, lambda r: r.computed_sha256)
        if tuple(r.data_index for r in g) not in recorded_groups
    ]
    # casefold: macOS and Windows file systems are usually case-insensitive.
    report["duplicate_pdf_paths"] = [
        flag(g, "DUPLICATE_PDF_PATH", "same PDF path referenced by several rows")
        for g in _groups(unique, lambda r: r.resolved_path.casefold() if r.resolved_path else None)
    ]

    near_key = ("class_level", "subject_id", "course_or_language", "resource_title")
    report["possible_near_duplicates"] = [
        flag(g, "POSSIBLE_NEAR_DUPLICATE", "same book and chapter/unit code")
        for g in _groups(
            unique,
            lambda r: (
                tuple(r.values[c].casefold() for c in near_key)
                + (r.values["chapter_or_unit_code"].casefold(),)
            ),
        )
    ]
    report["counts"] = {
        "exact_duplicate_extra_copies": len(extra_copies),
        **{k: len(v) for k, v in report.items() if isinstance(v, list)},
    }
    return issues, report


# --- Coverage --------------------------------------------------------------------------------


def coverage_report(rows: Sequence[tuple[dict[str, str], str]]) -> list[dict[str, Any]]:
    """25 class x subject combinations; `rows` are (values, disposition) pairs."""
    chapter_counts: dict[str, list[int]] = collections.defaultdict(list)
    table = []
    for cls in CLASS_LEVELS:
        for subject in SUBJECT_IDS:
            members = [
                (v, d) for v, d in rows if v["class_level"] == cls and v["subject_id"] == subject
            ]
            chapters = [(v, d) for v, d in members if v["item_type"] == "chapter_pdf"]
            entry = {
                "class_level": cls,
                "subject_id": subject,
                "rows": len(members),
                "chapter_pdf_rows": len(chapters),
                "other_resource_rows": len(members) - len(chapters),
                "accepted": sum(d == ACCEPTED for _, d in members),
                "quarantined": sum(d == QUARANTINED for _, d in members),
                "rejected": sum(d == REJECTED for _, d in members),
                "accepted_chapter_pdfs": sum(d == ACCEPTED for _, d in chapters),
                "courses": sorted({v["course_or_language"] for v, _ in members}),
                "books": sorted({v["resource_title"] for v, _ in members}),
            }
            chapter_counts[subject].append(len(chapters))
            table.append(entry)
    for entry in table:
        median = statistics.median(chapter_counts[entry["subject_id"]])
        if entry["rows"] == 0:
            entry["status"] = "missing"
        elif entry["accepted_chapter_pdfs"] == 0:
            entry["status"] = "present_not_accepted"
        elif entry["chapter_pdf_rows"] < 0.5 * median:
            entry["status"] = "covered_low_count_review_signal"
        else:
            entry["status"] = "covered"
        entry["subject_median_chapter_pdfs"] = median
    return table
