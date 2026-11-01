"""Import the assembled DEMO dataset into existing tables (dry run by default, one transaction).

Rows are written with `review_status = "demo_release"` (questions also `active = true`), with
provenance in `questions.verification`/`source_refs`. Rules:

- a non-demo row with the same key is never overwritten (conflict, nothing written);
- a demo row is updated only if the regenerated content differs; identical rows are no-ops;
- chapter `curriculum_item` and its `curriculum_version` move from `needs_review` to
  `demo_release` only; any other status is left alone;
- questions are re-validated here (KC exists in the dataset, source digest and chapter match
  the database, no duplicate of an existing question); failures are reported, not imported.
Refuses unless the target is the verified local development database.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    CurriculumItem,
    CurriculumVersion,
    KcCurriculumMap,
    KcEdge,
    KnowledgeComponent,
    Question,
    QuestionKc,
    QuestionOption,
    SourceDocument,
)
from app.db.session import create_db_engine
from app.services.question_bank import (
    NAMESPACE,
    QuestionDraft,
    content_hash,
    duplicate_key,
    question_id_for,
    validate_structure,
)
from data_pipeline.demo_content import DEMO_STATUS
from scripts.seed_dev_auth import preflight

ROOT = Path(__file__).resolve().parents[2]
LOGS = ROOT / "data_pipeline/data/logs/demo_import"
TABLES = (KnowledgeComponent, KcCurriculumMap, KcEdge, Question, QuestionOption, QuestionKc)


class ImportConflict(RuntimeError):
    pass


def _counts(session: Session) -> dict[str, int]:
    out = {m.__tablename__: session.scalar(select(func.count()).select_from(m)) for m in TABLES}
    out["demo_curriculum_items"] = session.scalar(
        select(func.count()).select_from(CurriculumItem).where(CurriculumItem.status == DEMO_STATUS)
    )
    return out


def edge_reason(edge: dict[str, Any]) -> str:
    """Label an AI-drafted edge as such. The model's "expert_judgement" is its own judgement,
    not a human expert's (that basis is reserved for reviewed expert rationales)."""
    basis = "judgement" if edge["basis"] == "expert_judgement" else edge["basis"]
    return f"[ai-drafted:{basis}] {edge['reason']}"


def _upsert(session: Session, model: type, key: Any, values: dict[str, Any], stats: dict) -> None:
    row = session.get(model, key)
    name = model.__tablename__
    if row is None:
        session.add(model(**values))
        stats[name]["insert"] += 1
        return
    if getattr(row, "review_status", DEMO_STATUS) != DEMO_STATUS:
        raise ImportConflict(f"{name} {key} exists with a non-demo status; never overwritten")
    changed = {k: v for k, v in values.items() if getattr(row, k) != v}
    if changed:
        for k, v in changed.items():
            setattr(row, k, v)
        stats[name]["update"] += 1
    else:
        stats[name]["unchanged"] += 1


def apply_dataset(session: Session, dataset: dict[str, Any]) -> dict[str, Any]:
    stats: dict[str, dict[str, int]] = {
        m.__tablename__: {"insert": 0, "update": 0, "unchanged": 0} for m in TABLES
    }
    rejected: list[dict[str, Any]] = []
    sources = {s.source_id: s for s in session.scalars(select(SourceDocument))}
    for chapter in dataset["chapters"]:
        if (
            chapter["source_id"] not in sources
            or session.get(CurriculumItem, chapter["inventory_id"]) is None
        ):
            raise ImportConflict(f"{chapter['source_id']}: run scripts.populate_content first")
    kc_ids = set()
    for kc in dataset["kcs"]:
        by_key = session.scalar(
            select(KnowledgeComponent).where(KnowledgeComponent.stable_key == kc["stable_key"])
        )
        if by_key is not None and by_key.kc_id != kc["kc_id"]:
            raise ImportConflict(f"stable key {kc['stable_key']} belongs to {by_key.kc_id}")
        _upsert(
            session,
            KnowledgeComponent,
            kc["kc_id"],
            {
                "kc_id": kc["kc_id"],
                "subject_id": kc["subject_id"],
                "stable_key": kc["stable_key"],
                "name": kc["name"],
                "description": kc["learning_objective"],
                "kc_type": kc["kc_type"],
                "difficulty_tier": kc["difficulty_tier"],
                "misconceptions": kc["misconceptions"] or None,
                "review_status": DEMO_STATUS,
                "content_version": "kc-v1",
            },
            stats,
        )
        kc_ids.add(kc["kc_id"])
    session.flush()
    for kc in dataset["kcs"]:
        for item_id in kc["inventory_ids"]:
            _upsert(
                session,
                KcCurriculumMap,
                (kc["kc_id"], item_id),
                {
                    "kc_id": kc["kc_id"],
                    "item_id": item_id,
                    "mapping_role": "primary",
                    "review_status": DEMO_STATUS,
                    "created_at": datetime(2026, 11, 1, tzinfo=UTC),
                },
                stats,
            )
    for edge in dataset["edges"]:
        key = (edge["prerequisite_kc_id"], edge["dependent_kc_id"])
        _upsert(
            session,
            KcEdge,
            key,
            {
                "prerequisite_kc_id": key[0],
                "dependent_kc_id": key[1],
                "strength": edge["strength"],
                "reason": edge_reason(edge),
                "review_status": DEMO_STATUS,
            },
            stats,
        )
    session.flush()
    existing_keys = {
        (q.verification or {}).get("duplicate_key"): q.question_id
        for q in session.scalars(select(Question))
    }
    seen: set[str] = set()
    for raw in dataset["questions"]:
        draft = QuestionDraft.model_validate(raw)
        qid = question_id_for(draft)
        problems = [c for c, _ in validate_structure(draft).errors]
        if not set(draft.kc_ids) <= kc_ids:
            problems.append("KC_NOT_IN_DATASET")
        for ref in draft.source_refs:
            source = sources.get(ref.source_id)
            if source is None or not (source.sha256 or "").startswith(ref.sha256):
                problems.append("SOURCE_REF_UNVERIFIED")
        dkey = duplicate_key(draft)
        if dkey in seen or existing_keys.get(dkey) not in (None, qid):
            problems.append("DUPLICATE_QUESTION")
        if problems:
            rejected.append({"question_id": qid, "problems": problems})
            continue
        seen.add(dkey)
        existing = session.get(Question, qid)
        if existing is not None:
            if existing.review_status != DEMO_STATUS:
                raise ImportConflict(f"question {qid} exists with a non-demo status")
            stats["questions"]["unchanged"] += 1
            continue
        session.add(
            Question(
                question_id=qid,
                item_type=draft.item_type,
                stem=draft.stem,
                expected_answer=draft.expected_answer,
                rubric=draft.rubric,
                difficulty=draft.difficulty,
                misconception_map=draft.misconception_map,
                source_refs=[r.model_dump() for r in draft.source_refs],
                verification={
                    "release": "demo",
                    "workflow": DEMO_STATUS,
                    "human_reviewed": False,
                    "content_sha256": content_hash(draft),
                    "duplicate_key": dkey,
                    "validation": validate_structure(draft).as_dict(),
                    "reviews": [],
                    "provenance": {
                        "origin": "ai_drafted",
                        "origin_ref": draft.origin_ref,
                        "class_level": draft.class_level,
                        "subject_id": draft.subject_id,
                        "curriculum_item_id": draft.curriculum_item_id,
                        "language": draft.language,
                        "explanation": draft.explanation,
                        "prompt_version": dataset.get("prompt_version"),
                    },
                },
                review_status=DEMO_STATUS,
                version=1,
                active=True,
            )
        )
        session.flush()
        stats["questions"]["insert"] += 1
        for order, option in enumerate(draft.options, start=1):
            session.add(
                QuestionOption(
                    option_id=uuid.uuid5(NAMESPACE, f"{qid}:1:{option.option_key}"),
                    question_id=qid,
                    option_key=option.option_key,
                    option_text=option.option_text,
                    is_correct=option.is_correct,
                    explanation=option.explanation,
                    display_order=order,
                )
            )
            stats["question_options"]["insert"] += 1
        for kc_id in draft.kc_ids:
            session.add(
                QuestionKc(
                    question_id=qid,
                    kc_id=kc_id,
                    weight=Decimal("1"),
                    mapping_role="primary",
                    review_status=DEMO_STATUS,
                )
            )
            stats["question_kcs"]["insert"] += 1
    promoted = 0
    for chapter in dataset["chapters"]:
        item = session.get(CurriculumItem, chapter["inventory_id"])
        if item.status == "needs_review":
            item.status = DEMO_STATUS
            promoted += 1
        version = session.get(CurriculumVersion, item.curriculum_version_id)
        if version is not None and version.status == "needs_review":
            version.status = DEMO_STATUS
    session.flush()
    return {
        "stats": stats,
        "rejected_questions": rejected,
        "curriculum_items_marked_demo": promoted,
    }


def run_import(dataset_path: Path, *, apply: bool) -> int:
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    if dataset.get("graph_errors"):
        print(f"refused: the dataset graph has errors {dataset['graph_errors']}")
        return 1
    engine = create_db_engine()
    if not preflight(engine).ok:
        print("refused: not the verified local development database")
        return 1
    with Session(engine) as session:
        before = _counts(session)
        try:
            result = apply_dataset(session, dataset)
            if apply:
                session.commit()
            else:
                session.rollback()  # dry run: the transaction is never committed
        except ImportConflict as exc:
            session.rollback()
            print(f"refused, nothing written: {exc}")
            return 1
    with Session(create_db_engine(read_only=True)) as check:
        after = _counts(check)
    report = {
        "mode": "apply" if apply else "dry_run",
        "ran_at": datetime.now(UTC).isoformat(),
        "counts_before": before,
        "counts_after": after,
        **result,
    }
    LOGS.mkdir(parents=True, exist_ok=True)
    (LOGS / f"demo_import_{report['mode']}_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "mode",
                    "counts_before",
                    "counts_after",
                    "stats",
                    "curriculum_items_marked_demo",
                )
            },
            indent=2,
        )
    )
    print(f"rejected questions: {len(result['rejected_questions'])}")
    return 0
