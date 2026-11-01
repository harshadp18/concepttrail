"""D-053 page-review attestation and Phase 4 pilot sign-off: evidence-bound and fail closed."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from data_pipeline import owner_attestations as oa
from data_pipeline import teacher_validation as tv
from data_pipeline import triage_review_queue as triage

REVIEW_HEADER = ["source_id", "pdf_page_index", "human_reviewed", "reviewer", "accurate_text"]


def put(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def put_json(root: Path, rel: str, payload: object) -> Path:
    return put(root, rel, json.dumps(payload))


def teacher_attestation() -> dict:
    chapters = [
        {
            "inventory_id": f"CT-C09-MAT-{n:03d}",
            "source_id": f"SRC-C09-MAT-T{n}-01",
            "objectives": [
                {"text": f"Explain {n}.{k}.", "evidence_terms": [f"t{n}.{k}"]}
                for k in range(1, (6 if n <= 6 else 5) + 1)
            ],
        }
        for n in range(1, 10)
    ]
    return tv.build_attestation({"record_id": "LO", "chapters": chapters}, [], "a" * 64)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    rows = [
        ["SRC-A", "0", "false", "ai_assisted:model", "ok"],
        ["SRC-A", "3", "false", "ai_assisted:model", "ok"],
        ["SRC-B", "9", "false", "ai_assisted:model", "ok"],
    ]
    csv_path = tmp_path / oa.REL["review_csv"]
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(REVIEW_HEADER)
        writer.writerows(rows)
    put(tmp_path, oa.REL["review_md"], "# AI-assisted review\n")
    put_json(tmp_path, oa.REL["inspection_index"], [{"source_id": "SRC-A", "page_index": 0}])
    put_json(tmp_path, oa.REL["teacher"], teacher_attestation())
    return tmp_path


def record_d053(root: Path) -> dict:
    record = oa.build_d053(root)
    tv.write_once(root / oa.REL["d053"], record)
    return record


# --- D-053 ----------------------------------------------------------------------------------


def test_d053_records_effective_review_without_inventing_findings(root: Path) -> None:
    record = record_d053(root)
    assert record["effective_status"] == {"human_reviewed": True, "basis": "owner_attestation"}
    assert record["authorization_basis"] == "owner_attestation"
    assert record["page_count"] == 3
    assert record["individual_findings_status"] == "not_recorded"
    assert "reviewer identities" in record["not_held_by_the_project"]
    assert any("every reviewed page passed" in c for c in record["not_claimed"])
    assert set(record["bound_evidence"]) == {"review_csv", "review_md", "inspection_index"}
    assert all(len(r["sha256"]) == 64 for r in record["bound_evidence"].values())
    verdict = oa.verify_d053(root)
    assert verdict["status"] == oa.VALID and len(verdict["pages"]) == 3


def test_original_review_rows_keep_human_reviewed_false(root: Path) -> None:
    record_d053(root)
    before = (root / oa.REL["review_csv"]).read_bytes()
    with (root / oa.REL["review_csv"]).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    effective = oa.effective_page_review(rows, oa.verify_d053(root))
    assert [r["human_reviewed_historical"] for r in effective] == ["false"] * 3
    assert all(
        r["human_reviewed_effective"] and r["effective_basis"] == "owner_attestation"
        for r in effective
    )
    assert (root / oa.REL["review_csv"]).read_bytes() == before  # evidence untouched
    assert all(r["human_reviewed"] == "false" for r in rows)  # input rows not mutated


def test_missing_attestation_fails_closed(root: Path) -> None:
    verdict = oa.verify_d053(root)
    assert verdict["status"] == oa.ABSENT and verdict["pages"] == []
    with (root / oa.REL["review_csv"]).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert not any(r["human_reviewed_effective"] for r in oa.effective_page_review(rows, verdict))


@pytest.mark.parametrize("target", ["review_csv", "review_md", "inspection_index"])
def test_changed_evidence_makes_the_attestation_stale(root: Path, target: str) -> None:
    record_d053(root)
    with (root / oa.REL[target]).open("a", encoding="utf-8") as handle:
        handle.write(" ")
    verdict = oa.verify_d053(root)
    assert verdict["status"] == oa.STALE
    assert any("changed since attestation" in p for p in verdict["problems"])
    assert verdict["pages"] == []  # nothing counts as reviewed


def test_missing_evidence_is_stale_not_valid(root: Path) -> None:
    record_d053(root)
    (root / oa.REL["review_md"]).unlink()
    verdict = oa.verify_d053(root)
    assert verdict["status"] == oa.STALE and "missing" in verdict["problems"][0]


def test_tampered_or_malformed_attestation_is_invalid(root: Path) -> None:
    record = record_d053(root)
    path = root / oa.REL["d053"]
    for key, value in (
        ("effective_status", {"human_reviewed": True, "basis": "independent_audit"}),
        ("individual_findings_status", "all_passed"),
        ("record_id", "OTHER"),
        ("authorization_basis", "verified"),
    ):
        path.write_text(json.dumps({**record, key: value}), encoding="utf-8")
        assert oa.verify_d053(root)["status"] == oa.INVALID, key
    path.write_text(json.dumps({**record, "pages_in_scope": record["pages_in_scope"][:-1]}))
    assert oa.verify_d053(root)["status"] == oa.INVALID  # page set no longer matches its digest
    path.write_text("not json")
    assert oa.verify_d053(root)["status"] == oa.INVALID


def test_d053_refuses_an_edited_or_missing_review_record(root: Path) -> None:
    path = root / oa.REL["review_csv"]
    path.write_text(path.read_text().replace(",false,", ",true,", 1), encoding="utf-8")
    with pytest.raises(oa.AttestationError, match="unedited AI-assisted"):
        oa.build_d053(root)
    path.unlink()
    with pytest.raises(oa.AttestationError, match="missing"):
        oa.build_d053(root)


def test_d053_is_write_once(root: Path) -> None:
    record = record_d053(root)
    path = root / oa.REL["d053"]
    assert tv.write_once(path, oa.build_d053(root)) == (path, False)  # repeat: no change
    with (root / oa.REL["review_csv"]).open("a", encoding="utf-8", newline="") as handle:
        handle.write("SRC-C,1,false,ai_assisted:model,ok\n")
    with pytest.raises(RuntimeError, match="immutable"):
        tv.write_once(path, oa.build_d053(root))
    assert json.loads(path.read_text("utf-8")) == record


# --- triage uses the verdict ----------------------------------------------------------------


def test_triage_resolves_only_pages_inside_the_attested_set(root: Path) -> None:
    record_d053(root)
    verdict = oa.verify_d053(root)
    covered = {
        "priority": "m",
        "item": "page_review",
        "source_document_id": "SRC-A",
        "pdf_page_indexes": "0 3",
    }
    partly = {**covered, "pdf_page_indexes": "0 3 5"}
    record = {"chapter_title_check": "consistent"}
    assert triage.triage_item(covered, record, {}, None, verdict)[0] == "resolved"
    assert triage.triage_item(partly, record, {}, None, verdict)[0] == "open"
    assert (
        triage.triage_item(covered, record, {}, None, {"status": "stale", "pages": []})[0] == "open"
    )
    assert triage.triage_item(covered, record, {}, None, None)[0] == "open"
    weak = {
        "priority": "h",
        "item": "ocr_required",
        "source_document_id": "SRC-B",
        "pdf_page_indexes": "9",
    }
    assert (
        triage.triage_item(
            weak, record, {"ocr_low_confidence_or_empty": {"reason": "weak"}}, None, verdict
        )[0]
        == "resolved"
    )
    assert (
        triage.triage_item(weak, record, {"ocr_required": {"reason": "not run"}}, None, verdict)[0]
        == "open"
    )


# --- sign-off -------------------------------------------------------------------------------


def make_signoff_evidence(root: Path) -> None:
    for name in (
        "pilot_report",
        "continuation_report",
        "owner_decisions_report",
        "reconciliation_report",
    ):
        put(root, oa.SIGNOFF_EVIDENCE[name], f"# {name}\n")
    put_json(
        root,
        oa.SIGNOFF_EVIDENCE["run_manifest"],
        {
            "versions": {"extractor": "x/1"},
            "database_writes": "none",
            "external_ai_calls": "none",
            "documents": [
                {
                    "source_id": "SRC-A",
                    "inventory_id": "CT-A",
                    "status": "processed",
                    "sha256_before": "a" * 64,
                    "devanagari_repair": {
                        "rule": "D-044",
                        "corrections_total": 5,
                        "repeated_vowel_signs_remaining": 1,
                        "other_repeats_flagged": 2,
                    },
                },
                {
                    "source_id": "SRC-B",
                    "inventory_id": "CT-B",
                    "status": "processed",
                    "sha256_before": "b" * 64,
                },
            ],
        },
    )
    put_json(
        root,
        oa.SIGNOFF_EVIDENCE["quality_report"],
        {
            "SRC-A": {
                "pages": 10,
                "extraction_failures": 0,
                "ocr": {"statuses": {"completed": 2}},
                "findings": [{"severity": "low", "code": "OCR_COMPLETED_NEEDS_SPOT_CHECK"}],
            },
            "SRC-B": {
                "pages": 5,
                "extraction_failures": 0,
                "ocr": {"statuses": {"low_confidence": 1}},
                "findings": [{"severity": "medium", "code": "OCR_LOW_CONFIDENCE_OR_EMPTY"}],
            },
        },
    )
    put_json(
        root,
        oa.SIGNOFF_EVIDENCE["provenance_manifest"],
        {"teacher_validation": {"status": "applied"}},
    )
    put_json(root, oa.SIGNOFF_EVIDENCE["pilot_csv_manifest"], {"content": {"row_count": 2}})
    put_json(
        root,
        oa.SIGNOFF_EVIDENCE["review_triage"],
        {
            "dispositions": {"resolved": 3, "open": 2, "owner_decision": 0},
            "by_item": {"page_review": {"open": 2}},
            "new_items_by_kind": {"ocr_quality_review": 1},
        },
    )
    put_json(root, oa.SIGNOFF_EVIDENCE["project_use_authorization"], {"record_id": "AUTH-test"})


@pytest.fixture
def signed(root: Path) -> Path:
    record_d053(root)
    make_signoff_evidence(root)
    tv.write_once(root / oa.REL["signoff"], oa.build_signoff(root))
    return root


def test_signoff_is_approved_bound_and_keeps_limitations(signed: Path) -> None:
    record = json.loads((signed / oa.REL["signoff"]).read_text("utf-8"))
    assert (record["decision"], record["signed_off_on"], record["basis"]) == (
        "approved",
        "2026-10-31",
        "owner_approval",
    )
    assert set(record["bound_evidence"]) == set(oa.SIGNOFF_EVIDENCE)
    gate = record["recorded_quality_gate_results"]
    assert (gate["documents"], gate["pages_processed"], gate["extraction_failures"]) == (2, 15, 0)
    assert gate["ocr_page_statuses"] == {"completed": 2, "low_confidence": 1}
    assert gate["review_triage"]["open"] == 2  # open items are retained, not hidden
    assert gate["hindi_repair"]["repeated_vowel_signs_remaining"] == 1
    assert any("not recorded" in x for x in record["retained_limitations"])
    assert any("separately approved" in x for x in record["does_not_claim"])
    assert [d["source_id"] for d in record["scope"]["pilot_documents"]] == ["SRC-A", "SRC-B"]
    assert oa.verify_signoff(signed)["status"] == oa.VALID


def test_signoff_is_stale_when_any_bound_evidence_changes(signed: Path) -> None:
    for name in ("pilot_report", "run_manifest", "review_triage", "teacher_validation_attestation"):
        path = signed / oa.SIGNOFF_EVIDENCE[name]
        original = path.read_bytes()
        path.write_bytes(original + b" ")
        verdict = oa.verify_signoff(signed)
        assert verdict["status"] == oa.STALE and name in verdict["problems"][0], name
        path.write_bytes(original)
    assert oa.verify_signoff(signed)["status"] == oa.VALID


def test_signoff_requires_a_valid_d053_and_fails_if_it_goes_stale(root: Path, signed: Path) -> None:
    with (signed / oa.REL["review_md"]).open("a", encoding="utf-8") as handle:
        handle.write("edited")
    verdict = oa.verify_signoff(signed)
    assert verdict["status"] == oa.STALE and any("D-053" in p for p in verdict["problems"])


def test_signoff_cannot_be_built_without_valid_prerequisites(root: Path) -> None:
    make_signoff_evidence(root)
    with pytest.raises(oa.AttestationError, match="D-053 attestation is not valid"):
        oa.build_signoff(root)  # no D-053 attestation yet
    record_d053(root)
    put_json(
        root,
        oa.SIGNOFF_EVIDENCE["provenance_manifest"],
        {"teacher_validation": {"status": "attestation_absent"}},
    )
    with pytest.raises(oa.AttestationError, match="teacher validation applied"):
        oa.build_signoff(root)
    put_json(
        root,
        oa.SIGNOFF_EVIDENCE["provenance_manifest"],
        {"teacher_validation": {"status": "applied"}},
    )
    (root / oa.SIGNOFF_EVIDENCE["pilot_report"]).unlink()
    with pytest.raises(oa.AttestationError, match="missing"):
        oa.build_signoff(root)


def test_missing_and_malformed_signoff_do_not_count_as_approval(signed: Path) -> None:
    path = signed / oa.REL["signoff"]
    record = json.loads(path.read_text("utf-8"))
    path.write_text(json.dumps({**record, "decision": "rejected"}), encoding="utf-8")
    assert oa.verify_signoff(signed)["status"] == oa.INVALID
    path.write_text(json.dumps({**record, "bound_evidence": {}}), encoding="utf-8")
    assert oa.verify_signoff(signed)["status"] == oa.INVALID
    path.unlink()
    assert oa.verify_signoff(signed)["status"] == oa.ABSENT


def test_signoff_is_write_once(signed: Path) -> None:
    path = signed / oa.REL["signoff"]
    assert tv.write_once(path, oa.build_signoff(signed)) == (path, False)
    put_json(
        signed,
        oa.SIGNOFF_EVIDENCE["quality_report"],
        {"SRC-A": {"pages": 1, "extraction_failures": 0, "ocr": {"statuses": {}}, "findings": []}},
    )
    with pytest.raises(RuntimeError, match="immutable"):
        tv.write_once(path, oa.build_signoff(signed))


# --- the real private records (skipped in a public checkout) -------------------------------

REAL = oa.PROJECT_ROOT
needs_private = pytest.mark.skipif(
    not ((REAL / oa.REL["d053"]).exists() and (REAL / oa.REL["signoff"]).exists()),
    reason="private owner attestations (gitignored) are not present in this checkout",
)


@needs_private
def test_real_attestations_verify_and_preserve_original_evidence() -> None:
    assert oa.verify_d053()["status"] == oa.VALID
    assert oa.verify_signoff()["status"] == oa.VALID
    rows = list(csv.DictReader((REAL / oa.REL["review_csv"]).open(encoding="utf-8", newline="")))
    assert len(rows) == 22 and all(r["human_reviewed"] == "false" for r in rows)
    d053 = json.loads((REAL / oa.REL["d053"]).read_text("utf-8"))
    assert d053["page_count"] == 22 and d053["individual_findings_status"] == "not_recorded"
    signoff = json.loads((REAL / oa.REL["signoff"]).read_text("utf-8"))
    assert signoff["decision"] == "approved" and signoff["signed_off_on"] == "2026-10-31"
    assert (
        signoff["scope"]["pages_processed"] == 222
        and len(signoff["scope"]["pilot_documents"]) == 10
    )
