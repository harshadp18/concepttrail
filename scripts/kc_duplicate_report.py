"""Read-only review report of possibly duplicate or overlapping knowledge components.

    python -m scripts.kc_duplicate_report [--threshold 0.5]

Pairs within a subject are flagged when their normalised names are equal or their name +
description word sets overlap (Jaccard) at or above the threshold. For each pair the report gives
IDs, names, classes, descriptions, curriculum provenance, question counts, learner evidence (the
mastery-history impact of a merge) and a recommendation. Nothing is merged, renamed or deleted:
the decision belongs to a human reviewer. Output: data_pipeline/data/logs/kc_review/ (git-ignored).
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    CurriculumItem,
    CurriculumVersion,
    KcCurriculumMap,
    KcEdge,
    KnowledgeComponent,
    QuestionKc,
    StudentKcState,
)
from app.db.session import create_db_engine

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data_pipeline/data/logs/kc_review"
STOP = {
    "the",
    "a",
    "an",
    "of",
    "and",
    "to",
    "in",
    "for",
    "on",
    "with",
    "by",
    "students",
    "will",
    "be",
    "able",
    "their",
    "is",
    "are",
    "how",
    "from",
    "using",
    "into",
    "or",
    "that",
    "as",
}


def words(*texts: str | None) -> set[str]:
    return {w for t in texts for w in re.findall(r"\w+", (t or "").casefold()) if w not in STOP}


def recommend(a: dict, b: dict, same_name: bool, overlap: float) -> str:
    if a["classes"] != b["classes"]:
        return (
            "Likely the same idea taught at different class levels: keep both, rename to state the "
            "class-specific depth, or link them with a reviewed prerequisite edge; do not merge "
            "(their questions and mastery histories belong to different curricula)."
        )
    if same_name and overlap < 0.3:
        return (
            "Same name, different descriptions: probably distinct facets named too generally. A "
            "reviewer should rename each to its specific assessable skill (or merge if the "
            "descriptions turn out to mean the same thing)."
        )
    if same_name or overlap >= 0.7:
        return (
            "Likely duplicate within one class: a reviewer should choose one KC to keep, remap the "
            "other's questions and curriculum mappings to it, and decide how to reconcile any "
            "learner mastery history before retiring the other."
        )
    return "Overlapping scope: a reviewer should sharpen both descriptions so each is assessable."


def build(threshold: float) -> dict:
    with Session(create_db_engine(read_only=True)) as db:
        kcs = db.scalars(select(KnowledgeComponent)).all()
        classes: dict[str, set[int]] = defaultdict(set)
        items: dict[str, list[str]] = defaultdict(list)
        for kc_id, item_id, title, level in db.execute(
            select(
                KcCurriculumMap.kc_id,
                CurriculumItem.item_id,
                CurriculumItem.title,
                CurriculumVersion.class_level,
            )
            .join(CurriculumItem, CurriculumItem.item_id == KcCurriculumMap.item_id)
            .join(
                CurriculumVersion,
                CurriculumVersion.curriculum_version_id == CurriculumItem.curriculum_version_id,
            )
        ):
            classes[kc_id].add(int(level))
            items[kc_id].append(f"{item_id}: {title}")
        qcount = dict(
            db.execute(select(QuestionKc.kc_id, func.count()).group_by(QuestionKc.kc_id)).all()
        )
        learners = dict(
            db.execute(
                select(StudentKcState.kc_id, func.count()).group_by(StudentKcState.kc_id)
            ).all()
        )
        edges = {(e.prerequisite_kc_id, e.dependent_kc_id) for e in db.scalars(select(KcEdge))}
    rows = {
        k.kc_id: {
            "kc_id": k.kc_id,
            "subject_id": k.subject_id,
            "name": k.name,
            "description": k.description,
            "review_status": k.review_status,
            "classes": sorted(classes[k.kc_id]),
            "curriculum_items": items[k.kc_id],
            "question_count": qcount.get(k.kc_id, 0),
            "learners_with_mastery_state": learners.get(k.kc_id, 0),
        }
        for k in kcs
    }
    pairs = []
    by_subject: dict[str, list[dict]] = defaultdict(list)
    for r in rows.values():
        by_subject[r["subject_id"]].append(r)
    for subject_rows in by_subject.values():
        for a, b in itertools.combinations(sorted(subject_rows, key=lambda r: r["kc_id"]), 2):
            same = (a["name"] or "").strip().casefold() == (b["name"] or "").strip().casefold()
            wa, wb = words(a["name"], a["description"]), words(b["name"], b["description"])
            overlap = len(wa & wb) / len(wa | wb) if wa and wb else 0.0
            if same or overlap >= threshold:
                pairs.append(
                    {
                        "kc_ids": [a["kc_id"], b["kc_id"]],
                        "same_name": same,
                        "word_overlap": round(overlap, 3),
                        "linked_by_edge": (a["kc_id"], b["kc_id"]) in edges
                        or (b["kc_id"], a["kc_id"]) in edges,
                        "a": a,
                        "b": b,
                        "mastery_history_impact": a["learners_with_mastery_state"]
                        + b["learners_with_mastery_state"],
                        "recommendation": recommend(a, b, same, overlap),
                    }
                )
    pairs.sort(key=lambda p: (not p["same_name"], -p["word_overlap"]))
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "threshold": threshold,
        "kcs": len(rows),
        "pairs": pairs,
        "note": "Candidates for human review only; nothing was merged or changed.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.kc_duplicate_report")
    parser.add_argument("--threshold", type=float, default=0.5)
    args = parser.parse_args(argv)
    report = build(args.threshold)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"kc_duplicates_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for p in report["pairs"]:
        print(
            f"{p['kc_ids'][0]} ~ {p['kc_ids'][1]} same_name={p['same_name']} "
            f"overlap={p['word_overlap']} classes={p['a']['classes']}/{p['b']['classes']} "
            f"| {p['a']['name']} / {p['b']['name']}"
        )
    print(f"{len(report['pairs'])} candidate pairs; report: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
