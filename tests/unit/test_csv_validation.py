"""Field rules, PDF integrity, duplicate categories, coverage and dispositions."""

from __future__ import annotations

import hashlib

import pytest

from data_pipeline.inventory_schema import CANONICAL_HEADER, CLASS_LEVELS, SUBJECT_IDS
from data_pipeline.stages.validate_csv import (
    ACCEPTED,
    ISSUE_CATALOG,
    QUARANTINED,
    REJECTED,
    Issue,
    RowView,
    check_header,
    check_pdf,
    coverage_report,
    disposition,
    duplicate_analysis,
    parse_local_path,
    rights_blocked_categories,
    validate_fields,
)


def codes(issues: list[Issue], severity: str | None = None) -> set[str]:
    return {i.code for i in issues if severity is None or i.severity == severity}


# --- header -----------------------------------------------------------------------------


def test_exact_canonical_header() -> None:
    result = check_header(CANONICAL_HEADER)
    assert result["matches_canonical"] and len(CANONICAL_HEADER) == 29
    assert result["missing_columns"] == result["unexpected_columns"] == []


def test_missing_and_unexpected_columns() -> None:
    header = [c for c in CANONICAL_HEADER if c != "source_url"] + ["teammate_comment"]
    result = check_header(header)
    assert not result["matches_canonical"]
    assert result["missing_columns"] == ["source_url"]
    assert result["unexpected_columns"] == ["teammate_comment"]


def test_column_order_is_validated() -> None:
    swapped = list(CANONICAL_HEADER)
    swapped[0], swapped[1] = swapped[1], swapped[0]
    result = check_header(swapped)
    assert not result["matches_canonical"]
    assert result["missing_columns"] == [] and result["unexpected_columns"] == []
    assert result["order_matches_for_common_columns"] is False


def test_duplicate_columns() -> None:
    assert check_header([*CANONICAL_HEADER, "notes"])["duplicate_columns"] == ["notes"]


# --- field rules ------------------------------------------------------------------------


def test_valid_row_has_only_warnings(inventory) -> None:
    issues = validate_fields(inventory.row())
    assert codes(issues, "reject") == set() and codes(issues, "quarantine") == set()
    assert codes(issues) == {"METADATA_MISSING", "RIGHTS_NOT_GRANTED"}
    missing = {i.field for i in issues if i.code == "METADATA_MISSING"}
    assert missing == {"topic_title", "learning_objective", "source_url", "acquired_at"}
    assert disposition(issues) == ACCEPTED


@pytest.mark.parametrize("column", ["inventory_id", "chapter_title", "sha256", "notes"])
def test_missing_required_field_rejects(inventory, column: str) -> None:
    issues = validate_fields(inventory.row(**{column: ""}))
    assert any(i.code == "REQUIRED_FIELD_MISSING" and i.field == column for i in issues)
    assert disposition(issues) == REJECTED


@pytest.mark.parametrize(
    ("overrides", "code", "expected"),
    [
        ({"class_level": "06"}, "CLASS_LEVEL_INVALID", REJECTED),
        ({"class_level": "11"}, "CLASS_LEVEL_INVALID", REJECTED),
        ({"subject_id": "maths"}, "SUBJECT_ID_UNKNOWN", REJECTED),
        ({"board": "ICSE"}, "BOARD_OUT_OF_SCOPE", QUARANTINED),
        ({"academic_session": "2026-28"}, "ACADEMIC_SESSION_INVALID", REJECTED),
        ({"inventory_id": "CT-6-MAT-1"}, "INVENTORY_ID_FORMAT_INVALID", REJECTED),
        ({"inventory_id": "CT-C07-MAT-001"}, "ID_CLASS_MISMATCH", QUARANTINED),
        ({"source_id": "SRC-C06-SCI-FECU1-01"}, "ID_SUBJECT_MISMATCH", QUARANTINED),
        ({"sha256": "ABC" + "0" * 61}, "SHA256_FORMAT_INVALID", REJECTED),
        ({"source_url": "ncert.nic.in/textbook"}, "URL_INVALID", REJECTED),
        ({"acquired_at": "31/10/2026"}, "DATE_FORMAT_INVALID", REJECTED),
        ({"last_verified_at": "2026-02-30"}, "DATE_FORMAT_INVALID", REJECTED),
        ({"rights_status": "permission_required"}, "VOCABULARY_UNKNOWN", QUARANTINED),
        ({"permitted_training": "allowed"}, "VOCABULARY_UNKNOWN", QUARANTINED),
        ({"chapter_or_unit_code": "Prelims"}, "ITEM_CODE_MISMATCH", QUARANTINED),
        ({"validation_status": "needs_review"}, "TEAMMATE_FLAGGED_FOR_REVIEW", QUARANTINED),
        ({"notes": "Source: no locator"}, "PDF_PATH_MISSING", REJECTED),
    ],
)
def test_field_rules(inventory, overrides: dict[str, str], code: str, expected: str) -> None:
    issues = validate_fields(inventory.row(**overrides))
    assert code in codes(issues)
    assert disposition(issues) == expected


def test_valid_dates_and_urls_pass(inventory) -> None:
    row = inventory.row(
        acquired_at="2026-10-30T12:00:00+05:30", source_url="https://ncert.nic.in/textbook.php"
    )
    assert codes(validate_fields(row), "reject") == set()


def test_leading_zero_ids_remain_strings(inventory) -> None:
    row = inventory.row(7)
    assert row["inventory_id"] == "CT-C06-MAT-007"
    assert codes(validate_fields(row), "reject") == set()


def test_reviewer_note_is_flagged_and_value_preserved(inventory) -> None:
    title = "The Proposal [Note: File named with double dot jewe209..pdf]"
    row = inventory.row(chapter_title=title)
    issues = validate_fields(row)
    note = [i for i in issues if i.code == "REVIEWER_NOTE_IN_FACTUAL_FIELD"]
    assert len(note) == 1 and note[0].field == "chapter_title"
    assert "[Note: File named with double dot jewe209..pdf]" in note[0].message
    assert row["chapter_title"] == title  # validation never edits values
    assert disposition(issues) == QUARANTINED


def test_parse_local_path() -> None:
    assert parse_local_path("local_path: class 6/x y/a.pdf | Source: z") == "class 6/x y/a.pdf"
    assert parse_local_path("Source: z | local_path:  b..pdf  ") == "b..pdf"
    assert parse_local_path("Source: z") is None
    assert parse_local_path("local_path:  | x") is None


def test_rights_categories_without_columns_stay_blocked(inventory) -> None:
    granted = inventory.row(
        rights_status="approved",
        permitted_processing="permitted",
        permitted_indexing="permitted",
        permitted_training="permitted",
        permitted_display="permitted",
    )
    assert rights_blocked_categories(granted) == ["external_model_processing", "redistribution"]
    assert len(rights_blocked_categories(inventory.row())) == 7


def test_every_issue_code_has_a_valid_severity() -> None:
    assert {severity for severity, _ in ISSUE_CATALOG.values()} == {
        "reject",
        "quarantine",
        "warning",
    }


# --- PDF integrity ------------------------------------------------------------------------


def test_matching_pdf(inventory) -> None:
    sha = inventory.pdf("class 6/a.pdf")
    result = check_pdf(inventory.pdf_root, "class 6/a.pdf", sha, {})
    assert result.issues == []
    assert result.exists and result.readable and result.signature_ok and result.sha256_match
    assert result.resolved_path == "class 6/a.pdf"


@pytest.mark.parametrize(
    ("local_path", "code"),
    [
        ("../outside.pdf", "PDF_PATH_UNSAFE"),
        ("/etc/hosts", "PDF_PATH_UNSAFE"),
        ("class 6\\a.pdf", "PDF_PATH_UNSAFE"),
        ("class 6/missing.pdf", "PDF_NOT_FOUND"),
        ("class 6", "PDF_NOT_A_FILE"),
    ],
)
def test_pdf_path_failures(inventory, local_path: str, code: str) -> None:
    inventory.pdf("class 6/a.pdf")
    result = check_pdf(inventory.pdf_root, local_path, "0" * 64, {})
    assert code in codes(result.issues, "reject")


def test_symlink_escaping_the_root_is_unsafe(inventory, tmp_path) -> None:
    outside = tmp_path / "secret.pdf"
    outside.write_bytes(b"%PDF-1.4 outside")
    (inventory.pdf_root / "link.pdf").symlink_to(outside)
    result = check_pdf(inventory.pdf_root, "link.pdf", "0" * 64, {})
    assert codes(result.issues) == {"PDF_PATH_UNSAFE"}


def test_wrong_extension_and_signature(inventory) -> None:
    sha = inventory.pdf("cover.jpg", b"\xff\xd8\xff\xe0 not a pdf")
    result = check_pdf(inventory.pdf_root, "cover.jpg", sha, {})
    assert codes(result.issues) == {"PDF_EXTENSION_INVALID", "PDF_SIGNATURE_INVALID"}


def test_hash_mismatch_rejects(inventory) -> None:
    inventory.pdf("a.pdf")
    result = check_pdf(inventory.pdf_root, "a.pdf", "f" * 64, {})
    assert codes(result.issues) == {"SHA256_MISMATCH"}
    assert (
        result.computed_sha256
        == hashlib.sha256((inventory.pdf_root / "a.pdf").read_bytes()).hexdigest()
    )


def test_malformed_recorded_hash_is_not_double_reported(inventory) -> None:
    inventory.pdf("a.pdf")
    assert check_pdf(inventory.pdf_root, "a.pdf", "not-a-hash", {}).issues == []


def test_irregular_filename_is_a_warning(inventory) -> None:
    sha = inventory.pdf("jewe204..pdf")
    result = check_pdf(inventory.pdf_root, "jewe204..pdf", sha, {})
    assert codes(result.issues) == {"FILENAME_IRREGULAR"}
    assert disposition(result.issues) == ACCEPTED


def test_hash_cache_reads_each_file_once(inventory) -> None:
    sha = inventory.pdf("a.pdf")
    cache: dict = {}
    check_pdf(inventory.pdf_root, "a.pdf", sha, cache)
    (inventory.pdf_root / "a.pdf").write_bytes(b"%PDF-changed")  # cache must win within a run
    assert check_pdf(inventory.pdf_root, "a.pdf", sha, cache).sha256_match


# --- duplicates ----------------------------------------------------------------------------


def view(index: int, values: dict[str, str], path: str | None = None, sha: str | None = None):
    return RowView(index, values, path, sha)


def test_exact_duplicates_keep_first_and_quarantine_extra_copies(inventory) -> None:
    row = inventory.row(1)
    issues, report = duplicate_analysis(
        [view(1, row, "p1", "h1"), view(2, dict(row), "p1", "h1"), view(3, dict(row), "p1", "h1")]
    )
    assert 1 not in issues
    assert codes(issues[2]) == codes(issues[3]) == {"EXACT_DUPLICATE_EXTRA_COPY"}
    assert issues[3][0].related_rows == (1,)
    assert report["counts"]["exact_duplicate_extra_copies"] == 2


def test_duplicate_id_with_conflicting_metadata(inventory) -> None:
    a = inventory.row(1)
    b = inventory.row(2, inventory_id=a["inventory_id"])
    issues, report = duplicate_analysis([view(1, a, "p1", "h1"), view(2, b, "p2", "h2")])
    assert "DUPLICATE_INVENTORY_ID_CONFLICT" in codes(issues[1]) & codes(issues[2])
    assert report["duplicate_inventory_ids"] == [[1, 2]]


def test_same_pdf_under_different_source_ids_and_rights(inventory) -> None:
    a = inventory.row(1)
    b = inventory.row(2, sha256=a["sha256"], permitted_display="permitted")
    issues, report = duplicate_analysis([view(1, a, "p1", "h"), view(2, b, "p2", "h")])
    expected = {"DUPLICATE_SHA256", "SAME_PDF_DIFFERENT_SOURCE_ID", "HASH_PERMISSION_CONFLICT"}
    assert expected <= codes(issues[1]) and expected <= codes(issues[2])
    assert report["sha256_permission_conflicts"] == [[1, 2]]
    assert all(i.severity == "quarantine" for i in issues[1])


def test_identical_file_bytes_and_shared_paths(inventory) -> None:
    a, b, c = inventory.row(1), inventory.row(2), inventory.row(3)
    issues, report = duplicate_analysis(
        [view(1, a, "x/A.pdf", "same"), view(2, b, "y.pdf", "same"), view(3, c, "x/a.pdf", "c")]
    )
    assert "DUPLICATE_PDF_CONTENT" in codes(issues[1]) & codes(issues[2])
    assert "DUPLICATE_PDF_PATH" in codes(issues[1]) & codes(issues[3])  # case-insensitive
    assert report["duplicate_pdf_paths"] == [[1, 3]]


def test_near_duplicates_are_warnings_only(inventory) -> None:
    a = inventory.row(1, chapter_or_unit_code="Chapter 1")
    b = inventory.row(2, chapter_or_unit_code="chapter 1")
    issues, _ = duplicate_analysis([view(1, a, "p1", "h1"), view(2, b, "p2", "h2")])
    assert codes(issues[1]) == {"POSSIBLE_NEAR_DUPLICATE"}
    assert disposition(issues[1]) == ACCEPTED


# --- coverage and disposition --------------------------------------------------------------


def test_coverage_reports_all_25_combinations(inventory) -> None:
    rows = []
    for cls in CLASS_LEVELS:
        for subject in SUBJECT_IDS:
            for _ in range(4):
                rows.append(
                    (
                        {
                            "class_level": cls,
                            "subject_id": subject,
                            "item_type": "chapter_pdf",
                            "course_or_language": "C",
                            "resource_title": "B",
                        },
                        ACCEPTED,
                    )
                )
    rows = [r for r in rows if (r[0]["class_level"], r[0]["subject_id"]) != ("9", "hindi")]
    rows = [
        r
        for i, r in enumerate(rows)
        if not (r[0]["class_level"] == "8" and r[0]["subject_id"] == "english" and i % 4)
    ]
    table = coverage_report(rows)
    assert len(table) == 25
    status = {(e["class_level"], e["subject_id"]): e["status"] for e in table}
    assert status[("9", "hindi")] == "missing"
    assert status[("8", "english")] == "covered_low_count_review_signal"
    assert status[("6", "science")] == "covered"


def test_quarantined_only_combination_is_not_covered() -> None:
    rows = [
        (
            {
                "class_level": "6",
                "subject_id": "hindi",
                "item_type": "chapter_pdf",
                "course_or_language": "",
                "resource_title": "",
            },
            QUARANTINED,
        )
    ]
    entry = next(
        e for e in coverage_report(rows) if e["subject_id"] == "hindi" and e["class_level"] == "6"
    )
    assert entry["status"] == "present_not_accepted"


def test_disposition_priority() -> None:
    warn = Issue("METADATA_MISSING", "x", "")
    quarantine = Issue("REVIEWER_NOTE_IN_FACTUAL_FIELD", "x", "")
    reject = Issue("SHA256_MISMATCH", "x", "")
    assert disposition([]) == disposition([warn]) == ACCEPTED
    assert disposition([warn, quarantine]) == QUARANTINED
    assert disposition([quarantine, reject]) == REJECTED
