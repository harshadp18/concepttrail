"""Bell-Ringer topic analysis and cycles, and the class mastery heatmap.

Algorithms decide; no language model is called here. Every number is read from
`student_kc_state` (provisional BKT estimates) and `attempts`.

Topic analysis (always available, read-only). For each servable topic of the class level:
- denominator: learners actively enrolled in the class;
- learners with evidence: enough scored answers (`MIN_EVIDENCE_FOR_WEAK`) for an estimate;
- affected learners: UNIQUE learners with evidence whose estimate is below the weak cut-off
  (repeated wrong answers by one learner count once);
- not attempted: enrolled learners with no attempt on any question of the topic;
- recent failed attempts and the unique learners behind them, inside the stated window.
A topic is flagged only when the coverage, affected-learner and affected-share thresholds in
`Settings.bell_ringer_*` are all met; the response says which ones failed otherwise.

Root gap: the prerequisite graph is searched backwards from a flagged topic; the prerequisite
on which most affected learners are also weak (ties: the earliest one) becomes the warm-up
target when at least half of them are weak there. Demo graph edges are AI-proposed and the
response labels them.

Warm-up card: the deck's 5-minute format (1 min alone, 3 min in pairs, 1 min class share), a
board question on the target topic, a bridge question on the flagged topic, the answer key
(teacher only) and "watch for": the wrong answer this class chose most often, else the
question's recorded misconception note.

Cycles use the PROPOSED `bell_ringer_cycle` table (`db/proposals/0004_bell_ringer_cycle.py`);
callers must check `Settings.bell_ringer_enabled`. One open cycle per (class, topic): a repeat
request returns the open cycle instead of creating another.
"""

from __future__ import annotations

import math
import uuid
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.content_release import servable_review_statuses
from app.db.models import (
    Attempt,
    ClassEnrollment,
    Classroom,
    KnowledgeComponent,
    Learner,
    Question,
    QuestionKc,
    QuestionOption,
    StudentKcState,
)
from app.db.proposed_models import BELL_RINGER_STATUSES, BellRingerCycle
from app.services import progress_summary
from app.services.attempt_service import is_deliverable
from app.services.graph_runtime import GraphUnavailable, ReleasedGraph, get_runtime_graph

OPEN_STATUSES = ("planned", "in_progress")
TRANSITIONS = {
    "planned": {"in_progress", "completed", "cancelled"},
    "in_progress": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}
STEPS = (
    {
        "minutes": 1,
        "label": "Solve alone",
        "detail": "Everyone answers the board question silently.",
    },
    {"minutes": 3, "label": "Compare in pairs", "detail": "Partners explain their answers."},
    {"minutes": 1, "label": "Class shares", "detail": "Two pairs share; close on the key idea."},
)
BOARD_FRIENDLY = ("single_choice", "true_false", "numeric", "mcq", "mcq_single")


class BellRingerError(ValueError):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass(frozen=True)
class Policy:
    weak_below: float
    min_evidence: int
    min_coverage: float
    min_affected: int
    min_share: float
    window_days: int

    def view(self) -> dict[str, Any]:
        return {
            "weak_below": self.weak_below,
            "min_evidence": self.min_evidence,
            "min_coverage": self.min_coverage,
            "min_affected_learners": self.min_affected,
            "min_affected_share": self.min_share,
            "window_days": self.window_days,
            "provisional": True,
        }


def policy(settings: Settings | None = None, window_days: int | None = None) -> Policy:
    s = settings or get_settings()
    return Policy(
        weak_below=progress_summary.WEAK_BELOW,
        min_evidence=progress_summary.MIN_EVIDENCE_FOR_WEAK,
        min_coverage=s.bell_ringer_min_coverage,
        min_affected=s.bell_ringer_min_affected_learners,
        min_share=s.bell_ringer_min_affected_share,
        window_days=window_days or s.bell_ringer_window_days,
    )


def class_learner_ids(session: Session, classroom_id: uuid.UUID) -> list[uuid.UUID]:
    """Learners with an active enrollment in the class (the denominator everywhere)."""
    return sorted(
        set(
            session.scalars(
                select(ClassEnrollment.learner_id).where(
                    ClassEnrollment.classroom_id == classroom_id,
                    ClassEnrollment.ended_at.is_(None),
                    ClassEnrollment.learner_id.is_not(None),
                )
            )
        )
    )


def _activity(
    session: Session,
    learner_ids: Sequence[uuid.UUID],
    kc_ids: Iterable[str],
    since: datetime | None,
) -> dict[tuple[uuid.UUID, str], tuple[int, int, datetime | None]]:
    """(attempts, correct, last attempt) per (learner, topic), optionally since a time."""
    kcs = list(set(kc_ids))
    if not learner_ids or not kcs:
        return {}
    query = (
        select(
            Attempt.learner_id,
            QuestionKc.kc_id,
            func.count(Attempt.attempt_id),
            func.coalesce(func.sum(case((Attempt.scored_correct.is_(True), 1), else_=0)), 0),
            func.max(Attempt.attempted_at),
        )
        .join(QuestionKc, QuestionKc.question_id == Attempt.question_id)
        .where(
            Attempt.learner_id.in_(list(learner_ids)),
            QuestionKc.kc_id.in_(kcs),
            QuestionKc.review_status.in_(servable_review_statuses()),
        )
        .group_by(Attempt.learner_id, QuestionKc.kc_id)
    )
    if since is not None:
        query = query.where(Attempt.attempted_at >= since)
    return {(lid, kc): (int(n), int(c), last) for lid, kc, n, c, last in session.execute(query)}


def _estimate(state: StudentKcState | None, min_evidence: int) -> float | None:
    """The estimate when it rests on enough evidence, else None (never a zero)."""
    if state is None or state.mastery_probability is None:
        return None
    if (state.evidence_count or 0) < min_evidence:
        return None
    return float(state.mastery_probability)


def _scope(
    session: Session, classroom: Classroom, subject_id: str | None, item_id: str | None = None
) -> list[tuple[str, progress_summary.ChapterKcs]]:
    """(kc_id, chapter) pairs for the class level, in curriculum order, first chapter wins."""
    levels = [int(classroom.grade_level)] if classroom.grade_level is not None else []
    out: list[tuple[str, progress_summary.ChapterKcs]] = []
    seen: set[str] = set()
    for chapter in progress_summary.chapter_kcs(session, levels):
        if subject_id and chapter.subject_id != subject_id:
            continue
        if item_id and chapter.item_id != item_id:
            continue
        for kc_id in chapter.kc_ids:
            if kc_id not in seen:
                seen.add(kc_id)
                out.append((kc_id, chapter))
    return out


def _names(session: Session, kc_ids: Iterable[str]) -> dict[str, str | None]:
    ids = list(set(kc_ids))
    if not ids:
        return {}
    return {
        k.kc_id: k.name
        for k in session.scalars(
            select(KnowledgeComponent).where(KnowledgeComponent.kc_id.in_(ids))
        )
    }


def analyse_topics(
    session: Session,
    classroom: Classroom,
    *,
    subject_id: str | None = None,
    window_days: int | None = None,
    now: datetime | None = None,
    with_cards: bool = True,
) -> dict[str, Any]:
    pol = policy(window_days=window_days)
    now = now or datetime.now(UTC)
    since = now - timedelta(days=pol.window_days)
    learners = class_learner_ids(session, classroom.classroom_id)
    scope = _scope(session, classroom, subject_id)
    kc_ids = [k for k, _ in scope]
    states = progress_summary.mastery_by_kc(session, learners)
    ever = _activity(session, learners, kc_ids, None)
    recent = _activity(session, learners, kc_ids, since)
    graph = get_runtime_graph(session)
    names = _names(session, kc_ids)
    rows: list[dict[str, Any]] = []
    for kc_id, chapter in scope:
        estimates = {
            lid: v
            for lid in learners
            if (v := _estimate(states.get(lid, {}).get(kc_id), pol.min_evidence)) is not None
        }
        affected = sorted((lid for lid, v in estimates.items() if v < pol.weak_below), key=str)
        attempted = {lid for lid in learners if (lid, kc_id) in ever}
        recent_rows = [recent[(lid, kc_id)] for lid in learners if (lid, kc_id) in recent]
        coverage = len(estimates) / len(learners) if learners else 0.0
        share = len(affected) / len(estimates) if estimates else None
        unmet = []
        if coverage < pol.min_coverage:
            unmet.append("coverage_below_minimum")
        if len(affected) < pol.min_affected:
            unmet.append("too_few_affected_learners")
        if share is None or share < pol.min_share:
            unmet.append("affected_share_below_minimum")
        flagged = not unmet
        rows.append(
            {
                "kc_id": kc_id,
                "name": names.get(kc_id),
                "subject_id": chapter.subject_id,
                "item_id": chapter.item_id,
                "item_title": chapter.title,
                "enrolled_learners": len(learners),
                "learners_with_evidence": len(estimates),
                "learners_below_threshold": len(affected),
                "learners_not_attempted": len(learners) - len(attempted),
                "coverage": round(coverage, 4),
                "affected_share": round(share, 4) if share is not None else None,
                "average_mastery_probability": (
                    round(sum(estimates.values()) / len(estimates), 4) if estimates else None
                ),
                "recent_attempts": sum(r[0] for r in recent_rows),
                "recent_failed_attempts": sum(r[0] - r[1] for r in recent_rows),
                "recent_learners_with_failed_attempts": sum(1 for r in recent_rows if r[0] > r[1]),
                "flagged": flagged,
                "severity": (("high" if (share or 0) >= 0.6 else "medium") if flagged else None),
                "unmet_criteria": unmet,
                "_affected": affected,
            }
        )
    flagged_rows = sorted(
        (r for r in rows if r["flagged"]),
        key=lambda r: (
            -(r["affected_share"] or 0),
            -r["learners_below_threshold"],
            r["average_mastery_probability"] if r["average_mastery_probability"] is not None else 1,
            r["kc_id"],
        ),
    )
    rank = {r["kc_id"]: i for i, r in enumerate(flagged_rows, start=1)}
    for row in rows:
        affected = row.pop("_affected")
        row["rank"] = rank.get(row["kc_id"])
        if row["flagged"] and with_cards:
            gap = root_gap(session, graph, row["kc_id"], affected, states, pol)
            row["root_gap"] = gap
            row["activity"] = warm_up_card(session, gap["target_kc_id"], row["kc_id"], learners)
    rows.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0, r["kc_id"]))
    return {
        "classroom_id": str(classroom.classroom_id),
        "grade_level": classroom.grade_level,
        "subject_id": subject_id,
        "enrolled_learners": len(learners),
        "window": {"days": pol.window_days, "since": since.isoformat(), "until": now.isoformat()},
        "criteria": pol.view(),
        "flagged_count": len(flagged_rows),
        "topics": rows,
        "note": (
            "Learner counts are unique learners; repeated attempts by one learner count once. "
            "Mastery is a provisional estimate, not a grade. " + progress_summary.PROGRESS_NOTE
        ),
    }


def root_gap(
    session: Session,
    graph: ReleasedGraph | GraphUnavailable,
    kc_id: str,
    affected: Sequence[uuid.UUID],
    states: dict[uuid.UUID, dict[str, StudentKcState]],
    pol: Policy,
) -> dict[str, Any]:
    names = _names(session, [kc_id])
    own = {
        "target_kc_id": kc_id,
        "target_name": names.get(kc_id),
        "is_prerequisite": False,
    }
    if isinstance(graph, GraphUnavailable) or kc_id not in graph.kcs:
        return {
            **own,
            "graph_available": False,
            "reason": graph.reason if isinstance(graph, GraphUnavailable) else "kc_not_in_graph",
            "explanation": (
                "No prerequisite graph covers this topic; the warm-up targets it directly."
            ),
            "candidates": [],
        }
    prereqs = graph.graph.prerequisites(kc_id)  # nearest first
    pnames = _names(session, prereqs)
    candidates = []
    for depth_rank, p in enumerate(prereqs):
        weak = 0
        unknown = 0
        for lid in affected:
            v = _estimate(states.get(lid, {}).get(p), pol.min_evidence)
            if v is None:
                unknown += 1
            elif v < pol.weak_below:
                weak += 1
        candidates.append(
            {
                "kc_id": p,
                "name": pnames.get(p),
                "affected_learners_weak": weak,
                "affected_learners_without_evidence": unknown,
                "_order": depth_rank,
            }
        )
    needed = max(1, math.ceil(len(affected) / 2))
    best = max(
        (c for c in candidates if c["affected_learners_weak"] >= needed),
        key=lambda c: (c["affected_learners_weak"], c["_order"]),
        default=None,
    )
    for c in candidates:
        c.pop("_order")
    base = {
        "graph_available": True,
        "graph_version": graph.version,
        "edge_provenance": "ai_proposed_demo" if graph.kind == "demo" else "released_snapshot",
        "candidates": candidates[:10],
    }
    if not prereqs:
        return {
            **own,
            **base,
            "explanation": (
                "No earlier topic is linked to this one, so the warm-up targets it directly."
            ),
        }
    if best is None:
        return {
            **own,
            **base,
            "explanation": (
                f"None of the {len(prereqs)} earlier topic(s) linked to this one is weak for at "
                f"least {needed} of the {len(affected)} affected learners, so the warm-up "
                "targets this topic directly."
            ),
        }
    return {
        **base,
        "target_kc_id": best["kc_id"],
        "target_name": best["name"],
        "is_prerequisite": True,
        "explanation": (
            f"{best['affected_learners_weak']} of the {len(affected)} affected learners "
            f"{'is' if best['affected_learners_weak'] == 1 else 'are'} also below "
            f"{pol.weak_below:.0%} on this prerequisite, so the gap likely starts there."
        ),
    }


def _question_view(session: Session, question: Question) -> dict[str, Any]:
    options = list(
        session.scalars(
            select(QuestionOption)
            .where(QuestionOption.question_id == question.question_id)
            .order_by(QuestionOption.display_order, QuestionOption.option_key)
        )
    )
    misconception = (
        question.misconception_map.get("targets")
        if isinstance(question.misconception_map, dict)
        else None
    )
    return {
        "question_id": question.question_id,
        "item_type": question.item_type,
        "stem": question.stem,
        "difficulty": question.difficulty,
        "options": [
            {
                "option_key": o.option_key,
                "option_text": o.option_text,
                "is_correct": o.is_correct is True,
            }
            for o in options
        ],
        "expected_answer": question.expected_answer,
        "recorded_misconception": misconception,
        "review_status": question.review_status,
    }


def _questions_for(session: Session, kc_id: str) -> list[Question]:
    questions = session.scalars(
        select(Question)
        .join(QuestionKc, QuestionKc.question_id == Question.question_id)
        .where(
            QuestionKc.kc_id == kc_id,
            QuestionKc.review_status.in_(servable_review_statuses()),
            Question.review_status.in_(servable_review_statuses()),
            Question.active.is_(True),
        )
        .order_by(Question.difficulty, Question.question_id)
    ).all()
    out = []
    for q in questions:
        options = list(
            session.scalars(
                select(QuestionOption).where(QuestionOption.question_id == q.question_id)
            )
        )
        if is_deliverable(q, options):
            out.append(q)
    # board-friendly formats first, then easier first (stable order)
    return sorted(out, key=lambda q: (q.item_type not in BOARD_FRIENDLY,))


def _watch_for(
    session: Session, question_id: str, learner_ids: Sequence[uuid.UUID]
) -> dict[str, Any] | None:
    if not learner_ids:
        return None
    answers = session.scalars(
        select(Attempt.submitted_answer).where(
            Attempt.question_id == question_id,
            Attempt.learner_id.in_(list(learner_ids)),
            Attempt.scored_correct.is_(False),
        )
    ).all()
    keys = Counter(
        a.get("option_key") for a in answers if isinstance(a, dict) and a.get("option_key")
    )
    if not keys:
        return None
    key, count = sorted(keys.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    option = session.scalar(
        select(QuestionOption).where(
            QuestionOption.question_id == question_id, QuestionOption.option_key == key
        )
    )
    return {
        "source": "class_attempts",
        "option_key": key,
        "option_text": option.option_text if option else None,
        "wrong_attempts": count,
    }


def warm_up_card(
    session: Session, target_kc_id: str, topic_kc_id: str, learner_ids: Sequence[uuid.UUID]
) -> dict[str, Any]:
    target_qs = _questions_for(session, target_kc_id)
    topic_qs = target_qs if target_kc_id == topic_kc_id else _questions_for(session, topic_kc_id)
    board = target_qs[0] if target_qs else None
    bridge = next(
        (q for q in topic_qs if board is None or q.question_id != board.question_id), None
    )
    watch: dict[str, Any] | None = None
    if board is not None:
        watch = _watch_for(session, board.question_id, learner_ids)
        if watch is None and isinstance(board.misconception_map, dict):
            note = board.misconception_map.get("targets")
            if note:
                watch = {"source": "recorded_misconception", "text": note}
    return {
        "format": "5-minute warm-up",
        "total_minutes": sum(s["minutes"] for s in STEPS),
        "steps": list(STEPS),
        "board_question": _question_view(session, board) if board else None,
        "bridge_question": _question_view(session, bridge) if bridge else None,
        "watch_for": watch,
        "available_questions": {"target": len(target_qs), "topic": len(topic_qs)},
        "generated_by": "deterministic template from stored questions; no language model",
    }


# --- cycles (PROPOSED table) ------------------------------------------------------------------


def _cycle_view(row: BellRingerCycle, names: dict[str, str | None]) -> dict[str, Any]:
    baseline = row.baseline or {}
    return {
        "cycle_id": str(row.cycle_id),
        "classroom_id": str(row.classroom_id),
        "kc_id": row.kc_id,
        "topic_name": names.get(row.kc_id),
        "root_kc_id": row.root_kc_id,
        "root_name": names.get(row.root_kc_id) if row.root_kc_id else None,
        "subject_id": baseline.get("subject_id"),
        "item_title": baseline.get("item_title"),
        "status": row.status,
        "board_question_id": row.board_question_id,
        "bridge_question_id": row.bridge_question_id,
        "teacher_note": row.teacher_note,
        "baseline": {k: v for k, v in baseline.items() if k != "affected"},
        "affected_count": len(baseline.get("affected", [])),
        "created_by": str(row.created_by),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "started_at": _iso(row.started_at),
        "completed_at": _iso(row.completed_at),
    }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def list_cycles(
    session: Session, classroom_id: uuid.UUID, status: str | None = None
) -> list[dict[str, Any]]:
    query = select(BellRingerCycle).where(BellRingerCycle.classroom_id == classroom_id)
    if status is not None:
        query = query.where(BellRingerCycle.status == status)
    rows = list(
        session.scalars(query.order_by(BellRingerCycle.created_at.desc(), BellRingerCycle.cycle_id))
    )
    names = _names(session, [r.kc_id for r in rows] + [r.root_kc_id for r in rows if r.root_kc_id])
    return [_cycle_view(r, names) for r in rows]


def _open_cycle(session: Session, classroom_id: uuid.UUID, kc_id: str) -> BellRingerCycle | None:
    return session.scalar(
        select(BellRingerCycle).where(
            BellRingerCycle.classroom_id == classroom_id,
            BellRingerCycle.kc_id == kc_id,
            BellRingerCycle.status.in_(OPEN_STATUSES),
        )
    )


def open_cycle(
    session: Session,
    classroom: Classroom,
    teacher_id: uuid.UUID,
    kc_id: str,
    note: str | None = None,
    window_days: int | None = None,
) -> tuple[dict[str, Any], bool]:
    """Create the topic's cycle, or return the open one. Returns (view, created)."""
    existing = _open_cycle(session, classroom.classroom_id, kc_id)
    if existing is not None:
        return cycle_detail(session, existing), False
    analysis = analyse_topics(session, classroom, window_days=window_days)
    row_data = next((t for t in analysis["topics"] if t["kc_id"] == kc_id), None)
    if row_data is None:
        raise BellRingerError("topic_not_found", "The topic is not part of this class.", 404)
    learners = class_learner_ids(session, classroom.classroom_id)
    pol = policy(window_days=window_days)
    states = progress_summary.mastery_by_kc(session, learners)
    affected = [
        {"learner_id": str(lid), "mastery_probability": round(v, 4)}
        for lid in learners
        if (v := _estimate(states.get(lid, {}).get(kc_id), pol.min_evidence)) is not None
        and v < pol.weak_below
    ]
    if "root_gap" in row_data:
        gap, card = row_data["root_gap"], row_data["activity"]
    else:  # a teacher may plan for a topic that is not flagged; record that it was not
        gap = root_gap(
            session,
            get_runtime_graph(session),
            kc_id,
            [uuid.UUID(a["learner_id"]) for a in affected],
            states,
            pol,
        )
        card = warm_up_card(session, gap["target_kc_id"], kc_id, learners)
    baseline = {
        "captured_at": datetime.now(UTC).isoformat(),
        "window": analysis["window"],
        "criteria": analysis["criteria"],
        "flagged_at_creation": row_data["flagged"],
        "subject_id": row_data["subject_id"],
        "item_title": row_data["item_title"],
        **{
            k: row_data[k]
            for k in (
                "enrolled_learners",
                "learners_with_evidence",
                "learners_below_threshold",
                "learners_not_attempted",
                "coverage",
                "affected_share",
                "average_mastery_probability",
                "recent_failed_attempts",
                "recent_learners_with_failed_attempts",
            )
        },
        "root_gap_explanation": gap.get("explanation"),
        "edge_provenance": gap.get("edge_provenance"),
        "affected": affected,
    }
    row = BellRingerCycle(
        cycle_id=uuid.uuid4(),
        classroom_id=classroom.classroom_id,
        kc_id=kc_id,
        root_kc_id=gap["target_kc_id"] if gap.get("is_prerequisite") else None,
        created_by=teacher_id,
        status="planned",
        board_question_id=(card["board_question"] or {}).get("question_id"),
        bridge_question_id=(card["bridge_question"] or {}).get("question_id"),
        teacher_note=(note or "").strip() or None,
        baseline=baseline,
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:  # a concurrent request opened the same topic first
        existing = _open_cycle(session, classroom.classroom_id, kc_id)
        if existing is None:
            raise
        return cycle_detail(session, existing), False
    return cycle_detail(session, row), True


def get_cycle(session: Session, classroom_id: uuid.UUID, cycle_id: uuid.UUID) -> BellRingerCycle:
    row = session.get(BellRingerCycle, cycle_id)
    if row is None or row.classroom_id != classroom_id:
        raise BellRingerError("cycle_not_found", "The Bell-Ringer cycle is unavailable.", 404)
    return row


def update_status(
    session: Session, classroom_id: uuid.UUID, cycle_id: uuid.UUID, status: str
) -> BellRingerCycle:
    if status not in BELL_RINGER_STATUSES:
        raise BellRingerError("invalid_status", "Unknown status.")
    row = get_cycle(session, classroom_id, cycle_id)
    if status not in TRANSITIONS[row.status]:
        raise BellRingerError(
            "invalid_transition", f"Cannot move from {row.status} to {status}.", 409
        )
    now = datetime.now(UTC)
    row.status, row.updated_at = status, now
    if status == "in_progress":
        row.started_at = now
    if status == "completed":
        row.completed_at = now
    session.flush()
    return row


def cycle_detail(session: Session, row: BellRingerCycle) -> dict[str, Any]:
    """The cycle with its card and a follow-up computed from persisted state now."""
    names = _names(session, [row.kc_id] + ([row.root_kc_id] if row.root_kc_id else []))
    view = _cycle_view(row, names)
    learners = class_learner_ids(session, row.classroom_id)
    view["activity"] = warm_up_card(session, row.root_kc_id or row.kc_id, row.kc_id, learners)
    view["follow_up"] = follow_up(session, row)
    return view


def follow_up(session: Session, row: BellRingerCycle) -> dict[str, Any]:
    """How the learners affected at creation are doing now (unique learners, same cut-off)."""
    baseline = row.baseline or {}
    affected = baseline.get("affected", [])
    ids = [uuid.UUID(a["learner_id"]) for a in affected]
    enrolled = set(class_learner_ids(session, row.classroom_id))
    ids = [i for i in ids if i in enrolled]
    pol = policy()
    states = progress_summary.mastery_by_kc(session, ids)
    since = row.started_at or row.created_at
    kcs = [row.kc_id] + ([row.root_kc_id] if row.root_kc_id else [])
    activity = _activity(session, ids, kcs, since)
    names = (
        {
            lr.learner_id: lr.display_name
            for lr in session.scalars(select(Learner).where(Learner.learner_id.in_(ids)))
        }
        if ids
        else {}
    )
    before = {a["learner_id"]: a["mastery_probability"] for a in affected}
    learners_view = []
    improved = 0
    for lid in sorted(ids, key=lambda i: (names.get(i) or "", str(i))):
        now_v = _estimate(states.get(lid, {}).get(row.kc_id), pol.min_evidence)
        recovered = now_v is not None and now_v >= pol.weak_below
        improved += recovered
        n = sum(activity.get((lid, k), (0, 0, None))[0] for k in kcs)
        c = sum(activity.get((lid, k), (0, 0, None))[1] for k in kcs)
        learners_view.append(
            {
                "learner_id": str(lid),
                "display_name": names.get(lid),
                "mastery_at_start": before.get(str(lid)),
                "mastery_now": round(now_v, 4) if now_v is not None else None,
                "now_at_or_above_cut_off": recovered,
                "attempts_since_start": n,
                "correct_since_start": c,
            }
        )
    return {
        "since": _iso(since),
        "affected_at_start": len(affected),
        "still_enrolled": len(ids),
        "now_at_or_above_cut_off": improved,
        "practised_since_start": sum(1 for v in learners_view if v["attempts_since_start"]),
        "weak_below": pol.weak_below,
        "learners": learners_view,
        "note": "Re-check uses the same provisional cut-off; a change is an estimate, not a grade.",
    }


# --- heatmap -----------------------------------------------------------------------------------


def _band(estimate: float | None, has_any: bool) -> str:
    if estimate is None:
        return "insufficient_evidence" if has_any else "no_data"
    if estimate >= progress_summary.MASTERED_AT:
        return "mastered"
    if estimate >= progress_summary.WEAK_BELOW:
        return "developing"
    return "needs_practice"


def class_heatmap(
    session: Session,
    classroom: Classroom,
    *,
    subject_id: str | None = None,
    item_id: str | None = None,
    window_days: int | None = None,
    max_topics: int = 80,
) -> dict[str, Any]:
    """Learners x topics. Cells carry the estimate (or null), evidence and attempt counts."""
    learners = class_learner_ids(session, classroom.classroom_id)
    scope = _scope(session, classroom, subject_id, item_id)
    truncated = len(scope) > max_topics
    scope = scope[:max_topics]
    kc_ids = [k for k, _ in scope]
    names = _names(session, kc_ids)
    states = progress_summary.mastery_by_kc(session, learners)
    since = datetime.now(UTC) - timedelta(days=window_days) if window_days else None
    activity = _activity(session, learners, kc_ids, since)
    ever = activity if since is None else _activity(session, learners, kc_ids, None)
    people = (
        sorted(
            session.scalars(select(Learner).where(Learner.learner_id.in_(learners))).all(),
            key=lambda lr: (lr.display_name or "", str(lr.learner_id)),
        )
        if learners
        else []
    )
    min_ev = progress_summary.MIN_EVIDENCE_FOR_WEAK
    rows = []
    column: dict[str, list[float]] = {k: [] for k in kc_ids}
    column_weak: Counter[str] = Counter()
    for person in people:
        cells = []
        own: list[float] = []
        for kc_id in kc_ids:
            state = states.get(person.learner_id, {}).get(kc_id)
            est = _estimate(state, min_ev)
            n, c, last = activity.get((person.learner_id, kc_id), (0, 0, None))
            has_any = state is not None or (person.learner_id, kc_id) in ever
            band = _band(est, has_any)
            if est is not None:
                own.append(est)
                column[kc_id].append(est)
                column_weak[kc_id] += band == "needs_practice"
            cells.append(
                {
                    "mastery_probability": round(est, 4) if est is not None else None,
                    "evidence_count": (state.evidence_count or 0) if state else 0,
                    "attempts": n,
                    "correct": c,
                    "last_attempt_at": _iso(last),
                    "band": band,
                }
            )
        rows.append(
            {
                "learner_id": str(person.learner_id),
                "display_name": person.display_name,
                "topics_with_estimate": len(own),
                "average_mastery_probability": round(sum(own) / len(own), 4) if own else None,
                "cells": cells,
            }
        )
    topics = [
        {
            "kc_id": kc_id,
            "name": names.get(kc_id),
            "subject_id": chapter.subject_id,
            "item_id": chapter.item_id,
            "item_title": chapter.title,
            "learners_with_estimate": len(column[kc_id]),
            "learners_needing_practice": column_weak[kc_id],
            "average_mastery_probability": (
                round(sum(column[kc_id]) / len(column[kc_id]), 4) if column[kc_id] else None
            ),
        }
        for kc_id, chapter in scope
    ]
    return {
        "classroom_id": str(classroom.classroom_id),
        "grade_level": classroom.grade_level,
        "subject_id": subject_id,
        "item_id": item_id,
        "window_days": window_days,
        "learner_count": len(people),
        "topics": topics,
        "learners": rows,
        "truncated": truncated,
        "bands": {
            "mastered": {"at_or_above": progress_summary.MASTERED_AT},
            "developing": {"at_or_above": progress_summary.WEAK_BELOW},
            "needs_practice": {"below": progress_summary.WEAK_BELOW},
            "insufficient_evidence": {"evidence_below": min_ev},
            "no_data": {},
        },
        "thresholds_provisional": True,
        "note": (
            "Cells show the current provisional mastery estimate; the window only limits the "
            "attempt counts. No data is shown as no data, never as zero. "
            + progress_summary.PROGRESS_NOTE
        ),
    }
