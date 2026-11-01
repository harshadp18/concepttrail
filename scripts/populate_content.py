"""Populate the development database with eligible, traceable content from existing local data.

    python -m scripts.populate_content            # dry run (default): plan only, no writes
    python -m scripts.populate_content --apply    # one transaction; read back; never overwrites

Datasets, in dependency order, all into existing tables:

1. `subject` (the five agreed subjects).
2. `curriculum_version` (board, session, class, course), status `needs_review` (the Phase 3
   master merge is not approved, so nothing is `published`).
3. `source_document` for the 383 accepted inventory rows (quarantined rows are not in the
   accepted file). `rights_status` and `status` are copied; `permitted_uses` is the list of
   uses the purpose-specific gate (`data_pipeline.authorization.check_use`) grants for those
   exact bytes today.
4. `curriculum_item` per accepted row, status `needs_review`; the 51 Phase 4 AI-generated
   objectives are attached with `review_status: not_individually_recorded` (never approved).
5. `content_unit` per page of the 10 Phase 4 pilot artifacts, only when the gate grants
   `local_text_normalization`; page review status is copied (no page is approved).
6. `bkt_config_version`: one PROVISIONAL, uncalibrated parameter set so the mastery engine can
   run in development (its notes say so).

KCs, edges and questions are not populated: none is approved or released.

Safety: refuses unless the target is the verified local development database. An existing row
that differs is a conflict and is never overwritten; identical rows are no-ops (idempotent).
Input file hashes, counts before/after and a read-back go to the manifest under
`data_pipeline/data/logs/db_population/` (ignored by Git).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    BktConfigVersion,
    ContentUnit,
    CurriculumItem,
    CurriculumVersion,
    SourceDocument,
    Subject,
)
from app.db.session import create_db_engine
from data_pipeline import authorization
from data_pipeline.teacher_validation import objective_id
from scripts.seed_dev_auth import preflight

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "resources/teammate_csv/processed/cleaned/curriculum_inventory.cleaned.csv"
ARTIFACTS = ROOT / "data_pipeline/data/processed/textbook_json"
OBJECTIVES = (
    ROOT / "data_pipeline/data/overrides/metadata_enrichment/ai_generated_learning_objectives.json"
)
MANIFEST_DIR = ROOT / "data_pipeline/data/logs/db_population"
PIPELINE = "populate-content-v1"

SUBJECTS = {
    "english": ("English", "languages"),
    "hindi": ("Hindi", "languages"),
    "mathematics": ("Mathematics", "mathematics"),
    "science": ("Science", "science"),
    "social_science": ("Social Science", "social_science"),
}
BKT_PROVISIONAL = {
    "bkt_config_version": "bkt-provisional-v1",
    "parameters": {"p_l0": 0.2, "p_t": 0.1, "p_g": 0.2, "p_s": 0.1},
    "effective_at": datetime(2026, 1, 1, tzinfo=UTC),
    "created_at": datetime(2026, 10, 31, tzinfo=UTC),
    "notes": "PROVISIONAL and UNCALIBRATED development defaults (common BKT starting values). "
    "Not fitted on any learner data; replace with a fitted version before any claim about "
    "mastery accuracy.",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def slug(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "-", text.upper()).strip("-")


def _date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.combine(date.fromisoformat(value[:10]), datetime.min.time(), UTC)
    except ValueError:
        return None


def version_id(row: dict[str, str]) -> str:
    return (
        f"{row['board']}-{row['academic_session']}-C{int(row['class_level']):02d}-"
        f"{slug(row['course_or_language'])}"
    )


def build_datasets(records: list[dict[str, Any]] | None = None) -> dict[str, list[dict[str, Any]]]:
    rows = list(csv.DictReader(INVENTORY.open(encoding="utf-8", newline="")))
    accepted = [r for r in rows if r["validation_status"] == "passed" and r["source_id"]]
    data: dict[str, list[dict[str, Any]]] = {
        k: []
        for k in (
            "subject",
            "curriculum_version",
            "source_document",
            "curriculum_item",
            "content_unit",
            "bkt_config_version",
        )
    }
    data["subject"] = [
        {"subject_id": k, "display_name": v[0], "subject_family": v[1], "active": True}
        for k, v in SUBJECTS.items()
    ]
    versions: dict[str, dict[str, Any]] = {}
    for r in accepted:
        vid = version_id(r)
        versions.setdefault(
            vid,
            {
                "curriculum_version_id": vid,
                "board": r["board"],
                "academic_session": r["academic_session"],
                "class_level": int(r["class_level"]),
                "course_or_language": r["course_or_language"],
                "source_url": None,
                "verified_at": None,
                "status": "needs_review",
            },
        )
    data["curriculum_version"] = sorted(versions.values(), key=lambda v: v["curriculum_version_id"])
    uses = sorted(authorization.KNOWN_USES)
    for r in accepted:
        permitted = [
            u
            for u in uses
            if authorization.check_use(r["source_id"], r["sha256"], u, records).permitted
        ]
        title = " ".join(
            x
            for x in (r["resource_title"] + ":", r["chapter_or_unit_code"], r["chapter_title"])
            if x
        )
        data["source_document"].append(
            {
                "source_id": r["source_id"],
                "subject_id": r["subject_id"],
                "curriculum_version_id": version_id(r),
                "title": title,
                "source_url": r["source_url"] or None,
                "publisher": None,
                "edition_label": r["publication_or_revision"] or None,
                "acquired_at": _date(r["acquired_at"]),
                "sha256": r["sha256"],
                "rights_status": r["rights_status"],
                "permitted_uses": permitted,
                "permission_reference": r["permission_reference"] or None,
                "last_verified_at": _date(r["last_verified_at"]),
                "status": r["review_status"],
            }
        )
    objectives: dict[str, list[dict[str, Any]]] = {}
    generation = json.loads(OBJECTIVES.read_text(encoding="utf-8"))
    for chapter in generation["chapters"]:
        objectives[chapter["inventory_id"]] = [
            {
                "objective_id": objective_id(chapter["inventory_id"], n),
                "text": o["text"],
                "language": chapter.get("language"),
                "origin": "ai_generated",
                "generation_record": generation["record_id"],
                "review_status": "not_individually_recorded",
                "note": "AI-generated draft; review completion was owner-attested, no individual "
                "approval exists",
            }
            for n, o in enumerate(chapter["objectives"], start=1)
        ]
    for r in accepted:
        data["curriculum_item"].append(
            {
                "item_id": r["inventory_id"],
                "curriculum_version_id": version_id(r),
                "subject_id": r["subject_id"],
                "parent_item_id": None,
                "item_type": "chapter" if r["item_type"] == "chapter_pdf" else "other_resource",
                "title": r["chapter_title"],
                "sequence_label": r["chapter_or_unit_code"] or None,
                "learning_objectives": objectives.get(r["inventory_id"]),
                "status": "needs_review",
            }
        )
    by_source = {r["source_id"]: r for r in accepted}
    for path in sorted(ARTIFACTS.glob("*.normalized.json")):
        artifact = json.loads(path.read_text(encoding="utf-8"))
        doc = artifact["document"]
        inv = by_source.get(doc["source_id"])
        if inv is None or doc["pdf_sha256"] != inv["sha256"]:
            continue
        if not authorization.check_use(
            doc["source_id"], inv["sha256"], "local_text_normalization", records
        ).permitted:
            continue
        for page in artifact["pages"]:
            text = page.get("text") or ""
            data["content_unit"].append(
                {
                    "content_unit_id": f"{doc['source_id']}:p{page['page_index']:03d}",
                    "source_id": doc["source_id"],
                    "item_id": inv["inventory_id"],
                    "unit_type": "page",
                    "title": doc.get("chapter_title"),
                    "content_text": text,
                    "pdf_page_index": page["page_index"],
                    "printed_page_label": (page.get("page_label") or {}).get("value"),
                    "asset_refs": {
                        "artifact": path.name,
                        "raw_ref": page.get("raw_ref"),
                        "classification": page.get("classification"),
                        "ocr_status": page.get("ocr_status"),
                        "text_unusable": bool(page.get("text_unusable")),
                    },
                    "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "extraction_status": "text_unusable"
                    if page.get("text_unusable") or artifact.get("text_unusable")
                    else page.get("extraction_method", "extracted"),
                    "review_status": page.get("review_status") or "needs_review",
                    "pipeline_version": artifact.get("normalizer_version"),
                }
            )
    data["bkt_config_version"] = [dict(BKT_PROVISIONAL)]
    return data


MODELS: dict[str, tuple[type, Callable[[dict[str, Any]], Any]]] = {
    "subject": (Subject, lambda r: r["subject_id"]),
    "curriculum_version": (CurriculumVersion, lambda r: r["curriculum_version_id"]),
    "source_document": (SourceDocument, lambda r: r["source_id"]),
    "curriculum_item": (CurriculumItem, lambda r: r["item_id"]),
    "content_unit": (ContentUnit, lambda r: r["content_unit_id"]),
    "bkt_config_version": (BktConfigVersion, lambda r: r["bkt_config_version"]),
}


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, datetime) and isinstance(b, datetime):
        return a == b
    if isinstance(a, (dict, list)) or isinstance(b, (dict, list)):
        return json.dumps(a, sort_keys=True, default=str) == json.dumps(
            b, sort_keys=True, default=str
        )
    return a == b


def validate(data: dict[str, list[dict[str, Any]]]) -> list[str]:
    problems = []
    keys = {name: [MODELS[name][1](r) for r in rows] for name, rows in data.items()}
    for name, ids in keys.items():
        if len(set(ids)) != len(ids):
            problems.append(f"{name}: duplicate keys")
    subjects, versions = set(keys["subject"]), set(keys["curriculum_version"])
    sources, items = set(keys["source_document"]), set(keys["curriculum_item"])
    for r in data["source_document"]:
        if r["subject_id"] not in subjects or r["curriculum_version_id"] not in versions:
            problems.append(f"source_document {r['source_id']}: dangling foreign key")
        if not re.fullmatch(r"[0-9a-f]{64}", r["sha256"] or ""):
            problems.append(f"source_document {r['source_id']}: invalid sha256")
    for r in data["curriculum_item"]:
        if r["subject_id"] not in subjects or r["curriculum_version_id"] not in versions:
            problems.append(f"curriculum_item {r['item_id']}: dangling foreign key")
    for r in data["content_unit"]:
        if r["source_id"] not in sources or r["item_id"] not in items:
            problems.append(f"content_unit {r['content_unit_id']}: dangling foreign key")
    return problems


def plan(session: Session, data: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    out = {}
    for name, rows in data.items():
        model, key = MODELS[name]
        inserts, same, conflicts = [], 0, []
        for row in rows:
            existing = session.get(model, key(row))
            if existing is None:
                inserts.append(row)
            elif all(_same(getattr(existing, c), v) for c, v in row.items()):
                same += 1
            else:
                diff = sorted(c for c, v in row.items() if not _same(getattr(existing, c), v))
                conflicts.append({"key": str(key(row)), "columns": diff})
        out[name] = {"insert": inserts, "unchanged": same, "conflicts": conflicts}
    return out


def counts(session: Session) -> dict[str, int]:
    return {n: session.scalar(select(func.count()).select_from(m)) for n, (m, _) in MODELS.items()}


def run(apply: bool) -> dict[str, Any]:
    engine = create_db_engine(read_only=not apply)
    pre = preflight(engine)
    if not pre.ok:
        raise SystemExit(f"refused: {pre.problems}")
    data = build_datasets()
    problems = validate(data)
    manifest: dict[str, Any] = {
        "pipeline": PIPELINE,
        "mode": "apply" if apply else "dry_run",
        "ran_at": datetime.now(UTC).isoformat(),
        "inputs": {
            str(p.relative_to(ROOT)): sha256_file(p)
            for p in [INVENTORY, OBJECTIVES, *sorted(ARTIFACTS.glob("*.normalized.json"))]
        },
        "validation_problems": problems,
    }
    if problems:
        manifest["result"] = "refused_invalid_input"
        return manifest
    with Session(engine) as session:
        manifest["counts_before"] = counts(session)
        p = plan(session, data)
        manifest["plan"] = {
            n: {
                "insert": len(v["insert"]),
                "unchanged": v["unchanged"],
                "conflicts": v["conflicts"],
            }
            for n, v in p.items()
        }
        if not apply:
            manifest["result"] = "dry_run_no_writes"
            return manifest
        try:  # the planning reads opened the transaction; all inserts commit together
            for name in MODELS:
                model, _ = MODELS[name]
                for row in p[name]["insert"]:
                    session.add(model(**row))
                session.flush()
            session.commit()
        except BaseException:
            session.rollback()
            raise
        with Session(engine) as check:
            manifest["counts_after"] = counts(check)
            readback = plan(check, data)
            manifest["readback"] = {
                n: {
                    "missing": len(v["insert"]),
                    "matching": v["unchanged"],
                    "conflicts": len(v["conflicts"]),
                }
                for n, v in readback.items()
            }
        manifest["result"] = "applied"
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.populate_content")
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    args = parser.parse_args(argv)
    manifest = run(args.apply)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (MANIFEST_DIR / f"populate_{manifest['mode']}_{stamp}.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8"
    )
    summary = {
        k: manifest.get(k)
        for k in (
            "mode",
            "result",
            "validation_problems",
            "counts_before",
            "plan",
            "counts_after",
            "readback",
        )
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0 if manifest["result"] in ("applied", "dry_run_no_writes") else 1


if __name__ == "__main__":
    sys.exit(main())
