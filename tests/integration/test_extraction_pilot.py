"""End-to-end extraction pilot on synthetic PDFs, with every path redirected to tmp."""

from __future__ import annotations

import csv
import functools
import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from conftest import SYNTHETIC_PROSE, UNICODE_FONT

from data_pipeline import authorization as auth
from data_pipeline import run_extraction_pilot as pilot
from data_pipeline.inventory_schema import CANONICAL_HEADER
from data_pipeline.stages import ocr_pages

pytestmark = pytest.mark.skipif(not UNICODE_FONT.exists(), reason="needs a Unicode font")

ENRICHMENT_FILES = {
    "topic_mapping.csv",
    "learning_objective_mapping.csv",
    "source_url_mapping.csv",
    "acquisition_date_evidence.json",
    "unified_enrichment.json",
    "unified_enrichment.csv",
    "missing_value_report.json",
    "missing_value_report.md",
    "human_review_queue.csv",
    "provenance_manifest.json",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def env(tmp_path: Path, pdfs, inventory, monkeypatch: pytest.MonkeyPatch):
    pdf_root = inventory.pdf_root
    specs = {
        "class 6/maths/m01.pdf": (
            "mathematics",
            "MAT",
            "Patterns in Numbers",
            [
                {"heading": "Patterns in Numbers", "lines": [SYNTHETIC_PROSE]},
                {
                    "lines": [
                        "1.1 Counting Shapes",
                        SYNTHETIC_PROSE,
                        "x + y = 7",
                        "1.2 Number Lines",
                        SYNTHETIC_PROSE,
                    ]
                },
            ],
        ),
        "class 7/hindi/h01.pdf": (
            "hindi",
            "HIN",
            "हमारा पाठ",
            [{"heading": "हमारा पाठ", "lines": ["बच्चों ने किताब पढ़ी। ज्ञान और श्रम का महत्व।"] * 4}],
        ),
        "class 8/science/s01.pdf": ("science", "SCI", "Scanned Chapter", None),
        "class 9/english/e01.pdf": (
            "english",
            "ENG",
            "Quarantined Story",
            [{"lines": [SYNTHETIC_PROSE]}],
        ),
    }
    rows, selected = [], []
    for n, (rel_path, (subject, code, title, pages)) in enumerate(specs.items(), 1):
        target = pdf_root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        built = pdfs.scanned(f"s{n}.pdf") if pages is None else pdfs.build(f"b{n}.pdf", pages)
        target.write_bytes(built.read_bytes())
        cls = rel_path.split("/")[0].split()[1]
        row = inventory.row(
            n,
            local_path=rel_path,
            subject_id=subject,
            class_level=cls,
            chapter_title=title,
            inventory_id=f"CT-C{int(cls):02d}-{code}-{n:03d}",
            source_id=f"SRC-C{int(cls):02d}-{code}-BOOK1-{n:02d}",
        )
        rows.append(row)
        selected.append(
            {
                "status": "selected",
                "slot": f"slot{n}",
                **{k: row[k] for k in ("source_id", "inventory_id", "sha256")},
                "local_path": rel_path,
            }
        )
    accepted, quarantined = rows[:3], rows[3:]

    def write_csv(path: Path, items: list[dict]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=list(CANONICAL_HEADER), extrasaction="ignore"
            )
            writer.writeheader()
            writer.writerows(items)
        return path

    cleaned = write_csv(tmp_path / "cleaned.csv", accepted)
    quarantine = write_csv(tmp_path / "quarantined.csv", quarantined)
    manifest = tmp_path / "phase3_manifest.json"
    manifest.write_text(
        json.dumps({"run_id": "test-run", "outputs": {pilot.rel(cleaned): sha(cleaned)}})
    )
    selection = tmp_path / "selection.json"
    selection.write_text(json.dumps({"selected": selected}))
    config = tmp_path / "config.yaml"
    config.write_text("ocr:\n  enabled: false\n  dpi: 72\n")
    record = auth.owner_local_processing_record(accepted)
    data = tmp_path / "data"
    for name, value in {
        "PDF_ROOT": pdf_root,
        "CLEANED": cleaned,
        "QUARANTINED": quarantine,
        "PHASE3_MANIFEST": manifest,
        "CONFIG": config,
        "SELECTION": selection,
        "RAW_DIR": data / "raw_json",
        "NORMALIZED_DIR": data / "normalized",
        "ENRICH_DIR": data / "enrichment",
        "LOG_DIR": data / "logs",
        "URL_EVIDENCE": data / "enrichment/source_url_evidence.json",
        "OFFICIAL_OUTCOMES": data / "official.json",
        "AI_OBJECTIVES": data / "ai_objectives.json",
        "DATA": data,
    }.items():
        monkeypatch.setattr(pilot, name, value)
    monkeypatch.setattr(pilot, "load_records", lambda: [record])
    monkeypatch.setattr(
        pilot.ocr_pages,
        "detect_tesseract",
        lambda: ocr_pages.OcrAvailability(None, None, error="absent"),
    )
    return {"data": data, "pdf_root": pdf_root, "rows": rows, "config": config}


def outputs(data: Path) -> dict[str, str]:
    return {p.relative_to(data).as_posix(): sha(p) for p in sorted(data.rglob("*")) if p.is_file()}


def test_pilot_end_to_end(env, capsys) -> None:
    pdf_hashes = {p: sha(p) for p in env["pdf_root"].rglob("*.pdf")}
    assert pilot.main() == 1  # the quarantined row is refused, so not every selection ran
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert summary == {"documents": 4, "processed": 3, "pages": 4}

    data = env["data"]
    run = json.loads((data / "logs/run_manifest.json").read_text())
    statuses = {d["source_id"]: d["status"] for d in run["documents"]}
    assert list(statuses.values()) == ["processed", "processed", "processed", "refused"]
    assert run["database_writes"] == "none" and run["external_ai_calls"] == "none"

    raw_files = sorted((data / "raw_json").glob("*.raw.json"))
    assert len(raw_files) == 3
    raw = json.loads(raw_files[0].read_text())
    page = raw["pages"][0]
    for key in (
        "source_id",
        "pdf_path",
        "pdf_sha256",
        "page_index",
        "page_label",
        "text",
        "text_length",
        "extraction_method",
        "classification",
        "images",
        "tables",
        "extracted_at",
        "pipeline_version",
        "review_status",
    ):
        assert key in page

    norm_files = sorted((data / "normalized").glob("*.normalized.json"))
    norm = json.loads(norm_files[0].read_text())
    assert norm["raw_artifact"] == pilot.rel(raw_files[0])
    assert (
        norm["pages"][0]["raw_ref"]["raw_text_sha256"]
        == hashlib.sha256(raw["pages"][0]["text"].encode()).hexdigest()
    )

    assert {p.name for p in (data / "enrichment").iterdir()} >= ENRICHMENT_FILES
    unified = {
        u["source_document_id"]: u
        for u in json.loads((data / "enrichment/unified_enrichment.json").read_text())
    }
    maths, hindi, scanned = (unified[r["source_id"]] for r in env["rows"][:3])
    assert maths["topic_value_status"] == "requires_human_review" and maths["topic_count"] == 2
    assert maths["objective_value_status"] == "source_derived_candidate"
    assert maths["learning_objective"] is None  # candidates are never written as values
    assert hindi["chapter_title_check"] == "consistent"
    assert all(
        u["acquired_at"] is None and u["acquisition_date_status"] == "unknown"
        for u in unified.values()
    )
    assert all(u["url_value_status"] == "unknown" for u in unified.values())  # verifier not run

    queue = list(
        csv.DictReader((data / "enrichment/human_review_queue.csv").open(encoding="utf-8"))
    )
    scanned_id = env["rows"][2]["source_id"]
    assert any(q["item"] == "ocr_required" and q["source_document_id"] == scanned_id for q in queue)
    scanned_raw = json.loads(next(f for f in raw_files if scanned_id in f.name).read_text())
    assert scanned_raw["pages"][0]["classification"]["class"] == "scanned"
    assert scanned_raw["pages"][0]["ocr"]["status"] == "disabled"

    assert not list((data / "enrichment").glob("proposed_enriched_inventory*"))
    assert {p: sha(p) for p in env["pdf_root"].rglob("*.pdf")} == pdf_hashes  # originals untouched


def test_rerun_is_idempotent(env) -> None:
    run_logs = {"logs/events.jsonl", "logs/run_manifest.json"}
    pilot.main()
    first = outputs(env["data"])
    first_manifest = json.loads((env["data"] / "logs/run_manifest.json").read_text())
    pilot.main()
    second = outputs(env["data"])
    second_manifest = json.loads((env["data"] / "logs/run_manifest.json").read_text())

    # Raw, normalised, enrichment and quality artifacts are byte-identical.
    assert {k: v for k, v in first.items() if k not in run_logs} == {
        k: v for k, v in second.items() if k not in run_logs
    }
    # Run logs differ only in recording that the second run reused existing artifacts.
    for manifest in (first_manifest, second_manifest):
        for doc in manifest["documents"]:
            doc.pop("raw_reused", None)
            doc.pop("normalized_reused", None)
    assert first_manifest == second_manifest
    events = [json.loads(e) for e in (env["data"] / "logs/events.jsonl").read_text().splitlines()]
    assert all(
        e["raw_reused"] and e["normalized_reused"] for e in events if e["status"] == "processed"
    )


def test_mocked_local_ocr_is_stored_separately(env, monkeypatch: pytest.MonkeyPatch) -> None:
    env["config"].write_text('ocr:\n  enabled: true\n  dpi: 72\n  languages: ["eng", "hin"]\n')
    tsv = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        + "\n".join(
            f"5\t1\t1\t1\t1\t{i}\t0\t0\t9\t9\t{c}\t{w}"
            for i, (w, c) in enumerate(
                [("Scanned", 91), ("heading", 89), ("with", 90), ("five", 90), ("words", 90)], 1
            )
        )
    )

    def run(cmd):
        return subprocess.CompletedProcess(cmd, 0, stdout=tsv, stderr="")

    monkeypatch.setattr(
        pilot.ocr_pages,
        "detect_tesseract",
        lambda: ocr_pages.OcrAvailability("/t", "tesseract 5.4", ["eng"]),
    )
    monkeypatch.setattr(pilot.ocr_pages, "ocr_page", functools.partial(ocr_pages.ocr_page, run=run))
    pilot.main()
    scanned_id = env["rows"][2]["source_id"]
    raw_path = next((env["data"] / "raw_json").glob(f"{scanned_id}*.raw.json"))
    page = json.loads(raw_path.read_text())["pages"][0]
    assert page["ocr"]["status"] == "completed"
    assert page["ocr"]["text"] == "Scanned heading with five words"
    assert page["ocr"]["languages"] == "eng" and page["ocr"]["mean_confidence"] == 90.0
    assert page["text"].strip() == ""  # native text is never replaced by OCR
    queue = list(
        csv.DictReader((env["data"] / "enrichment/human_review_queue.csv").open(encoding="utf-8"))
    )
    items = {q["item"] for q in queue if q["source_document_id"] == scanned_id}
    assert "ocr_quality_review" in items and "ocr_required" not in items


def test_weak_ocr_is_queued_as_weak_not_as_not_run(env, monkeypatch: pytest.MonkeyPatch) -> None:
    env["config"].write_text('ocr:\n  enabled: true\n  dpi: 72\n  languages: ["eng", "hin"]\n')
    tsv = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight"
        "\tconf\ttext\n5\t1\t1\t1\t1\t1\t0\t0\t9\t9\t40\tFig."
    )
    monkeypatch.setattr(
        pilot.ocr_pages,
        "detect_tesseract",
        lambda: ocr_pages.OcrAvailability("/t", "tesseract 5.4", ["eng"]),
    )
    monkeypatch.setattr(
        pilot.ocr_pages,
        "ocr_page",
        functools.partial(
            ocr_pages.ocr_page,
            run=lambda cmd: subprocess.CompletedProcess(cmd, 0, stdout=tsv, stderr=""),
        ),
    )
    pilot.main()
    scanned_id = env["rows"][2]["source_id"]
    queue = list(
        csv.DictReader((env["data"] / "enrichment/human_review_queue.csv").open(encoding="utf-8"))
    )
    items = {q["item"]: q for q in queue if q["source_document_id"] == scanned_id}
    assert "ocr_required" not in items
    assert "minimal_text" in items["ocr_low_confidence_or_empty"]["reason"]


def test_unapproved_ocr_language_is_refused(env, monkeypatch: pytest.MonkeyPatch) -> None:
    env["config"].write_text('ocr:\n  enabled: true\n  dpi: 72\n  languages: ["hin"]\n')
    monkeypatch.setattr(
        pilot.ocr_pages,
        "detect_tesseract",
        lambda: ocr_pages.OcrAvailability("/t", "tesseract 5.5", ["eng", "hin"]),
    )
    pilot.main()
    scanned_id = env["rows"][2]["source_id"]
    raw_path = next((env["data"] / "raw_json").glob(f"{scanned_id}*.raw.json"))
    ocr = json.loads(raw_path.read_text())["pages"][0]["ocr"]
    assert ocr["status"] == "language_unavailable" and "not approved" in ocr["reason"]


def test_devanagari_repair_runs_only_for_configured_sources(env) -> None:
    hindi_id = env["rows"][1]["source_id"]
    env["config"].write_text(
        f'ocr:\n  enabled: false\n  dpi: 72\ndevanagari_repair:\n  rule: "D-044"\n'
        f'  source_ids: ["{hindi_id}"]\n'
    )
    pilot.main()
    data = env["data"]
    raws = {p.name.split("__")[0]: sha(p) for p in (data / "raw_json").glob("*.raw.json")}
    run = json.loads((data / "logs/run_manifest.json").read_text())
    repaired = {d["source_id"]: d.get("devanagari_repair") for d in run["documents"]}
    assert repaired[hindi_id]["rule"] == "D-044"
    assert all(v is None for k, v in repaired.items() if k != hindi_id)
    norm = json.loads(next((data / "normalized").glob(f"{hindi_id}*.normalized.json")).read_text())
    log_path = next((data / "normalized").glob(f"{hindi_id}*.repairs.json"))
    assert sha(log_path) == norm["devanagari_repair"]["log_sha256"]
    assert json.loads(log_path.read_text())["unaligned_blocks_total"] == 0
    assert all(p["devanagari_repair"]["rule"] == "D-044" for p in norm["pages"])
    pilot.main()  # rerun: raw artifacts reused byte-identically, no new generations
    assert {p.name.split("__")[0]: sha(p) for p in (data / "raw_json").glob("*.raw.json")} == raws
    assert len(list((data / "normalized").glob(f"{hindi_id}*.repairs.json"))) == 1
