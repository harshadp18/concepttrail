"""End-to-end teammate CSV pipeline on synthetic fixtures (and, opt-in, the real inventory).

Run: python -m pytest -q tests/integration/test_teammate_csv_pipeline.py
     python -m pytest -q -m real_inventory tests/integration   # real files, outputs in tmp
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from data_pipeline.clean_teammate_csv import PROJECT_ROOT, main
from data_pipeline.inventory_schema import CANONICAL_HEADER

REAL_CSV = PROJECT_ROOT / "resources/teammate_csv/incoming/curriculum_inventory.csv"
REAL_PDF_ROOT = PROJECT_ROOT / "resources/textbook_pdfs"
REAL_MASTER = PROJECT_ROOT / "data_pipeline/curriculum.csv"
REAL_CONFIG = PROJECT_ROOT / "data_pipeline/config.yaml"


class Env:
    def __init__(self, inventory: Any, tmp_path: Path) -> None:
        self.inventory = inventory
        self.out = tmp_path / "out"
        self.raw = tmp_path / "raw"
        self.config = tmp_path / "config.yaml"
        self.master = tmp_path / "curriculum.csv"
        shutil.copy(REAL_CONFIG, self.config)
        shutil.copy(REAL_MASTER, self.master)

    def run(self, *extra: str, input_dir: Path | None = None) -> int:
        return main(
            [
                "--input-dir",
                str(input_dir or self.inventory.root / "incoming"),
                "--pdf-root",
                str(self.inventory.pdf_root),
                "--output-root",
                str(self.out),
                "--snapshot-root",
                str(self.raw),
                "--master",
                str(self.master),
                "--config",
                str(self.config),
                *extra,
            ]
        )

    def path(self, kind: str, stem: str = "inventory") -> Path:
        locations = {
            "cleaned": f"processed/cleaned/{stem}.cleaned.csv",
            "rejected": f"processed/rejected/{stem}.rejected.csv",
            "quarantined": f"processed/rejected/{stem}.quarantined.csv",
            "manifest": f"processed/manifests/{stem}.manifest.json",
            "decisions": f"processed/manifests/{stem}.decisions.jsonl",
            "reconciliation": f"processed/manifests/{stem}.reconciliation.csv",
            "profile": f"processed/reports/{stem}.profile.json",
            "coverage": f"processed/reports/{stem}.coverage.csv",
            "reviewer_notes": f"processed/reports/{stem}.reviewer_notes.csv",
            "field_mapping": f"mappings/{stem}.field_mapping.json",
            "merge": f"mappings/{stem}.merge_proposal.json",
        }
        return self.out / locations[kind]

    def rows(self, kind: str, stem: str = "inventory") -> list[dict[str, str]]:
        with self.path(kind, stem).open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    def manifest(self, stem: str = "inventory") -> dict[str, Any]:
        return json.loads(self.path("manifest", stem).read_text(encoding="utf-8"))

    def output_hashes(self) -> dict[str, str]:
        return {
            p.relative_to(self.out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(self.out.rglob("*"))
            if p.is_file()
        }


@pytest.fixture
def env(inventory, tmp_path: Path) -> Env:
    return Env(inventory, tmp_path)


@pytest.fixture
def fixture_csv(inventory) -> Path:
    """8 rows: 3 accepted, 3 rejected, 2 quarantined (rows numbered from 1)."""
    good = inventory.row(1)
    rows: list[Any] = [
        good,  # 1 accepted (Hindi + maths symbols)
        inventory.row(2, chapter_title="  Fractions  "),  # 2 accepted, whitespace trimmed
        dict(good),  # 3 quarantined: exact duplicate of row 1
        inventory.row(4, chapter_title="Shapes [Note: file named oddly]"),  # 4 quarantined
        inventory.row(5, sha256="e" * 64),  # 5 rejected: hash mismatch
        inventory.row(6, notes="Source: no locator"),  # 6 rejected: no local_path
        ["CT-C06-MAT-007", "6", "CBSE"],  # 7 rejected: malformed width
        inventory.row(8),  # 8 accepted
    ]
    return inventory.write_csv("inventory.csv", rows)


def test_full_run_reconciles_and_classifies_every_row(env: Env, fixture_csv: Path, capsys) -> None:
    original = fixture_csv.read_bytes()
    master_before = env.master.read_bytes()

    assert env.run() == 0
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert summary["equation"] == "8 input = 3 accepted + 3 rejected + 2 quarantined"
    assert summary["balanced"] is True

    cleaned = env.rows("cleaned")
    assert tuple(cleaned[0]) == CANONICAL_HEADER
    assert [r["inventory_id"] for r in cleaned] == [
        "CT-C06-MAT-001",
        "CT-C06-MAT-002",
        "CT-C06-MAT-008",
    ]
    assert cleaned[0]["chapter_title"] == "Patterns √2 × π ≤ ∞ — अध्याय 1"
    assert cleaned[0]["resource_title"] == "गणित Ganita: Textbook for Grade 6"
    assert cleaned[1]["chapter_title"] == "Fractions"
    raw_cleaned = env.path("cleaned").read_bytes()
    assert not raw_cleaned.startswith(b"\xef\xbb\xbf") and b"\r\n" not in raw_cleaned

    quarantined = {r["__source_row"]: r for r in env.rows("quarantined")}
    assert set(quarantined) == {"3", "4"}
    assert quarantined["3"]["__reason_codes"] == "EXACT_DUPLICATE_EXTRA_COPY"
    assert quarantined["3"]["__related_rows"] == "1"
    assert quarantined["4"]["__reason_codes"] == "REVIEWER_NOTE_IN_FACTUAL_FIELD"
    assert quarantined["4"]["chapter_title"] == "Shapes [Note: file named oddly]"  # preserved
    assert quarantined["4"]["__source_line"] == "5"

    rejected = {r["__source_row"]: r for r in env.rows("rejected")}
    assert {k: v["__reason_codes"] for k, v in rejected.items()} == {
        "5": "SHA256_MISMATCH",
        "6": "PDF_PATH_MISSING",
        "7": "ROW_WIDTH_MISMATCH",
    }
    assert json.loads(rejected["7"]["__raw_record_json"]) == ["CT-C06-MAT-007", "6", "CBSE"]
    assert all(r["__suggested_actions"] for r in rejected.values())

    ledger = env.rows("reconciliation")
    assert [r["data_row"] for r in ledger] == [str(n) for n in range(1, 9)]
    assert {r["disposition"] for r in ledger} == {"accepted", "rejected", "quarantined"}

    notes = env.rows("reviewer_notes")
    assert [(n["inventory_id"], n["annotation"], n["applied"]) for n in notes] == [
        ("CT-C06-MAT-004", "[Note: file named oddly]", "false")
    ]
    decisions = [json.loads(line) for line in env.path("decisions").read_text().splitlines()]
    assert [t["rule"] for t in decisions[1]["transforms"]] == ["TRIM_OUTER_WHITESPACE"]
    assert len(env.rows("coverage")) == 25

    # originals and master untouched; snapshot byte-identical and read-only
    assert fixture_csv.read_bytes() == original
    assert env.master.read_bytes() == master_before
    manifest = env.manifest()
    assert manifest["input"]["unchanged"] and manifest["master_inventory"]["unchanged"]
    snapshot = PROJECT_ROOT / manifest["snapshot"]["path"]
    if not snapshot.exists():
        snapshot = Path(manifest["snapshot"]["path"])
    assert snapshot.read_bytes() == original
    assert not snapshot.stat().st_mode & 0o222
    for path, digest in manifest["outputs"].items():
        target = PROJECT_ROOT / path if (PROJECT_ROOT / path).exists() else Path(path)
        assert hashlib.sha256(target.read_bytes()).hexdigest() == digest
    merge = json.loads(env.path("merge").read_text())
    assert merge["applied"] is False and merge["proposed_additions"]["rows"] == 3
    assert merge["rights"]["original_permission_fields_modified"] is False


def test_second_run_is_idempotent(env: Env, fixture_csv: Path) -> None:
    assert env.run() == 0
    first, first_manifest = env.output_hashes(), env.manifest()
    assert env.run() == 0
    second, second_manifest = env.output_hashes(), env.manifest()

    manifest_key = "processed/manifests/inventory.manifest.json"
    assert {k: v for k, v in first.items() if k != manifest_key} == {
        k: v for k, v in second.items() if k != manifest_key
    }
    for volatile in (first_manifest, second_manifest):
        volatile.pop("generated_at_utc")
        volatile["snapshot"].pop("reused_existing")
    assert first_manifest == second_manifest


def test_changed_input_requires_force(env: Env, inventory, fixture_csv: Path) -> None:
    assert env.run() == 0
    old_run = env.manifest()["run_id"]
    inventory.write_csv("inventory.csv", [inventory.row(1)])
    assert env.run() == 4  # refuses to replace outputs of a different input
    assert env.manifest()["run_id"] == old_run
    assert env.run("--force") == 0
    assert env.manifest()["run_id"] != old_run
    assert env.manifest()["reconciliation"]["input_rows"] == 1


def test_dry_run_writes_nothing(env: Env, fixture_csv: Path) -> None:
    assert env.run("--dry-run") == 0
    assert not env.out.exists() and not env.raw.exists()


def test_profile_only_writes_snapshot_and_profile(env: Env, fixture_csv: Path) -> None:
    assert env.run("--profile-only") == 0
    assert [p.name for p in env.out.rglob("*") if p.is_file()] == ["inventory.profile.json"]
    profile = json.loads(env.path("profile").read_text())
    assert profile["data_rows"] == 8 and profile["utf8_bom"] is True
    assert any(env.raw.rglob("inventory.csv"))


def test_non_canonical_header_requires_mapping(env: Env, inventory) -> None:
    header = (*CANONICAL_HEADER, "teammate_comment")
    row = inventory.row(1)
    inventory.write_csv("inventory.csv", [[*(row[c] for c in CANONICAL_HEADER), "hi"]], header)
    assert env.run() == 3
    quarantined = env.rows("quarantined")
    assert [r["__reason_codes"] for r in quarantined] == ["SCHEMA_MAPPING_REQUIRED"]
    assert json.loads(quarantined[0]["__raw_record_json"])[-1] == "hi"  # nothing discarded
    mapping = json.loads(env.path("field_mapping").read_text())
    assert mapping["unmapped_source_columns"][0]["source_column"] == "teammate_comment"
    assert mapping["approved"] is False
    assert env.rows("cleaned") == []


def test_unreadable_csv_is_fatal(env: Env, inventory) -> None:
    path = inventory.root / "incoming" / "broken.csv"
    path.parent.mkdir(parents=True)
    path.write_bytes(",".join(CANONICAL_HEADER).encode() + b'\n"unclosed,quote\n')
    assert env.run() == 2
    assert not env.out.exists()


def test_unsafe_config_is_refused(env: Env, fixture_csv: Path) -> None:
    text = env.config.read_text().replace(
        "auto_correct_factual_values: false", "auto_correct_factual_values: true"
    )
    env.config.write_text(text)
    assert env.run() == 6
    assert not env.out.exists()


def test_missing_input_is_reported(env: Env, tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert env.run(input_dir=empty) == 7


@pytest.mark.real_inventory
def test_real_inventory_reconciles_without_touching_originals(tmp_path: Path) -> None:
    if not REAL_CSV.exists() or not REAL_PDF_ROOT.exists():
        pytest.skip("real teammate inventory or PDF drop-zone not present")
    csv_before = hashlib.sha256(REAL_CSV.read_bytes()).hexdigest()
    master_before = hashlib.sha256(REAL_MASTER.read_bytes()).hexdigest()
    out, raw = tmp_path / "out", tmp_path / "raw"
    code = main(["--file", str(REAL_CSV), "--output-root", str(out), "--snapshot-root", str(raw)])
    assert code == 0
    manifest = json.loads(
        (out / "processed/manifests/curriculum_inventory.manifest.json").read_text()
    )
    rec = manifest["reconciliation"]
    assert rec["input_rows"] == 386 and rec["balanced"]
    assert rec["input_rows"] == rec["accepted"] + rec["rejected"] + rec["quarantined"]
    quality = json.loads((out / "processed/reports/curriculum_inventory.quality.json").read_text())
    assert quality["pdf_integrity"]["sha256_match"] == 386
    assert len(quality["coverage"]) == 25
    assert all(e["rows"] > 0 for e in quality["coverage"])
    assert hashlib.sha256(REAL_CSV.read_bytes()).hexdigest() == csv_before
    assert hashlib.sha256(REAL_MASTER.read_bytes()).hexdigest() == master_before
