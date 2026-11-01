"""Authorisation record templates are generic; historical wording is private and still verifies."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from data_pipeline import authorization as auth
from data_pipeline import owner_attestations as oa

ROOT = Path(__file__).resolve().parents[1].parent
RECORDS = [auth.OWNER_LOCAL_RECORD_ID, auth.OWNER_PROJECT_RECORD_ID]
D050_SHA256 = "f13e8b696f881e3a055a1f2735f7b628ce5b4f3a36bb40b5b9dabad6adf338f9"
D034_SHA256 = "2c493a32308001b0a169635e0f7a4b73da2d1093c1a2c8b7f750e0d179119921"
needs_private = pytest.mark.skipif(
    not all((auth.AUTHORIZATION_DIR / f"{r}.json").exists() for r in RECORDS),
    reason="private authorisation records (gitignored) are not present in this checkout",
)
DOCS = [{"source_id": "SRC-X", "sha256": "a" * 64}]


def private_wording(record_id: str) -> dict[str, str]:
    record = json.loads((auth.AUTHORIZATION_DIR / f"{record_id}.json").read_text("utf-8"))
    keys = ("statement", "evidence_reference_status", "review_status", "decision_reference")
    return {k: record[k] for k in keys if k in record}


def test_new_records_use_only_generic_wording() -> None:
    for build in (auth.owner_local_processing_record, auth.owner_project_use_record):
        record = build(DOCS)
        for key, value in auth.GENERIC_WORDING.items():
            assert record[key] == value
        assert "decision_reference" not in record
        assert record["authorization_basis"] == "owner_attestation"
        assert "not independent legal verification" in record["nature"]
        assert record["uses"] and record["documents"] == DOCS


def test_wording_overrides_are_validated() -> None:
    assert auth.resolve_wording(None) == auth.GENERIC_WORDING
    assert auth.resolve_wording({"statement": "x"})["review_status"] == "owner_attested"
    for bad in ({"unknown": "x"}, {"statement": ""}, {"statement": 3}, {"scope": "everything"}):
        with pytest.raises(ValueError):
            auth.resolve_wording(bad)  # type: ignore[arg-type]


def test_wording_does_not_change_what_the_gate_grants() -> None:
    plain = auth.owner_project_use_record(DOCS)
    custom = auth.owner_project_use_record(DOCS, {"statement": "Different words."})
    for use in auth.LOCAL_USES + auth.PROJECT_USES + tuple(auth.SEPARATE_AUTHORIZATION_ONLY):
        a = auth.check_use("SRC-X", "a" * 64, use, [plain]).permitted
        assert a == auth.check_use("SRC-X", "a" * 64, use, [custom]).permitted
    assert (
        plain["uses"] == custom["uses"] and plain["documents_sha256"] == custom["documents_sha256"]
    )


def test_incomplete_or_tampered_evidence_still_fails_closed() -> None:
    record = auth.owner_project_use_record(DOCS)
    assert auth.check_use("SRC-X", "b" * 64, "indexing_retrieval", [record]).permitted is False
    assert (
        auth.check_use(
            "SRC-X", "a" * 64, "indexing_retrieval", [{**record, "documents": []}]
        ).permitted
        is False
    )
    assert auth.check_use("SRC-X", "a" * 64, "indexing_retrieval", []).permitted is False
    for use in auth.SEPARATE_AUTHORIZATION_ONLY:
        forged = {**record, "uses": {**record["uses"], use: "permitted"}}
        assert not auth.check_use("SRC-X", "a" * 64, use, [forged]).permitted


def test_generic_template_cannot_overwrite_a_written_record(tmp_path: Path) -> None:
    path = auth.write_record(
        auth.owner_project_use_record(DOCS, {"statement": "Old words."}), tmp_path
    )
    with pytest.raises(RuntimeError, match="immutable"):
        auth.write_record(auth.owner_project_use_record(DOCS), tmp_path)
    assert (
        auth.write_record(
            auth.owner_project_use_record(DOCS, {"statement": "Old words."}), tmp_path
        )
        == path
    )


@needs_private
def test_historical_records_regenerate_byte_identically_from_private_wording() -> None:
    rows = list(csv.DictReader(auth.CLEANED_INVENTORY.open(encoding="utf-8", newline="")))
    builders = {
        auth.OWNER_LOCAL_RECORD_ID: auth.owner_local_processing_record,
        auth.OWNER_PROJECT_RECORD_ID: auth.owner_project_use_record,
    }
    for record_id, build in builders.items():
        actual = (auth.AUTHORIZATION_DIR / f"{record_id}.json").read_text("utf-8")
        rebuilt = (
            json.dumps(build(rows, private_wording(record_id)), ensure_ascii=False, indent=2) + "\n"
        )
        assert rebuilt == actual, record_id
        generic = json.dumps(build(rows), ensure_ascii=False, indent=2) + "\n"
        assert generic != actual  # re-recording with generic wording would be refused


@needs_private
def test_historical_evidence_bytes_and_attestations_are_unchanged() -> None:
    def sha(record_id: str) -> str:
        return hashlib.sha256(
            (auth.AUTHORIZATION_DIR / f"{record_id}.json").read_bytes()
        ).hexdigest()

    assert sha(auth.OWNER_PROJECT_RECORD_ID) == D050_SHA256
    assert sha(auth.OWNER_LOCAL_RECORD_ID) == D034_SHA256
    if (ROOT / oa.REL["d053"]).exists():
        assert oa.verify_d053()["status"] == oa.VALID
        assert oa.verify_signoff()["status"] == oa.VALID


@needs_private
def test_private_wording_is_absent_from_every_published_source_file() -> None:
    secrets = [
        v
        for r in RECORDS
        for k, v in private_wording(r).items()
        if k in ("statement", "evidence_reference_status") and len(v) > 20
    ]
    assert secrets
    suffixes = {".py", ".md", ".json", ".toml", ".example", ".yaml"}
    skip = {".git", ".venv", "data", "reports", "__pycache__", ".ruff_cache", ".pytest_cache"}
    leaks = []
    for path in ROOT.rglob("*"):
        if (
            not path.is_file()
            or path.suffix not in suffixes
            or skip & set(path.relative_to(ROOT).parts)
        ):
            continue
        if path.name in {"DECISIONS.md", "SOURCE_AUDIT.md"} or "overrides" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        leaks += [path.name for s in secrets if s in text]
    assert not leaks, leaks
