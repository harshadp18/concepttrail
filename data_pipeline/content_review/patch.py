# ruff: noqa: E501  (review records and evidence are prose)
"""AI content review -> a reviewable, reversible content patch for `demo_release` rows.

    python -m data_pipeline.content_review.patch build              # read-only: write patch JSON
    python -m data_pipeline.content_review.patch apply --database-url URL [--apply]

`build` reads the current rows (read-only engine), turns the AI review findings into concrete
operations with BEFORE and AFTER values, adds the original synthetic gap-fill questions, and
writes `patch_v1.json` next to the private review records (see `records.py`; not published).

`apply` applies that patch inside ONE transaction to the database named by `--database-url`
(dry run unless `--apply`). It refuses any row that is not `demo_release`, refuses a row whose
current value no longer matches the recorded BEFORE value, never changes `review_status`, never
sets `human_reviewed`, and records an explicit `ai_review` entry in `questions.verification`.
It was verified on a disposable restored copy; it has NOT been applied to the persistent
database (that is the owner's decision).

Every one of the 460 reviewed questions gets an `ai_review` verdict: `no_defect_found`,
`repaired`, `withdrawn` (active = false) or `escalated` (left as is, listed for human review).
An AI review is not an independent human review and is never recorded as one.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.models import (
    CurriculumItem,
    KcCurriculumMap,
    KcEdge,
    KnowledgeComponent,
    Question,
    QuestionKc,
    QuestionOption,
)
from data_pipeline.content_review import records

ROOT = Path(__file__).resolve().parents[2]
PATCH = records.PATCH
AUDIT_DIR = ROOT / "data_pipeline/data/logs/content_review"
REVIEWER = "claude-opus-5-5 (AI model; not a human reviewer)"
REVIEW_DATE = "2026-11-01"
DEMO = "demo_release"


class PatchConflict(RuntimeError):
    pass


def load_findings() -> tuple[list[dict], Any]:
    """Question findings and a graph-findings view, read from the private records."""
    graph = SimpleNamespace(
        REMOVE_EDGES=records.remove_edges(),
        ESCALATE_EDGES=records.escalate_edges(),
        KC_FINDINGS=records.kc_findings(),
    )
    return records.findings(), graph


def explanation_of(q: Question) -> str:
    return ((q.verification or {}).get("provenance") or {}).get("explanation") or ""


def question_state(session: Session, q: Question) -> dict:
    options = sorted(
        session.scalars(select(QuestionOption).where(QuestionOption.question_id == q.question_id)),
        key=lambda o: o.option_key,
    )
    return {
        "stem": q.stem,
        "active": q.active,
        "expected_answer": q.expected_answer,
        "explanation": explanation_of(q),
        "options": {
            o.option_key: {"text": o.option_text, "is_correct": bool(o.is_correct)} for o in options
        },
    }


def apply_fix(state: dict, fix: dict, item_type: str) -> dict:
    after = copy.deepcopy(state)
    if "stem_replace" in fix:
        old, new = fix["stem_replace"]
        if old not in after["stem"]:
            raise PatchConflict(f"stem text not found: {old[:50]}")
        after["stem"] = after["stem"].replace(old, new)
    if "text_replace" in fix:
        old, new = fix["text_replace"]
        hits = old in after["stem"] or any(old in o["text"] for o in after["options"].values())
        if not hits:
            raise PatchConflict(f"text not found: {old[:50]}")
        after["stem"] = after["stem"].replace(old, new)
        for o in after["options"].values():
            o["text"] = o["text"].replace(old, new)
    for key, text in fix.get("option_text", {}).items():
        if key not in after["options"]:
            raise PatchConflict(f"no option {key}")
        after["options"][key]["text"] = text
    if "set_correct" in fix:
        for key, o in after["options"].items():
            o["is_correct"] = key in fix["set_correct"]
    if "true_false_value" in fix:
        value = fix["true_false_value"]
        after["expected_answer"] = {**(after["expected_answer"] or {}), "value": value}
        for o in after["options"].values():
            o["is_correct"] = (o["text"].strip().casefold() == "true") is value
    if "explanation" in fix:
        after["explanation"] = fix["explanation"]
    if "explanation_replace" in fix:
        old, new = fix["explanation_replace"]
        if old not in after["explanation"]:
            raise PatchConflict(f"explanation text not found: {old[:50]}")
        after["explanation"] = after["explanation"].replace(old, new)
    correct = sum(o["is_correct"] for o in after["options"].values())
    if item_type in ("single_choice", "true_false") and correct != 1:
        raise PatchConflict(f"fix leaves {correct} correct options on a single-answer item")
    if item_type == "multiple_select" and correct < 1:
        raise PatchConflict("fix leaves no correct option")
    return after


def build(session: Session, additions: list[dict]) -> dict:
    findings, graph = load_findings()
    by_item = {}
    for f in findings:
        if f["item"] in by_item:
            raise PatchConflict(f"duplicate finding for {f['item']}")
        by_item[f["item"]] = f
    ops, verdicts = [], {}
    for q in session.scalars(select(Question).order_by(Question.question_id)):
        if q.review_status != DEMO:
            raise PatchConflict(
                f"{q.question_id} is not {DEMO}; AI review patches demo content only"
            )
        f = by_item.pop(q.question_id, None)
        state = question_state(session, q)
        if f is None:
            verdicts[q.question_id] = {"verdict": "no_defect_found"}
            continue
        verdict = {"repair": "repaired", "deactivate": "withdrawn", "escalate": "escalated"}[
            f["action"]
        ]
        verdicts[q.question_id] = {
            "verdict": verdict,
            "issue": f["issue"],
            "confidence": f["confidence"],
        }
        if f["action"] == "repair":
            after = apply_fix(state, f["fix"], q.item_type or "")
            ops.append(
                {
                    "op": "update_question",
                    "question_id": q.question_id,
                    "issue": f["issue"],
                    "evidence": f["evidence"],
                    "before": state,
                    "after": after,
                }
            )
        elif f["action"] == "deactivate":
            ops.append(
                {
                    "op": "withdraw_question",
                    "question_id": q.question_id,
                    "issue": f["issue"],
                    "evidence": f["evidence"],
                    "before": {"active": q.active},
                    "after": {"active": False},
                    "suggested_correction": f.get("suggested_correction"),
                }
            )
    if by_item:
        raise PatchConflict(f"findings for unknown items: {sorted(by_item)}")
    for (pre, dep), reason in sorted(graph.REMOVE_EDGES.items()):
        edge = session.get(KcEdge, (pre, dep))
        if edge is None:
            raise PatchConflict(f"edge {pre}->{dep} not found")
        ops.append(
            {
                "op": "remove_edge",
                "prerequisite_kc_id": pre,
                "dependent_kc_id": dep,
                "issue": "indefensible_prerequisite",
                "evidence": reason,
                "before": {
                    "strength": edge.strength,
                    "reason": edge.reason,
                    "review_status": edge.review_status,
                },
            }
        )
    for f in graph.KC_FINDINGS:
        if f["action"] != "repair":
            continue
        kc = session.get(KnowledgeComponent, f["item"])
        before = {k: getattr(kc, k) for k in f["fix"]}
        ops.append(
            {
                "op": "update_kc",
                "kc_id": kc.kc_id,
                "issue": f["issue"],
                "evidence": f["evidence"],
                "before": before,
                "after": dict(f["fix"]),
            }
        )
    for kc in records.outcome_kcs():
        item = session.get(CurriculumItem, kc["item_id"])
        if item is None:
            raise PatchConflict(f"unknown curriculum item {kc['item_id']}")
        ops.append(
            {
                "op": "add_kc",
                "kc": kc,
                "item_status_before": item.status,
                "issue": "verified_objective_gap_fill",
                "evidence": f"official CBSE learning outcome: {kc['outcome']['source_title']} ({kc['outcome']['source_page']})",
            }
        )
    for add in additions:
        ops.append({"op": "add_question", **add})
    escalations = (
        [f for f in findings if f["action"] == "escalate"]
        + [f for f in graph.KC_FINDINGS if f["action"] == "escalate"]
        + [
            {"item": f"{a}->{b}", "action": "escalate", "issue": "weak_prerequisite", "evidence": r}
            for (a, b), r in sorted(graph.ESCALATE_EDGES.items())
        ]
    )
    patch = {
        "patch_id": "content-review-v1",
        "reviewer": REVIEWER,
        "review_type": "ai_reviewed",
        "review_date": REVIEW_DATE,
        "scope": "all questions, knowledge components and prerequisite edges in the demo dataset",
        "statement": "AI review of AI-generated demo content. Not an independent human or academic "
        "review; nothing is approved or published; review_status is unchanged.",
        "verdicts": verdicts,
        "operations": ops,
        "escalations": escalations,
    }
    body = json.dumps({k: v for k, v in patch.items()}, sort_keys=True, default=str)
    patch["sha256"] = hashlib.sha256(body.encode()).hexdigest()
    return patch


# --- apply --------------------------------------------------------------------------------------------


def _check_demo(row, name: str) -> None:
    if row is None:
        raise PatchConflict(f"{name} missing")
    if getattr(row, "review_status", DEMO) != DEMO:
        raise PatchConflict(f"{name} is not {DEMO}; refusing to modify")


def _set_question(session: Session, q: Question, after: dict, ai_review: dict) -> None:
    q.stem = after["stem"]
    q.expected_answer = after["expected_answer"]
    verification = copy.deepcopy(q.verification or {})
    provenance = verification.setdefault("provenance", {})
    provenance["explanation"] = after["explanation"]
    verification["ai_review"] = ai_review
    verification["human_reviewed"] = False
    q.verification = verification
    for o in session.scalars(
        select(QuestionOption).where(QuestionOption.question_id == q.question_id)
    ):
        target = after["options"][o.option_key]
        o.option_text, o.is_correct = target["text"], target["is_correct"]


def apply(session: Session, patch: dict) -> dict:
    stats = {
        "verdicts_recorded": 0,
        "updated": 0,
        "withdrawn": 0,
        "edges_removed": 0,
        "kcs_updated": 0,
        "added": 0,
        "already_applied": 0,
    }
    stamp = {
        "reviewer": REVIEWER,
        "type": "ai_reviewed",
        "date": REVIEW_DATE,
        "patch_id": patch["patch_id"],
        "note": "AI review; not a human review",
    }
    handled = set()
    for op in patch["operations"]:
        kind = op["op"]
        if kind in ("update_question", "withdraw_question"):
            q = session.get(Question, op["question_id"])
            _check_demo(q, op["question_id"])
            review = {**stamp, **patch["verdicts"][op["question_id"]]}
            if kind == "update_question":
                current = question_state(session, q)
                if current == op["after"]:
                    stats["already_applied"] += 1
                elif current != op["before"]:
                    raise PatchConflict(f"{q.question_id} changed since the patch was built")
                else:
                    _set_question(session, q, op["after"], review)
                    stats["updated"] += 1
            else:
                if q.active is False:
                    stats["already_applied"] += 1
                else:
                    q.active = False
                    v = copy.deepcopy(q.verification or {})
                    v["ai_review"] = review
                    v["human_reviewed"] = False
                    q.verification = v
                    stats["withdrawn"] += 1
            handled.add(op["question_id"])
        elif kind == "remove_edge":
            edge = session.get(KcEdge, (op["prerequisite_kc_id"], op["dependent_kc_id"]))
            if edge is None:
                stats["already_applied"] += 1
                continue
            _check_demo(edge, f"edge {op['prerequisite_kc_id']}->{op['dependent_kc_id']}")
            session.delete(edge)
            stats["edges_removed"] += 1
        elif kind == "update_kc":
            kc = session.get(KnowledgeComponent, op["kc_id"])
            _check_demo(kc, op["kc_id"])
            if all(getattr(kc, k) == v for k, v in op["after"].items()):
                stats["already_applied"] += 1
                continue
            if any(getattr(kc, k) != v for k, v in op["before"].items()):
                raise PatchConflict(f"{op['kc_id']} changed since the patch was built")
            for k, v in op["after"].items():
                setattr(kc, k, v)
            stats["kcs_updated"] += 1
        elif kind == "add_kc":
            spec = op["kc"]
            if session.get(KnowledgeComponent, spec["kc_id"]) is not None:
                stats["already_applied"] += 1
                continue
            item = session.get(CurriculumItem, spec["item_id"])
            if item is None or item.status not in ("needs_review", DEMO):
                raise PatchConflict(
                    f"{spec['item_id']} is {getattr(item, 'status', None)}; only unreviewed items are extended"
                )
            session.add(
                KnowledgeComponent(
                    kc_id=spec["kc_id"],
                    subject_id=spec["subject_id"],
                    stable_key=spec["stable_key"],
                    name=spec["name"],
                    description=spec["description"],
                    kc_type=spec["kc_type"],
                    difficulty_tier=spec["difficulty_tier"],
                    review_status=DEMO,
                    content_version="kc-cbse-outcome-v1",
                )
            )
            session.flush()
            session.add(
                KcCurriculumMap(
                    kc_id=spec["kc_id"],
                    item_id=spec["item_id"],
                    mapping_role="primary",
                    review_status=DEMO,
                    created_at=datetime(2026, 11, 1, tzinfo=UTC),
                )
            )
            if item.status == "needs_review":
                item.status = DEMO  # served only in demo mode; never published by this patch
            stats.setdefault("kcs_added", 0)
            stats["kcs_added"] += 1
        elif kind == "add_question":
            if session.get(Question, op["question"]["question_id"]) is not None:
                stats["already_applied"] += 1
                continue
            _add_question(session, op, stamp)
            stats["added"] += 1
        session.flush()
    for qid, verdict in patch["verdicts"].items():
        if qid in handled:
            continue
        q = session.get(Question, qid)
        _check_demo(q, qid)
        v = copy.deepcopy(q.verification or {})
        if v.get("ai_review", {}).get("patch_id") == patch["patch_id"]:
            continue
        v["ai_review"] = {**stamp, **verdict}
        v["human_reviewed"] = False
        q.verification = v
        stats["verdicts_recorded"] += 1
    session.flush()
    return stats


def _add_question(session: Session, op: dict, stamp: dict) -> None:
    spec = op["question"]
    kc = session.get(KnowledgeComponent, spec["kc_id"])
    if kc is None:
        raise PatchConflict(f"unknown KC {spec['kc_id']}")
    session.add(
        Question(
            question_id=spec["question_id"],
            item_type=spec["item_type"],
            stem=spec["stem"],
            expected_answer=spec.get("expected_answer"),
            rubric=None,
            difficulty=spec["difficulty"],
            misconception_map={"targets": spec["misconception"]}
            if spec.get("misconception")
            else None,
            source_refs=[],  # original synthetic content: no textbook citation is claimed
            verification={
                "release": "demo",
                "workflow": DEMO,
                "reviews": [],
                "human_reviewed": False,
                "provenance": {
                    "origin": "ai_authored_synthetic",
                    "authoring_model": REVIEWER,
                    "basis": "knowledge-component objective and general subject knowledge; "
                    "no textbook text used",
                    "language": spec["language"],
                    "class_level": spec["class_level"],
                    "subject_id": spec["subject_id"],
                    "curriculum_item_id": spec["curriculum_item_id"],
                    "explanation": spec["explanation"],
                    "prompt_version": "content-review-v1",
                },
                "ai_review": {**stamp, "verdict": "authored_and_self_checked"},
            },
            review_status=DEMO,
            version=1,
            active=True,
        )
    )
    session.flush()
    for order, o in enumerate(spec["options"], start=1):
        session.add(
            QuestionOption(
                option_id=uuid.uuid5(uuid.NAMESPACE_URL, f"{spec['question_id']}:{o['key']}"),
                question_id=spec["question_id"],
                option_key=o["key"],
                option_text=o["text"],
                is_correct=o["correct"],
                explanation=o["why"],
                display_order=order,
            )
        )
    from decimal import Decimal

    session.add(
        QuestionKc(
            question_id=spec["question_id"],
            kc_id=spec["kc_id"],
            weight=Decimal("1"),
            mapping_role="primary",
            review_status=DEMO,
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m data_pipeline.content_review.patch")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    ap = sub.add_parser("apply")
    ap.add_argument("--database-url", required=True)
    ap.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if not records.available() or (args.cmd == "apply" and not PATCH.exists()):
        print(
            "refused: the private content-review records are not in this checkout", file=sys.stderr
        )
        return 2
    if args.cmd == "build":
        from app.db.session import create_db_engine

        with Session(create_db_engine(read_only=True)) as session:
            patch = build(session, records.additions() + records.outcome_questions())
        PATCH.write_text(
            json.dumps(patch, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8"
        )
        counts = {}
        for op in patch["operations"]:
            counts[op["op"]] = counts.get(op["op"], 0) + 1
        verdicts = {}
        for v in patch["verdicts"].values():
            verdicts[v["verdict"]] = verdicts.get(v["verdict"], 0) + 1
        print(
            json.dumps(
                {
                    "operations": counts,
                    "verdicts": verdicts,
                    "escalations": len(patch["escalations"]),
                    "sha256": patch["sha256"],
                },
                indent=1,
            )
        )
        return 0
    patch = json.loads(PATCH.read_text(encoding="utf-8"))
    engine = create_engine(
        args.database_url, connect_args={"options": "-c search_path=concepttrail,public"}
    )
    with Session(engine) as session:
        stats = apply(session, patch)
        if args.apply:
            session.commit()
            AUDIT_DIR.mkdir(parents=True, exist_ok=True)
            (AUDIT_DIR / f"applied_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json").write_text(
                json.dumps(
                    {
                        "patch_sha256": patch["sha256"],
                        "target": engine.url.render_as_string(hide_password=True),
                        "stats": stats,
                    },
                    indent=1,
                )
            )
        else:
            session.rollback()
    print(json.dumps({"mode": "apply" if args.apply else "dry_run", **stats}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
