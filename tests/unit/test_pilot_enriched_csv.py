"""Derived pilot CSV: canonical columns, write rules, rights overlay, hashes, idempotency."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from data_pipeline import authorization as auth
from data_pipeline import build_pilot_enriched_csv as builder
from data_pipeline.clean_teammate_csv import csv_bytes
from data_pipeline.inventory_schema import CANONICAL_HEADER


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory_row(inventory_id: str, source_id: str, digest: str, **values: str) -> dict:
    row = dict.fromkeys(CANONICAL_HEADER, "")
    row.update(
        inventory_id=inventory_id,
        source_id=source_id,
        sha256=digest,
        rights_status="review_required",
        permitted_processing="permission_required",
        permitted_indexing="permission_required",
        permitted_training="not_permitted",
        permitted_display="permission_required",
        permission_reference="https://example.org/terms",
    )
    row.update(values)
    return row


def enrichment(source_id: str, inventory_id: str, **overrides) -> dict:
    record = {
        "source_document_id": source_id,
        "inventory_id": inventory_id,
        "topic_title": None,
        "learning_objective": None,
        "source_url": None,
        "acquired_at": None,
        "topic_value_status": "requires_human_review",
        "objective_value_status": "source_derived_candidate",
        "url_value_status": "unknown",
        "acquisition_date_status": "unknown",
        "value_origin": {},
        "evidence_reference": {},
        "confidence": {},
        "review_status": {},
        "reasons": {"topic_title": "chapter-level row covers 2 topics"},
        "objective_counts_by_origin": {"source_derived_candidate": 2},
    }
    record.update(overrides)
    return record


@pytest.fixture
def setup(tmp_path: Path) -> dict:
    rows = [
        inventory_row("CT-C09-MAT-001", "SRC-C09-MAT-AAAA1-01", "a" * 64),
        inventory_row("CT-C09-SCI-001", "SRC-C09-SCI-BBBB1-01", "b" * 64, source_url="https://x/b"),
        inventory_row("CT-C09-ENG-001", "SRC-C09-ENG-CCCC1-01", "c" * 64),  # not in the pilot
    ]
    cleaned = tmp_path / "cleaned.csv"
    cleaned.write_bytes(
        csv_bytes(CANONICAL_HEADER, [[r[c] for c in CANONICAL_HEADER] for r in rows])
    )
    phase3 = tmp_path / "phase3_manifest.json"
    phase3.write_text(json.dumps({"run_id": "r1", "outputs": {str(cleaned): sha(cleaned)}}))

    enrich_dir = tmp_path / "enrichment"
    enrich_dir.mkdir()
    unified = [
        enrichment(
            "SRC-C09-MAT-AAAA1-01",
            "CT-C09-MAT-001",
            learning_objective="In this chapter, we will explore identities.",
            objective_value_status="source_explicit",
            source_url="https://ncert.example/a.pdf",
            url_value_status="verified",
            value_origin={"learning_objective": "textbook_explicit"},
        ),
        enrichment(
            "SRC-C09-SCI-BBBB1-01",
            "CT-C09-SCI-001",
            source_url="https://ncert.example/b.pdf",  # conflicts with the cleaned value
            url_value_status="verified",
            topic_title="1.1 Topic A | 1.2 Topic B",
            topic_value_status="source_explicit",
        ),
    ]
    (enrich_dir / "unified_enrichment.json").write_text(json.dumps(unified))
    (enrich_dir / "topic_mapping.csv").write_text(
        "source_document_id,kind,title\n"
        "SRC-C09-MAT-AAAA1-01,topic,1.1 A\nSRC-C09-MAT-AAAA1-01,heading_candidate,Big\n"
    )
    (enrich_dir / "learning_objective_mapping.csv").write_text("source_document_id\n")
    run = tmp_path / "run_manifest.json"
    run.write_text(
        json.dumps(
            {
                "versions": {"enrichment": "metadata-enrichment/test"},
                "documents": [
                    {
                        "source_id": r["source_id"],
                        "inventory_id": r["inventory_id"],
                        "status": "processed",
                        "sha256_before": r["sha256"],
                    }
                    for r in rows[:2]
                ],
                "enrichment_outputs": {
                    name: sha(enrich_dir / name)
                    for name in (
                        "unified_enrichment.json",
                        "topic_mapping.csv",
                        "learning_objective_mapping.csv",
                    )
                },
            }
        )
    )
    auth_dir = tmp_path / "auth"
    auth.write_record(auth.owner_local_processing_record(rows), auth_dir)
    out = tmp_path / "out"
    out.mkdir()
    paths = builder.Paths(cleaned, phase3, run, enrich_dir, auth_dir, out)
    return {"paths": paths, "rows": rows, "out": out, "cleaned": cleaned}


def read(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def test_rows_columns_and_ids_are_preserved(setup) -> None:
    before = sha(setup["cleaned"])
    builder.build(setup["paths"])
    header, rows = read(setup["out"] / f"{builder.OUTPUT_STEM}.csv")
    assert tuple(header) == CANONICAL_HEADER and len(header) == 29
    assert [r["inventory_id"] for r in rows] == ["CT-C09-MAT-001", "CT-C09-SCI-001"]
    assert sha(setup["cleaned"]) == before  # the input is never modified


def test_only_single_verified_or_explicit_values_are_written(setup) -> None:
    builder.build(setup["paths"])
    _, rows = read(setup["out"] / f"{builder.OUTPUT_STEM}.csv")
    maths, science = rows
    assert maths["learning_objective"] == "In this chapter, we will explore identities."
    assert maths["source_url"] == "https://ncert.example/a.pdf"
    assert maths["topic_title"] == "" and maths["acquired_at"] == ""
    assert science["source_url"] == "https://x/b"  # non-empty cleaned value never replaced
    assert science["topic_title"] == ""  # several topics stay in the sidecar
    assert science["learning_objective"] == ""  # candidates are never written

    _, status = read(setup["out"] / f"{builder.OUTPUT_STEM}.status.csv")
    by = {(s["inventory_id"], s["field"]): s for s in status}
    assert by[("CT-C09-MAT-001", "learning_objective")]["value_class"] == "source_explicit"
    assert by[("CT-C09-MAT-001", "source_url")]["value_class"] == "verified"
    candidate = by[("CT-C09-SCI-001", "learning_objective")]
    assert candidate["value_class"] == "candidate" and candidate["written"] == "false"
    assert "conflict" in by[("CT-C09-SCI-001", "source_url")]["reason"]
    assert "multiple values" in by[("CT-C09-SCI-001", "topic_title")]["reason"]
    topic = by[("CT-C09-MAT-001", "topic_title")]
    assert topic["candidate_count"] == "2" and "1 heading_candidate" in topic["candidate_reference"]


def test_rights_overlay_is_scoped_and_audited(setup) -> None:
    builder.build(setup["paths"])
    _, rows = read(setup["out"] / f"{builder.OUTPUT_STEM}.csv")
    for row in rows:
        assert row["permitted_processing"] == "permitted"
        assert row["permitted_training"] == "not_permitted"
        assert row["permitted_indexing"] == row["permitted_display"] == "permission_required"
        assert row["rights_status"] == "review_required"
    _, changes = read(setup["out"] / f"{builder.OUTPUT_STEM}.changes.csv")
    overlay = [c for c in changes if c["field"] == "permitted_processing"]
    assert len(overlay) == 2
    assert all(
        c["original_value"] == "permission_required"
        and c["authorization_record"] == auth.OWNER_LOCAL_RECORD_ID
        and len(c["authorization_record_sha256"]) == 64
        for c in overlay
    )
    # Every changed cell is recorded, and nothing else changed.
    assert {(c["inventory_id"], c["field"]) for c in changes} == {
        ("CT-C09-MAT-001", "learning_objective"),
        ("CT-C09-MAT-001", "source_url"),
        ("CT-C09-MAT-001", "permitted_processing"),
        ("CT-C09-SCI-001", "permitted_processing"),
    }


def test_manifest_hashes_verify_and_rerun_is_identical(setup) -> None:
    first = builder.build(setup["paths"], now=datetime(2026, 1, 1, tzinfo=UTC))
    for path, digest in first["content"]["outputs"].items():
        assert sha(Path(path)) == digest
    snapshot = {p.name: sha(p) for p in setup["out"].iterdir()}
    second = builder.build(setup["paths"], now=datetime(2027, 1, 1, tzinfo=UTC))
    assert {p.name: sha(p) for p in setup["out"].iterdir()} == snapshot
    assert second["generated_at"] == "2026-01-01T00:00:00+00:00"  # content unchanged
    _, rows = read(setup["out"] / f"{builder.OUTPUT_STEM}.csv")
    assert len(rows) == 2  # rewritten, never appended


def test_tampered_inputs_stop_the_build_without_writing(setup) -> None:
    paths = setup["paths"]
    with setup["cleaned"].open("a", encoding="utf-8") as handle:
        handle.write("\n")
    with pytest.raises(builder.BuildError, match="Phase 3 manifest"):
        builder.build(paths)
    assert not list(setup["out"].iterdir())


def test_changed_sidecar_or_pdf_hash_is_refused(setup) -> None:
    paths = setup["paths"]
    (paths.enrichment_dir / "topic_mapping.csv").write_text("source_document_id,kind,title\n")
    with pytest.raises(builder.BuildError, match="topic_mapping.csv"):
        builder.build(paths)

    run = json.loads(paths.run_manifest.read_text())
    run["enrichment_outputs"]["topic_mapping.csv"] = sha(paths.enrichment_dir / "topic_mapping.csv")
    run["documents"][0]["sha256_before"] = "f" * 64
    paths.run_manifest.write_text(json.dumps(run))
    with pytest.raises(builder.BuildError, match="sha256 differ"):
        builder.build(paths)


def test_value_class_distinguishes_origins() -> None:
    assert builder.value_class("verified", None) == "verified"
    assert builder.value_class("source_explicit", "textbook_explicit") == "source_explicit"
    assert builder.value_class("requires_human_review", "human_approved") == "human_approved"
    assert builder.value_class("source_derived_candidate", None) == "candidate"
    assert builder.value_class("unknown", None) == "unresolved"


def _with(setup, **changes) -> builder.Paths:
    import dataclasses

    return dataclasses.replace(setup["paths"], **changes)


def _owner(tmp: Path, **decisions) -> Path:
    path = tmp / "owner.json"
    path.write_text(json.dumps({"decisions": decisions}))
    return path


def _artifacts(setup, tmp: Path, *, failed_page: bool = False) -> None:
    """Minimal raw/normalised artifacts for the pilot rows, referenced from the run manifest."""
    run_path = setup["paths"].run_manifest
    run = json.loads(run_path.read_text())
    for doc in run["documents"]:
        text = "page text"
        page = {
            "source_id": doc["source_id"],
            "pdf_sha256": doc["sha256_before"],
            "page_index": 0,
            "extraction_method": "failed" if failed_page else "native_text",
            "extracted_at": "2026-10-31T00:00:00+00:00",
            "pipeline_version": "test",
            "text": text,
        }
        raw = {"document": {"pdf_metadata": {"page_count": 1}}, "pages": [page]}
        digest = hashlib.sha256(text.encode()).hexdigest()
        norm = {"pages": [{"raw_ref": {"raw_text_sha256": digest}}]}
        (tmp / f"{doc['source_id']}.raw.json").write_text(json.dumps(raw))
        (tmp / f"{doc['source_id']}.norm.json").write_text(json.dumps(norm))
        doc.update(
            raw_path=f"{doc['source_id']}.raw.json",
            normalized_path=f"{doc['source_id']}.norm.json",
            sha256_after=doc["sha256_before"],
        )
    run_path.write_text(json.dumps(run))


def test_project_use_overlay_updates_rights_but_never_training(setup) -> None:
    auth.write_record(
        auth.owner_project_use_record(setup["rows"]), setup["paths"].authorization_dir
    )
    builder.build(setup["paths"])
    _, rows = read(setup["out"] / f"{builder.OUTPUT_STEM}.csv")
    for row in rows:
        assert row["rights_status"] == "approved"
        assert row["permitted_processing"] == row["permitted_indexing"] == "permitted"
        assert row["permitted_display"] == "permitted"
        assert row["permitted_training"] == "not_permitted"
        assert row["permission_reference"] == "https://example.org/terms"  # history kept
    _, changes = read(setup["out"] / f"{builder.OUTPUT_STEM}.changes.csv")
    processing = [c for c in changes if c["field"] == "permitted_processing"][0]
    assert processing["authorization_record"] == (
        f"{auth.OWNER_LOCAL_RECORD_ID};{auth.OWNER_PROJECT_RECORD_ID}"
    )
    rights = [c for c in changes if c["field"] == "rights_status"][0]
    assert rights["original_value"] == "review_required"
    assert rights["authorization_record"] == auth.OWNER_PROJECT_RECORD_ID


def test_disagreeing_records_stop_the_build(setup) -> None:
    rogue = auth.owner_project_use_record(setup["rows"])
    rogue["record_id"] = "AUTH-rogue"
    rogue["inventory_field_overlay"]["permitted_display"]["overlay_value"] = "not_permitted"
    auth.write_record(rogue, setup["paths"].authorization_dir)
    auth.write_record(
        auth.owner_project_use_record(setup["rows"]), setup["paths"].authorization_dir
    )
    with pytest.raises(builder.BuildError, match="disagree"):
        builder.build(setup["paths"])


def test_extraction_status_follows_the_rule(setup, tmp_path: Path) -> None:
    _artifacts(setup, tmp_path)
    owner = _owner(tmp_path, extraction_status={"status": "approved"})
    builder.build(_with(setup, owner_decisions=owner, artifact_root=tmp_path))
    _, rows = read(setup["out"] / f"{builder.OUTPUT_STEM}.csv")
    assert {r["extraction_status"] for r in rows} == {"extracted"}
    assert {r["review_status"] for r in rows} == {""}  # review state untouched
    _, status = read(setup["out"] / f"{builder.OUTPUT_STEM}.status.csv")
    extraction = [s for s in status if s["field"] == "extraction_status"]
    assert all(s["value_class"] == "rule_derived" and s["written"] == "true" for s in extraction)

    # Without owner approval nothing is marked.
    builder.build(_with(setup, owner_decisions=None, artifact_root=tmp_path))
    _, rows = read(setup["out"] / f"{builder.OUTPUT_STEM}.csv")
    assert {r["extraction_status"] for r in rows} == {""}


def test_failed_page_blocks_extracted(setup, tmp_path: Path) -> None:
    _artifacts(setup, tmp_path, failed_page=True)
    owner = _owner(tmp_path, extraction_status={"status": "approved"})
    builder.build(_with(setup, owner_decisions=owner, artifact_root=tmp_path))
    _, rows = read(setup["out"] / f"{builder.OUTPUT_STEM}.csv")
    assert {r["extraction_status"] for r in rows} == {""}
    _, status = read(setup["out"] / f"{builder.OUTPUT_STEM}.status.csv")
    reason = [s for s in status if s["field"] == "extraction_status"][0]["reason"]
    assert "no_blocking_extraction_failures" in reason


def test_ai_generated_objectives_are_written_as_their_own_class(setup, tmp_path: Path) -> None:
    paths = setup["paths"]
    unified = json.loads((paths.enrichment_dir / "unified_enrichment.json").read_text())
    unified[1].update(
        learning_objective="Classify reactions. | Balance equations.",
        objective_value_status="ai_generated",
        value_origin={"learning_objective": "ai_generated"},
        review_status={"learning_objective": "pending_teacher_review"},
    )
    (paths.enrichment_dir / "unified_enrichment.json").write_text(json.dumps(unified))
    run = json.loads(paths.run_manifest.read_text())
    run["enrichment_outputs"]["unified_enrichment.json"] = sha(
        paths.enrichment_dir / "unified_enrichment.json"
    )
    paths.run_manifest.write_text(json.dumps(run))
    owner = _owner(tmp_path, acquired_at={"status": "accept_unknown"})
    builder.build(_with(setup, owner_decisions=owner))
    _, rows = read(setup["out"] / f"{builder.OUTPUT_STEM}.csv")
    assert rows[1]["learning_objective"] == "Classify reactions. | Balance equations."
    _, status = read(setup["out"] / f"{builder.OUTPUT_STEM}.status.csv")
    by = {(s["inventory_id"], s["field"]): s for s in status}
    objective = by[("CT-C09-SCI-001", "learning_objective")]
    assert objective["value_class"] == "ai_generated"
    assert objective["review_status"] == "pending_teacher_review"
    acquired = by[("CT-C09-SCI-001", "acquired_at")]
    assert acquired["review_status"] == "owner_accepted_unknown" and acquired["written"] == "false"
    assert "D-052" in acquired["reason"]
