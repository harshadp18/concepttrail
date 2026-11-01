"""Phase 4 extraction pilot: local extraction, selective OCR, normalisation and enrichment.

Prerequisites (each is its own command):

    python -m data_pipeline.authorization record-owner-local-processing
    python -m data_pipeline.select_pilot
    python -m data_pipeline.verify_source_urls          # optional; network only

Then:

    python -m data_pipeline.run_extraction_pilot

Outputs (all Git-ignored, none written to PostgreSQL):

    data_pipeline/data/interim/extracted_json/<source_id>__<sha12>__<key>.raw.json
    data_pipeline/data/processed/textbook_json/<source_id>__<sha12>__<key>.normalized.json
    data_pipeline/data/processed/metadata_enrichment/*   (sidecar; master never written)
    data_pipeline/data/logs/extraction_pilot/*            (manifest, events, quality report)

Raw artifacts are write-once: a changed PDF, extractor, threshold or OCR environment gives
a new cache key and a new file. Re-running unchanged inputs reproduces identical outputs.
"""

from __future__ import annotations

import collections
import csv
import datetime as dt
import hashlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pymupdf
import yaml

from data_pipeline import enrich_metadata as enrich
from data_pipeline import owner_attestations as oa
from data_pipeline import teacher_validation as tv
from data_pipeline.authorization import LOCAL_USES, check_use, load_records
from data_pipeline.stages import (
    classify_pages,
    clean_text,
    ocr_pages,
    repair_devanagari,
    structure_content,
)
from data_pipeline.stages.extract_pdf import EXTRACTOR_VERSION, ExtractionError, extract_document
from data_pipeline.stages.profile_csv import sha256_file
from data_pipeline.stages.validate_content import QUALITY_VERSION, document_quality
from data_pipeline.stages.validate_csv import check_pdf, parse_local_path

PIPELINE_VERSION = "extraction-pilot/1.0.0"
SCHEMA_VERSION = "raw-extraction/1"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA = PROJECT_ROOT / "data_pipeline/data"
PDF_ROOT = PROJECT_ROOT / "resources/textbook_pdfs"
CLEANED = PROJECT_ROOT / "resources/teammate_csv/processed/cleaned/curriculum_inventory.cleaned.csv"
QUARANTINED = (
    PROJECT_ROOT / "resources/teammate_csv/processed/rejected/curriculum_inventory.quarantined.csv"
)
PHASE3_MANIFEST = (
    PROJECT_ROOT / "resources/teammate_csv/processed/manifests/curriculum_inventory.manifest.json"
)
CONFIG = PROJECT_ROOT / "data_pipeline/config.yaml"
SELECTION = DATA / "logs/extraction_pilot/pilot_selection.json"
RAW_DIR = DATA / "interim/extracted_json"
NORMALIZED_DIR = DATA / "processed/textbook_json"
ENRICH_DIR = DATA / "processed/metadata_enrichment"
LOG_DIR = DATA / "logs/extraction_pilot"
URL_EVIDENCE = ENRICH_DIR / "source_url_evidence.json"
OFFICIAL_OUTCOMES = DATA / "overrides/metadata_enrichment/official_learning_outcomes.json"
AI_OBJECTIVES = DATA / "overrides/metadata_enrichment/ai_generated_learning_objectives.json"
TEACHER_VALIDATION = (
    DATA / "overrides/metadata_enrichment" / ("teacher_validation_attestation_2026-10-31.json")
)


class PilotError(Exception):
    pass


def rel(path: Path) -> str:
    p = path.resolve()
    return p.relative_to(PROJECT_ROOT).as_posix() if p.is_relative_to(PROJECT_ROOT) else str(p)


def digest(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    os.replace(tmp, path)


def json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n").encode()


def csv_bytes(header: list[str], rows: list[list[Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows([["" if v is None else v for v in row] for row in rows])
    return buffer.getvalue().encode("utf-8")


def now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


# --- inputs ---------------------------------------------------------------------------------


def load_inputs() -> dict[str, Any]:
    manifest = json.loads(PHASE3_MANIFEST.read_text(encoding="utf-8"))
    expected = manifest["outputs"].get(rel(CLEANED))
    if expected is None or sha256_file(CLEANED) != expected:
        raise PilotError("cleaned inventory does not match the Phase 3 manifest; re-run Phase 3")
    with CLEANED.open(encoding="utf-8", newline="") as handle:
        accepted = {r["source_id"]: r for r in csv.DictReader(handle)}
    with QUARANTINED.open(encoding="utf-8", newline="") as handle:
        quarantined = {r["source_id"] for r in csv.DictReader(handle)}
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    return {
        "accepted": accepted,
        "quarantined": quarantined,
        "phase3_run_id": manifest["run_id"],
        "cleaned_sha256": expected,
        "selection": json.loads(SELECTION.read_text(encoding="utf-8")),
        "records": load_records(),
        "ocr_enabled": bool(config.get("ocr", {}).get("enabled")),
        "ocr_dpi": int(config.get("ocr", {}).get("dpi", 300)),
        "ocr_languages": list(config.get("ocr", {}).get("languages", [])),
        # D-044 runs only on documents the owner approved by source_id.
        "devanagari_repair_scope": set(
            (config.get("devanagari_repair") or {}).get("source_ids", [])
        ),
        "config_sha256": sha256_file(CONFIG),
    }


# --- per document ---------------------------------------------------------------------------


def expected_script(row: dict[str, str]) -> str:
    return "devanagari" if row["subject_id"] == "hindi" else "latin"


def extract_raw(
    row: dict[str, str], pdf: Path, inputs: dict[str, Any], ocr_env: ocr_pages.OcrAvailability
) -> tuple[dict[str, Any], Path, bool]:
    script = expected_script(row)
    key = digest(
        [
            row["sha256"],
            EXTRACTOR_VERSION,
            classify_pages.CLASSIFIER_VERSION,
            SCHEMA_VERSION,
            script,
            [
                classify_pages.MIN_TEXT_CHARS,
                classify_pages.SCANNED_COVERAGE,
                classify_pages.IMAGE_PRESENT_COVERAGE,
                classify_pages.MIXED_COVERAGE,
            ],
            ocr_env.as_dict(),
            ocr_pages.OCR_ADAPTER_VERSION,
            inputs["ocr_enabled"],
            inputs["ocr_dpi"],
            inputs["ocr_languages"],
        ]
    )[:12]
    path = RAW_DIR / f"{row['source_id']}__{row['sha256'][:12]}__{key}.raw.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8")), path, True
    metadata, pages = extract_document(pdf)
    extracted_at = now()
    ocr_allowed = check_use(row["source_id"], row["sha256"], "local_ocr", inputs["records"])
    document = pymupdf.open(pdf)
    try:
        for page in pages:
            page["classification"] = classify_pages.classify_page(page, script)
            if not page["classification"]["ocr_candidate"]:
                page["ocr"] = {"status": "not_required"}
            elif not ocr_allowed.permitted:
                page["ocr"] = {"status": "not_authorised", "reason": ocr_allowed.reason}
            else:
                result = ocr_pages.ocr_page(
                    document[page["page_index"]],
                    script,
                    ocr_env,
                    enabled=inputs["ocr_enabled"],
                    dpi=inputs["ocr_dpi"],
                    approved_languages=inputs["ocr_languages"],
                )
                result["native_vs_ocr"] = ocr_pages.compare_native_and_ocr(
                    page["text"], result.get("text")
                )
                page["ocr"] = result
            page.update(
                source_id=row["source_id"],
                pdf_path=rel(pdf),
                pdf_sha256=row["sha256"],
                extracted_at=extracted_at,
                pipeline_version=PIPELINE_VERSION,
                review_status="needs_review"
                if page["classification"]["needs_review"]
                else "pending",
            )
    finally:
        document.close()
    raw = {
        "schema_version": SCHEMA_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "extractor_version": EXTRACTOR_VERSION,
        "cache_key": key,
        "extracted_at": extracted_at,
        "document": {
            "source_id": row["source_id"],
            "inventory_id": row["inventory_id"],
            "class_level": row["class_level"],
            "subject_id": row["subject_id"],
            "course_or_language": row["course_or_language"],
            "chapter_title": row["chapter_title"],
            "academic_session": row["academic_session"],
            "pdf_path": rel(pdf),
            "pdf_sha256": row["sha256"],
            "expected_script": script,
            "language_hint": "hi" if script == "devanagari" else "en",
            "pdf_metadata": metadata,
        },
        "ocr_environment": ocr_env.as_dict(),
        "pages": pages,
    }
    write_bytes(path, json_bytes(raw))
    return raw, path, False


def normalize(
    raw: dict[str, Any], raw_path: Path, pdf: Path | None = None, repair: bool = False
) -> tuple[dict[str, Any], Path, bool]:
    parts = [raw["cache_key"], clean_text.NORMALIZER_VERSION, structure_content.STRUCTURE_VERSION]
    if repair:
        parts += [repair_devanagari.RULE_ID, repair_devanagari.REPAIR_VERSION]
    key = digest(parts)[:12]
    doc = raw["document"]
    stem = f"{doc['source_id']}__{doc['pdf_sha256'][:12]}__{key}"
    path = NORMALIZED_DIR / f"{stem}.normalized.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8")), path, True
    view, repair_summary = raw, None
    if repair:
        # The raw artifact is untouched: corrections apply to a copy used for normalisation.
        with pymupdf.open(pdf) as opened:
            result = repair_devanagari.repair_document(raw, opened)
        view = result["view"]
        log_path = NORMALIZED_DIR / f"{stem}.repairs.json"
        log_data = json_bytes({"raw_artifact": rel(raw_path), **result["log"]})
        write_bytes(log_path, log_data)
        repair_summary = {
            "rule": repair_devanagari.RULE_ID,
            "repair_version": repair_devanagari.REPAIR_VERSION,
            "approval": "owner-approved 2026-10-31 (docs/DECISIONS.md D-044)",
            "log_artifact": rel(log_path),
            "log_sha256": hashlib.sha256(log_data).hexdigest(),
            "corrections_total": result["log"]["corrections_total"],
            "unaligned_blocks_total": result["log"]["unaligned_blocks_total"],
        }
        corrections_by_page = {
            p["pdf_page_index"]: len(p["corrections"]) for p in result["log"]["pages"]
        }
    normalized = clean_text.normalize_document(view, rel(raw_path))
    if repair_summary is not None:
        remaining = other = 0
        for page in normalized["pages"]:
            signs = repair_devanagari.repeated_signs(page["text"])
            flags = repair_devanagari.other_review_flags(page["text"])
            remaining += len(signs)
            other += len(flags)
            page["devanagari_repair"] = {
                "rule": repair_devanagari.RULE_ID,
                "corrections": corrections_by_page[page["page_index"]],
                "text_basis": "raw blocks with D-044 corrections (raw artifact unchanged)",
                "repeated_vowel_signs_for_review": signs,
                "other_repeats_for_review": flags,
            }
            if signs or flags:
                page["review_status"] = "needs_review"
        repair_summary["repeated_vowel_signs_remaining"] = remaining
        repair_summary["other_repeats_flagged"] = other
    unusable = {p["page_index"] for p in normalized["pages"] if p["text_unusable"]}
    hierarchy = structure_content.build_hierarchy(view, unusable)
    all_unusable = bool(raw["pages"]) and len(unusable) >= 0.5 * len(raw["pages"])
    payload = {
        "pipeline_version": PIPELINE_VERSION,
        "cache_key": key,
        "raw_artifact": rel(raw_path),
        "raw_cache_key": raw["cache_key"],
        "document": {k: v for k, v in doc.items() if k != "pdf_metadata"},
        "text_unusable": all_unusable,
        "hierarchy": hierarchy,
        "devanagari_repair": repair_summary,
        "chapter_title_check": (
            structure_content.chapter_title_check_ocr(
                doc["chapter_title"],
                "\n".join(
                    (p.get("ocr") or {}).get("text", "") for p in normalized["pages"][:2]
                ).strip()
                or None,
            )
            if all_unusable
            else structure_content.chapter_title_check(doc["chapter_title"], hierarchy, False)
        ),
        **normalized,
    }
    write_bytes(path, json_bytes(payload))
    return payload, path, False


def process_document(
    selected: dict[str, Any], inputs: dict[str, Any], ocr_env: ocr_pages.OcrAvailability
) -> dict[str, Any]:
    source_id = selected["source_id"]
    row = inputs["accepted"].get(source_id)
    if row is None or source_id in inputs["quarantined"]:
        return {"source_id": source_id, "status": "refused", "reason": "not an accepted record"}
    decisions = {
        use: check_use(source_id, row["sha256"], use, inputs["records"]) for use in LOCAL_USES
    }
    if not decisions["local_pdf_extraction"].permitted:
        return {
            "source_id": source_id,
            "status": "refused",
            "reason": decisions["local_pdf_extraction"].reason,
        }
    check = check_pdf(PDF_ROOT, parse_local_path(row["notes"]), row["sha256"], {})
    if not check.sha256_match or check.resolved_path is None:
        return {
            "source_id": source_id,
            "status": "refused",
            "reason": "integrity check failed",
            "issues": [i.code for i in check.issues],
        }
    pdf = PDF_ROOT / check.resolved_path
    before = sha256_file(pdf)
    try:
        raw, raw_path, raw_reused = extract_raw(row, pdf, inputs, ocr_env)
    except ExtractionError as exc:
        return {"source_id": source_id, "status": "extraction_failed", "reason": exc.code}
    normalized, norm_path, norm_reused = normalize(
        raw, raw_path, pdf, source_id in inputs["devanagari_repair_scope"]
    )
    quality = document_quality(raw, normalized, row["subject_id"])
    after = sha256_file(pdf)
    if after != before:
        raise PilotError(f"{rel(pdf)} changed during processing")
    return {
        "source_id": source_id,
        "inventory_id": row["inventory_id"],
        "slot": selected["slot"],
        "status": "processed",
        "row": row,
        "pdf": pdf,
        "sha256_before": before,
        "sha256_after": after,
        "authorization": {
            u: {"permitted": d.permitted, "record": d.record_id} for u, d in decisions.items()
        },
        "raw": raw,
        "raw_path": raw_path,
        "raw_reused": raw_reused,
        "normalized": normalized,
        "normalized_path": norm_path,
        "normalized_reused": norm_reused,
        "devanagari_repair": normalized.get("devanagari_repair"),
        "quality": quality,
    }


# --- enrichment -------------------------------------------------------------------------------


def enrich_document(
    doc: dict[str, Any],
    url_evidence: dict[str, Any] | None,
    catalogue: list[dict[str, Any]],
    generated: dict[str, Any] | None = None,
    attestation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row, normalized = doc["row"], doc["normalized"]
    artifact = rel(doc["normalized_path"])
    unusable = normalized["text_unusable"]
    topics = enrich.apply_topic_validation(
        enrich.topic_records(row, normalized["hierarchy"], artifact), attestation or {}
    )
    ocr_available = unusable and any(
        (p.get("ocr") or {}).get("status") in ("completed", "low_confidence")
        for p in normalized["pages"]
    )
    objectives = (
        enrich.official_objectives(row, catalogue)
        + enrich.explicit_objectives(row, normalized, artifact)
        + enrich.derived_objectives(row, topics, artifact)
        + enrich.ai_generated_objectives(row, normalized, generated or {}, artifact, attestation)
    )
    return {
        "source_document_id": row["source_id"],
        "inventory_id": row["inventory_id"],
        "class_level": row["class_level"],
        "subject_id": row["subject_id"],
        "chapter_title": row["chapter_title"],
        "chapter_title_check": normalized["chapter_title_check"],
        "topics": topics,
        "objectives": objectives,
        "topic_title": enrich.propose_topic_title(topics, unusable, artifact, ocr_available),
        "learning_objective": enrich.propose_objective(
            objectives, unusable, row["subject_id"], ocr_available
        ),
        "source_url": enrich.propose_url(row, url_evidence),
        "acquired_at": enrich.acquisition_evidence(
            row,
            doc["pdf"],
            [PROJECT_ROOT / "resources", DATA / "raw"],
            doc["raw"]["document"]["pdf_metadata"],
        ),
    }


def stable_processed_at(inputs_digest: str) -> str:
    previous = ENRICH_DIR / "provenance_manifest.json"
    if previous.exists():
        old = json.loads(previous.read_text(encoding="utf-8"))
        if old.get("inputs_digest") == inputs_digest:
            return old["processed_at"]
    return now()


def teacher_validation_summary(
    records: list[dict[str, Any]], attestation_present: bool
) -> dict[str, Any]:
    """How much of the owner-attested review state reached the outputs (never assumed).

    The attestation is a private file. When it is missing, or no longer binds to the current
    objective or topic text, statuses stay pending and this summary says so.
    """
    objectives = [
        o
        for r in records
        for o in r["objectives"]
        if o["value_origin"] == "ai_generated" and o.get("grounding") == "grounded"
    ]
    topics = [t for r in records for t in r["topics"] if t["kind"] in tv.TOPIC_KINDS]
    reconciled = sum(o.get("review_completion") == tv.REVIEW_COMPLETED for o in objectives)
    if not objectives:
        status = "not_applicable"
    elif reconciled == len(objectives):
        status = "applied"
    elif not attestation_present:
        status = "attestation_absent"
    else:
        status = "attestation_does_not_bind"
    return {
        "status": status,
        "attestation_present": attestation_present,
        "ai_generated_objectives": len(objectives),
        "objectives_reconciled": reconciled,
        "topic_rows": len(topics),
        "topic_rows_reconciled": sum(
            t.get("review_completion") == tv.REVIEW_COMPLETED for t in topics
        ),
    }


def write_enrichment(
    records: list[dict[str, Any]],
    docs: list[dict[str, Any]],
    inputs: dict[str, Any],
    url_evidence: dict[str, Any] | None,
) -> dict[str, str]:
    inputs_digest = digest(
        {
            "records": records,
            "url_evidence_sha256": sha256_file(URL_EVIDENCE) if URL_EVIDENCE.exists() else None,
            "official_outcomes_sha256": sha256_file(OFFICIAL_OUTCOMES)
            if OFFICIAL_OUTCOMES.exists()
            else None,
            "ai_objectives_sha256": sha256_file(AI_OBJECTIVES) if AI_OBJECTIVES.exists() else None,
            "teacher_validation_sha256": sha256_file(TEACHER_VALIDATION)
            if TEACHER_VALIDATION.exists()
            else None,
            "version": enrich.ENRICHMENT_VERSION,
        }
    )
    processed_at = stable_processed_at(inputs_digest)
    common = {"enrichment_version": enrich.ENRICHMENT_VERSION, "processed_at": processed_at}
    out: dict[str, bytes] = {}

    out["topic_mapping.csv"] = csv_bytes(
        [
            "source_document_id",
            "inventory_id",
            "kind",
            "number",
            "title",
            "display_title",
            "contains_control_characters",
            "pdf_page_index",
            "printed_page_label",
            "extraction_method",
            "confidence",
            "value_status",
            "review_status",
            "review_completion",
            "approval_outcome",
            "validation_record",
            "evidence_reference",
        ],
        [
            [
                t[k]
                for k in (
                    "source_document_id",
                    "inventory_id",
                    "kind",
                    "number",
                    "title",
                    "display_title",
                    "contains_control_characters",
                    "pdf_page_index",
                    "printed_page_label",
                    "extraction_method",
                    "confidence",
                    "value_status",
                    "review_status",
                    "review_completion",
                    "approval_outcome",
                    "validation_record",
                    "evidence_reference",
                )
            ]
            for r in records
            for t in r["topics"]
        ],
    )
    out["learning_objective_mapping.csv"] = csv_bytes(
        [
            "source_document_id",
            "objective",
            "value_origin",
            "curriculum_version",
            "pdf_page_index",
            "printed_page_label",
            "supporting_heading",
            "confidence",
            "review_status",
            "evidence_reference",
            "review_completion",
            "approval_outcome",
            "validation_record",
            "review_status_at_generation",
            "objective_id",
            "language",
            "generation_method",
            "generator",
            "generation_record",
            "grounding",
            "evidence_terms",
        ],
        [
            [
                json.dumps(o[k], ensure_ascii=False, sort_keys=True)
                if k == "evidence_terms" and o.get(k)
                else o.get(k)
                for k in (
                    "source_document_id",
                    "objective",
                    "value_origin",
                    "curriculum_version",
                    "pdf_page_index",
                    "printed_page_label",
                    "supporting_heading",
                    "confidence",
                    "review_status",
                    "evidence_reference",
                    "review_completion",
                    "approval_outcome",
                    "validation_record",
                    "review_status_at_generation",
                    "objective_id",
                    "language",
                    "generation_method",
                    "generator",
                    "generation_record",
                    "grounding",
                    "evidence_terms",
                )
            ]
            for r in records
            for o in r["objectives"]
        ],
    )
    out["source_url_mapping.csv"] = csv_bytes(
        [
            "source_document_id",
            "url",
            "url_value_status",
            "source_organization",
            "source_title",
            "book_page_url",
            "verification_date",
            "verification_method",
            "confidence",
            "review_status",
            "reason",
        ],
        [
            [
                r["source_document_id"],
                *(
                    r["source_url"].get(k)
                    for k in (
                        "value",
                        "value_status",
                        "source_organization",
                        "source_title",
                        "book_page_url",
                        "verification_date",
                        "verification_method",
                        "confidence",
                        "review_status",
                        "reason",
                    )
                ),
            ]
            for r in records
        ],
    )
    out["acquisition_date_evidence.json"] = json_bytes(
        [{"source_document_id": r["source_document_id"], **r["acquired_at"]} for r in records]
    )

    unified = []
    for r in records:
        t, o, u, a = r["topic_title"], r["learning_objective"], r["source_url"], r["acquired_at"]
        unified.append(
            {
                "source_document_id": r["source_document_id"],
                "inventory_id": r["inventory_id"],
                "topic_title": t["value"],
                "learning_objective": o["value"],
                "source_url": u["value"],
                "acquired_at": a["value"],
                "topic_value_status": t["value_status"],
                "objective_value_status": o["value_status"],
                "url_value_status": u["value_status"],
                "acquisition_date_status": a["acquisition_date_status"],
                "value_origin": {
                    "topic_title": t.get("value_origin"),
                    "learning_objective": o.get("value_origin"),
                    "source_url": "official_publisher_url" if u["value"] else None,
                    "acquired_at": None,
                },
                "evidence_reference": {
                    "topic_title": t["evidence_reference"],
                    "learning_objective": "learning_objective_mapping.csv",
                    "source_url": u.get("evidence_reference"),
                    "acquired_at": "acquisition_date_evidence.json",
                },
                "pdf_page_index": t.get("pdf_page_index"),
                "confidence": {
                    "topic_title": t.get("confidence"),
                    "source_url": u.get("confidence"),
                },
                "review_status": {
                    "topic_title": t["review_status"],
                    "learning_objective": o["review_status"],
                    "source_url": u["review_status"],
                    "acquired_at": a["review_status"],
                },
                "reasons": {
                    "topic_title": t.get("reason"),
                    "learning_objective": o.get("reason"),
                    "source_url": u.get("reason"),
                    "acquired_at": a.get("reason"),
                },
                "review_completion": {
                    "topic_title": t.get("review_completion"),
                    "learning_objective": o.get("review_completion"),
                },
                "approval_outcome": {
                    "topic_title": t.get("approval_outcome"),
                    "learning_objective": o.get("approval_outcome"),
                },
                "objective_counts_by_origin": o["counts_by_origin"],
                "topic_count": t["topic_count"],
                "chapter_title_check": r["chapter_title_check"]["status"],
                **common,
            }
        )
    out["unified_enrichment.json"] = json_bytes(unified)
    flat_keys = [
        "source_document_id",
        "inventory_id",
        "topic_title",
        "learning_objective",
        "source_url",
        "acquired_at",
        "topic_value_status",
        "objective_value_status",
        "url_value_status",
        "acquisition_date_status",
        "value_origin",
        "evidence_reference",
        "pdf_page_index",
        "confidence",
        "review_status",
        "enrichment_version",
        "processed_at",
    ]
    out["unified_enrichment.csv"] = csv_bytes(
        flat_keys,
        [
            [
                json.dumps(u[k], ensure_ascii=False, sort_keys=True)
                if isinstance(u[k], dict)
                else u[k]
                for k in flat_keys
            ]
            for u in unified
        ],
    )

    fields = ("topic_title", "learning_objective", "source_url", "acquired_at")
    status_key = {
        "topic_title": "topic_value_status",
        "learning_objective": "objective_value_status",
        "source_url": "url_value_status",
        "acquired_at": "acquisition_date_status",
    }
    missing = {
        f: {
            "status_counts": dict(collections.Counter(u[status_key[f]] for u in unified)),
            "populated": sum(1 for u in unified if u[f]),
            "documents": len(unified),
            "unresolved": [
                {
                    "source_document_id": u["source_document_id"],
                    "status": u[status_key[f]],
                    "reason": u["reasons"][f],
                }
                for u in unified
                if not u[f]
            ],
        }
        for f in fields
    }
    out["missing_value_report.json"] = json_bytes({**common, "fields": missing})
    lines = [
        "# Missing-value resolution report (pilot)",
        "",
        f"Enrichment {common['enrichment_version']}, processed {processed_at}.",
        "",
    ]
    for f, m in missing.items():
        lines.append(f"## `{f}`: {m['populated']} of {m['documents']} populated")
        lines.append("")
        lines.append(f"- Status counts: {m['status_counts']}")
        lines += [
            f"- `{x['source_document_id']}`: {x['status']} ({x['reason']})" for x in m["unresolved"]
        ]
        lines.append("")
    out["missing_value_report.md"] = "\n".join(lines).encode()

    queue = []
    for d, r in zip(docs, records, strict=True):
        sid = r["source_document_id"]
        pages = d["raw"]["pages"]
        candidates = [p for p in pages if p["classification"]["ocr_candidate"]]
        weak_statuses = ("low_confidence", "minimal_text", "no_text_found")
        status_of = {p["page_index"]: p["ocr"].get("status") for p in candidates}
        weak = [i for i, s in status_of.items() if s in weak_statuses]
        not_done = [i for i, s in status_of.items() if s != "completed" and i not in weak]
        done = [i for i, s in status_of.items() if s == "completed"]
        review_pages = [p["page_index"] for p in pages if p["classification"]["needs_review"]]
        if not_done:
            statuses = collections.Counter(status_of[i] for i in not_done)
            queue.append(
                [
                    "high",
                    "ocr_required",
                    sid,
                    not_done,
                    f"OCR not run for these pages: {dict(sorted(statuses.items()))}",
                ]
            )
        if weak:
            statuses = collections.Counter(status_of[i] for i in weak)
            queue.append(
                [
                    "high",
                    "ocr_low_confidence_or_empty",
                    sid,
                    weak,
                    "OCR ran but the result is weak or near-empty"
                    f" {dict(sorted(statuses.items()))}; read these pages from the page image",
                ]
            )
        if done:
            queue.append(
                [
                    "medium",
                    "ocr_quality_review",
                    sid,
                    done,
                    "OCR completed; compare OCR text with the page image before relying on it",
                ]
            )
        repaired_pages = [p for p in d["normalized"]["pages"] if p.get("devanagari_repair")]
        signs = {
            p["page_index"]: len(p["devanagari_repair"]["repeated_vowel_signs_for_review"])
            for p in repaired_pages
            if p["devanagari_repair"]["repeated_vowel_signs_for_review"]
        }
        others = collections.Counter(
            f["kind"]
            for p in repaired_pages
            for f in p["devanagari_repair"].get("other_repeats_for_review", [])
        )
        if signs or others:
            flagged = sorted(
                set(signs)
                | {
                    p["page_index"]
                    for p in repaired_pages
                    if p["devanagari_repair"].get("other_repeats_for_review")
                }
            )
            queue.append(
                [
                    "medium",
                    "hindi_repeated_vowel_sign_review",
                    sid,
                    flagged,
                    f"{sum(signs.values())} repeated vowel sign(s) remain after D-044, plus"
                    f" {dict(sorted(others.items()))} other flags (missing conjunct consonants"
                    " and repeated sign pairs are definite; consonant/syllable repeats are"
                    " suspect only); flags are not exhaustive, so the chapter needs proofreading;"
                    " not covered by D-044; correct only after checking the page image",
                ]
            )
        if review_pages:
            reasons = collections.Counter(
                x for p in pages for x in p["classification"]["review_reasons"]
            )
            queue.append(
                [
                    "medium",
                    "page_review",
                    sid,
                    review_pages,
                    json.dumps(dict(reasons), sort_keys=True),
                ]
            )
        if not r["chapter_title_check"]["status"].startswith("consistent"):
            queue.append(
                ["medium", "chapter_title_check", sid, [], r["chapter_title_check"]["status"]]
            )
        for f in fields:
            status = {
                "topic_title": r["topic_title"]["value_status"],
                "learning_objective": r["learning_objective"]["value_status"],
                "source_url": r["source_url"]["value_status"],
                "acquired_at": r["acquired_at"]["acquisition_date_status"],
            }[f]
            if status not in ("verified",):
                reason = {
                    "topic_title": r["topic_title"],
                    "learning_objective": r["learning_objective"],
                    "source_url": r["source_url"],
                    "acquired_at": r["acquired_at"],
                }[f].get("reason")
                queue.append(
                    ["medium" if f != "acquired_at" else "low", f"{f}:{status}", sid, [], reason]
                )
    out["human_review_queue.csv"] = csv_bytes(
        ["priority", "item", "source_document_id", "pdf_page_indexes", "reason"],
        [[p, i, s, " ".join(map(str, pg)), reason] for p, i, s, pg, reason in queue],
    )

    hashes = {}
    for name, data in out.items():
        write_bytes(ENRICH_DIR / name, data)
        hashes[name] = hashlib.sha256(data).hexdigest()
    teacher_summary = teacher_validation_summary(records, TEACHER_VALIDATION.exists())
    if teacher_summary["status"] not in ("applied", "not_applicable"):
        print(
            f"warning: teacher validation not applied ({teacher_summary['status']}): "
            f"{teacher_summary['objectives_reconciled']} of "
            f"{teacher_summary['ai_generated_objectives']} AI objectives reconciled; "
            "review statuses remain pending. The owner attestation is a private file "
            "(see docs/PUBLICATION_AND_REPRODUCIBILITY.md).",
            file=sys.stderr,
        )
    d053 = oa.verify_d053()
    if d053["status"] in (oa.STALE, oa.INVALID):
        print(
            f"warning: D-053 page-review attestation is {d053['status']}: "
            + "; ".join(d053["problems"])
            + ". Page review is treated as not completed.",
            file=sys.stderr,
        )
    manifest = {
        **common,
        "inputs_digest": inputs_digest,
        "phase3_run_id": inputs["phase3_run_id"],
        "cleaned_inventory_sha256": inputs["cleaned_sha256"],
        "authorization_records": sorted({r["record_id"] for r in inputs["records"]}),
        "raw_artifacts": {rel(d["raw_path"]): sha256_file(d["raw_path"]) for d in docs},
        "normalized_artifacts": {
            rel(d["normalized_path"]): sha256_file(d["normalized_path"]) for d in docs
        },
        "url_evidence": {"path": rel(URL_EVIDENCE), "sha256": sha256_file(URL_EVIDENCE)}
        if url_evidence
        else None,
        "official_outcomes_catalogue": rel(OFFICIAL_OUTCOMES)
        if OFFICIAL_OUTCOMES.exists()
        else None,
        "ai_generated_objectives": {
            "path": rel(AI_OBJECTIVES),
            "sha256": sha256_file(AI_OBJECTIVES),
            "approval": "owner-approved 2026-10-31 (docs/DECISIONS.md D-049)",
        }
        if AI_OBJECTIVES.exists()
        else None,
        "teacher_validation_attestation": {
            "path": rel(TEACHER_VALIDATION),
            "sha256": sha256_file(TEACHER_VALIDATION),
            "decision": tv.DECISION_REFERENCE,
        }
        if TEACHER_VALIDATION.exists()
        else None,
        "teacher_validation": teacher_summary,
        "d053_page_review": {
            "status": d053["status"],
            "attestation_sha256": d053.get("attestation_sha256"),
            "pages_in_scope": len(d053["pages"]),
            "problems": d053["problems"] if d053["status"] != oa.ABSENT else [],
        },
        "outputs": hashes,
        "master_inventory_written": False,
        "database_writes": "none",
        "external_ai_calls": "none",
    }
    write_bytes(ENRICH_DIR / "provenance_manifest.json", json_bytes(manifest))
    return hashes


# --- main ----------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    try:
        inputs = load_inputs()
    except (PilotError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    ocr_env = ocr_pages.detect_tesseract()
    results = [
        process_document(item, inputs, ocr_env)
        for item in inputs["selection"]["selected"]
        if item.get("status") == "selected"
    ]
    docs = [r for r in results if r["status"] == "processed"]
    url_evidence = (
        json.loads(URL_EVIDENCE.read_text(encoding="utf-8")) if URL_EVIDENCE.exists() else None
    )
    catalogue = enrich.load_official_catalogue(OFFICIAL_OUTCOMES)
    generated = enrich.load_generated_objectives(AI_OBJECTIVES)
    attestation = tv.load_attestation(TEACHER_VALIDATION)
    records = [enrich_document(d, url_evidence, catalogue, generated, attestation) for d in docs]
    enrichment_hashes = write_enrichment(records, docs, inputs, url_evidence)

    quality = {d["source_id"]: {"slot": d["slot"], **d["quality"]} for d in docs}
    events = b"".join(
        json.dumps(
            {
                k: v
                for k, v in r.items()
                if k
                in (
                    "source_id",
                    "slot",
                    "status",
                    "reason",
                    "raw_reused",
                    "normalized_reused",
                    "sha256_before",
                    "sha256_after",
                )
            },
            sort_keys=True,
        ).encode()
        + b"\n"
        for r in results
    )
    write_bytes(LOG_DIR / "quality_report.json", json_bytes(quality))
    write_bytes(LOG_DIR / "events.jsonl", events)
    run_manifest = {
        "pipeline_version": PIPELINE_VERSION,
        "versions": {
            "extractor": EXTRACTOR_VERSION,
            "normalizer": clean_text.NORMALIZER_VERSION,
            "structure": structure_content.STRUCTURE_VERSION,
            "quality": QUALITY_VERSION,
            "enrichment": enrich.ENRICHMENT_VERSION,
            "devanagari_repair": repair_devanagari.REPAIR_VERSION,
        },
        "config_sha256": inputs["config_sha256"],
        "ocr_environment": ocr_env.as_dict(),
        "ocr_enabled_in_config": inputs["ocr_enabled"],
        "documents": [
            {
                k: (rel(v) if isinstance(v, Path) else v)
                for k, v in r.items()
                if k
                in (
                    "source_id",
                    "inventory_id",
                    "slot",
                    "status",
                    "reason",
                    "sha256_before",
                    "sha256_after",
                    "authorization",
                    "raw_path",
                    "raw_reused",
                    "normalized_path",
                    "normalized_reused",
                    "devanagari_repair",
                )
            }
            for r in results
        ],
        "pages_processed": sum(len(d["raw"]["pages"]) for d in docs),
        "enrichment_outputs": enrichment_hashes,
        "database_writes": "none",
        "external_ai_calls": "none",
    }
    write_bytes(LOG_DIR / "run_manifest.json", json_bytes(run_manifest))
    print(
        json.dumps(
            {
                "documents": len(results),
                "processed": len(docs),
                "pages": run_manifest["pages_processed"],
            }
        )
    )
    return 0 if len(docs) == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
