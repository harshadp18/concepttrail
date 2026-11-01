"""Chapter, subject and weak-area progress, derived only from persisted state and attempts.

Every number here is read from `student_kc_state` (BKT estimates) and `attempts`; nothing is
generated or estimated by a language model. Mastery values are provisional model estimates
(`bkt-provisional-v1`), so the "mastered" and "weak" cut-offs are the provisional adaptive
thresholds and are reported with that label.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.content_release import servable_curriculum_statuses, servable_review_statuses
from app.db.models import (
    Attempt,
    CurriculumItem,
    CurriculumVersion,
    KcCurriculumMap,
    KnowledgeComponent,
    Question,
    QuestionKc,
    StudentKcState,
    Subject,
)
from app.services import learner_scope
from app.services.adaptive import DEFAULT_THRESHOLDS

MASTERED_AT = DEFAULT_THRESHOLDS.mastery_target
WEAK_BELOW = 0.5
MIN_EVIDENCE_FOR_WEAK = 2  # one wrong answer is not a weakness
PROGRESS_NOTE = (
    "Mastery values are provisional model estimates (bkt-provisional-v1, not calibrated on real "
    "learners). They are not grades."
)


@dataclass(frozen=True)
class ChapterKcs:
    item_id: str
    title: str | None
    subject_id: str | None
    class_level: int
    sequence_label: str | None
    kc_ids: tuple[str, ...]


def chapter_kcs(session: Session, class_levels: Iterable[int]) -> list[ChapterKcs]:
    """Servable curriculum items of the given class levels with their servable KCs."""
    levels = sorted(set(class_levels))
    if not levels:
        return []
    rows = session.execute(
        select(
            CurriculumItem.item_id,
            CurriculumItem.title,
            CurriculumItem.subject_id,
            CurriculumItem.sequence_label,
            CurriculumVersion.class_level,
            KcCurriculumMap.kc_id,
        )
        .join(
            CurriculumVersion,
            CurriculumVersion.curriculum_version_id == CurriculumItem.curriculum_version_id,
        )
        .join(KcCurriculumMap, KcCurriculumMap.item_id == CurriculumItem.item_id)
        .join(KnowledgeComponent, KnowledgeComponent.kc_id == KcCurriculumMap.kc_id)
        .where(
            CurriculumVersion.class_level.in_(levels),
            CurriculumVersion.status.in_(servable_curriculum_statuses()),
            CurriculumItem.status.in_(servable_curriculum_statuses()),
            KcCurriculumMap.review_status.in_(servable_review_statuses()),
            KnowledgeComponent.review_status.in_(servable_review_statuses()),
        )
        .order_by(CurriculumItem.item_id, KcCurriculumMap.kc_id)
    ).all()
    grouped: dict[str, dict[str, Any]] = {}
    for item_id, title, subject_id, label, level, kc_id in rows:
        entry = grouped.setdefault(
            item_id,
            {"title": title, "subject": subject_id, "label": label, "level": level, "kcs": []},
        )
        if kc_id not in entry["kcs"]:
            entry["kcs"].append(kc_id)
    return [
        ChapterKcs(item_id, e["title"], e["subject"], int(e["level"]), e["label"], tuple(e["kcs"]))
        for item_id, e in sorted(
            grouped.items(),
            key=lambda kv: (kv[1]["level"], kv[1]["subject"] or "", kv[1]["label"] or "", kv[0]),
        )
    ]


def mastery_by_kc(
    session: Session, learner_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, dict[str, StudentKcState]]:
    out: dict[uuid.UUID, dict[str, StudentKcState]] = defaultdict(dict)
    if not learner_ids:
        return out
    for state in session.scalars(
        select(StudentKcState).where(StudentKcState.learner_id.in_(list(learner_ids)))
    ):
        out[state.learner_id][state.kc_id] = state
    return out


def attempts_by_kc(
    session: Session, learner_ids: Sequence[uuid.UUID], kc_ids: Iterable[str]
) -> dict[str, tuple[int, int]]:
    """(attempts, correct) per KC over single- and multi-KC questions mapped to the KC.

    This is an activity count for display, not the evidence BKT uses (BKT only uses
    single-KC questions).
    """
    kcs = list(set(kc_ids))
    if not learner_ids or not kcs:
        return {}
    rows = session.execute(
        select(
            QuestionKc.kc_id,
            func.count(Attempt.attempt_id),
            func.coalesce(func.sum(case((Attempt.scored_correct.is_(True), 1), else_=0)), 0),
        )
        .join(Attempt, Attempt.question_id == QuestionKc.question_id)
        .where(
            Attempt.learner_id.in_(list(learner_ids)),
            QuestionKc.kc_id.in_(kcs),
            QuestionKc.review_status.in_(servable_review_statuses()),
        )
        .group_by(QuestionKc.kc_id)
    ).all()
    return {kc: (int(n), int(c)) for kc, n, c in rows}


def _chapter_row(
    chapter: ChapterKcs,
    states: dict[str, StudentKcState],
    attempts: dict[str, tuple[int, int]],
    names: dict[str, str | None],
) -> dict[str, Any]:
    values = [
        float(states[k].mastery_probability)
        for k in chapter.kc_ids
        if k in states and states[k].mastery_probability is not None
    ]
    n_attempts = sum(attempts.get(k, (0, 0))[0] for k in chapter.kc_ids)
    n_correct = sum(attempts.get(k, (0, 0))[1] for k in chapter.kc_ids)
    return {
        "item_id": chapter.item_id,
        "title": chapter.title,
        "subject_id": chapter.subject_id,
        "class_level": chapter.class_level,
        "topics_total": len(chapter.kc_ids),
        "topics_started": len(values),
        "topics_mastered": sum(v >= MASTERED_AT for v in values),
        "average_mastery_probability": round(sum(values) / len(values), 4) if values else None,
        "attempts": n_attempts,
        "correct_attempts": n_correct,
        "accuracy": round(n_correct / n_attempts, 4) if n_attempts else None,
        "topics": [
            {
                "kc_id": k,
                "name": names.get(k),
                "mastery_probability": (
                    float(states[k].mastery_probability)
                    if k in states and states[k].mastery_probability is not None
                    else None
                ),
                "evidence_count": (states[k].evidence_count or 0) if k in states else 0,
            }
            for k in chapter.kc_ids
        ],
    }


def learner_chapter_progress(
    session: Session, learner_id: uuid.UUID, class_levels: Iterable[int]
) -> dict[str, Any]:
    """Chapter rows and subject roll-ups for one learner over the given class levels."""
    chapters = chapter_kcs(session, class_levels)
    kc_ids = {k for c in chapters for k in c.kc_ids}
    allowed = learner_scope.accessible_kcs(
        session, learner_scope.LearnerAccess(learner_id, tuple(sorted(set(class_levels)))), kc_ids
    )
    chapters = [
        ChapterKcs(
            c.item_id,
            c.title,
            c.subject_id,
            c.class_level,
            c.sequence_label,
            tuple(k for k in c.kc_ids if k in allowed),
        )
        for c in chapters
    ]
    chapters = [c for c in chapters if c.kc_ids]
    states = mastery_by_kc(session, [learner_id]).get(learner_id, {})
    attempts = attempts_by_kc(session, [learner_id], {k for c in chapters for k in c.kc_ids})
    names = {
        k.kc_id: k.name
        for k in session.scalars(
            select(KnowledgeComponent).where(
                KnowledgeComponent.kc_id.in_({k for c in chapters for k in c.kc_ids})
            )
        )
    }
    rows = [_chapter_row(c, states, attempts, names) for c in chapters]
    subjects = {
        s.subject_id: s.display_name
        for s in session.scalars(select(Subject).where(Subject.active.is_(True)))
    }
    by_subject: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["subject_id"] in subjects:
            by_subject[row["subject_id"]].append(row)
    subject_rows = []
    for sid, chs in sorted(by_subject.items()):
        values = [c["average_mastery_probability"] for c in chs if c["topics_started"]]
        weights = [c["topics_started"] for c in chs if c["topics_started"]]
        subject_rows.append(
            {
                "subject_id": sid,
                "display_name": subjects[sid],
                "chapters_total": len(chs),
                "chapters_started": sum(1 for c in chs if c["topics_started"]),
                "topics_total": sum(c["topics_total"] for c in chs),
                "topics_started": sum(c["topics_started"] for c in chs),
                "topics_mastered": sum(c["topics_mastered"] for c in chs),
                "average_mastery_probability": (
                    round(
                        sum(v * w for v, w in zip(values, weights, strict=True)) / sum(weights), 4
                    )
                    if values
                    else None
                ),
                "attempts": sum(c["attempts"] for c in chs),
                "correct_attempts": sum(c["correct_attempts"] for c in chs),
            }
        )
    return {
        "mastered_threshold": MASTERED_AT,
        "thresholds_provisional": True,
        "subjects": subject_rows,
        "chapters": rows,
        "note": PROGRESS_NOTE,
    }


def weak_areas(
    session: Session, learner_id: uuid.UUID, kc_ids: Iterable[str] | None = None, limit: int = 10
) -> list[dict[str, Any]]:
    """KCs with enough evidence and a low estimate, weakest first (deterministic order)."""
    states = mastery_by_kc(session, [learner_id]).get(learner_id, {})
    allowed = set(kc_ids) if kc_ids is not None else None
    weak = [
        s
        for s in states.values()
        if s.mastery_probability is not None
        and float(s.mastery_probability) < WEAK_BELOW
        and (s.evidence_count or 0) >= MIN_EVIDENCE_FOR_WEAK
        and (allowed is None or s.kc_id in allowed)
    ]
    weak.sort(key=lambda s: (float(s.mastery_probability), s.kc_id))
    weak = weak[:limit]
    names = {
        k.kc_id: k.name
        for k in session.scalars(
            select(KnowledgeComponent).where(KnowledgeComponent.kc_id.in_([s.kc_id for s in weak]))
        )
    }
    return [
        {
            "kc_id": s.kc_id,
            "name": names.get(s.kc_id),
            "mastery_probability": float(s.mastery_probability),
            "evidence_count": s.evidence_count or 0,
            "reason": (
                f"Estimated mastery {float(s.mastery_probability):.2f} is below {WEAK_BELOW} "
                f"after {s.evidence_count or 0} scored answers."
            ),
        }
        for s in weak
    ]


def recent_activity(
    session: Session, learner_id: uuid.UUID, *, limit: int, offset: int
) -> dict[str, Any]:
    """The learner's own attempts, newest first. Never includes answer keys."""
    total = session.scalar(
        select(func.count(Attempt.attempt_id)).where(Attempt.learner_id == learner_id)
    )
    rows = session.execute(
        select(Attempt, Question.stem, Question.item_type)
        .join(Question, Question.question_id == Attempt.question_id)
        .where(Attempt.learner_id == learner_id)
        .order_by(Attempt.attempted_at.desc(), Attempt.attempt_id)
        .limit(limit)
        .offset(offset)
    ).all()
    return {
        "count": int(total or 0),
        "limit": limit,
        "offset": offset,
        "attempts": [
            {
                "attempt_id": str(a.attempt_id),
                "question_id": a.question_id,
                "question_stem": stem,
                "item_type": item_type,
                "scored_correct": a.scored_correct,
                "hint_tier": a.hint_tier,
                "attempted_at": _iso(a.attempted_at),
            }
            for a, stem, item_type in rows
        ],
    }


def retry_candidates(
    session: Session, learner_id: uuid.UUID, access: learner_scope.LearnerAccess, limit: int = 20
) -> list[dict[str, Any]]:
    """Questions whose most recent attempt by this learner was incorrect, newest first."""
    latest = (
        select(
            Attempt.question_id,
            func.max(Attempt.attempted_at).label("last_at"),
        )
        .where(Attempt.learner_id == learner_id)
        .group_by(Attempt.question_id)
        .subquery()
    )
    rows = session.execute(
        select(Attempt.question_id, Attempt.attempted_at)
        .join(
            latest,
            (Attempt.question_id == latest.c.question_id)
            & (Attempt.attempted_at == latest.c.last_at),
        )
        .where(Attempt.learner_id == learner_id, Attempt.scored_correct.is_(False))
        .order_by(Attempt.attempted_at.desc(), Attempt.question_id)
    ).all()
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for question_id, at in rows:
        if question_id in seen or not learner_scope.can_access_question(
            session, access, question_id
        ):
            continue
        question = session.get(Question, question_id)
        if question is None or question.active is not True:
            continue
        if question.review_status not in servable_review_statuses():
            continue
        seen.add(question_id)
        kc_ids = session.scalars(
            select(QuestionKc.kc_id)
            .where(
                QuestionKc.question_id == question_id,
                QuestionKc.review_status.in_(servable_review_statuses()),
            )
            .order_by(QuestionKc.kc_id)
        ).all()
        out.append(
            {
                "question_id": question_id,
                "item_type": question.item_type,
                "stem": question.stem,
                "kc_ids": [k for k in kc_ids if learner_scope.can_access_kc(session, access, k)],
                "last_attempted_at": _iso(at),
            }
        )
        if len(out) >= limit:
            break
    return out


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def class_weak_areas(session: Session, learner_ids: Sequence[uuid.UUID]) -> list[dict[str, Any]]:
    """Topics where some learners with enough evidence are below the weak cut-off, worst first.

    Ordering is deterministic: share below the cut-off (desc), mean mastery (asc), KC id.
    """
    per_kc: dict[str, list[float]] = defaultdict(list)
    for by_kc in mastery_by_kc(session, learner_ids).values():
        for kc_id, state in by_kc.items():
            if (
                state.mastery_probability is not None
                and (state.evidence_count or 0) >= MIN_EVIDENCE_FOR_WEAK
            ):
                per_kc[kc_id].append(float(state.mastery_probability))
    names = {
        k.kc_id: k.name
        for k in session.scalars(
            select(KnowledgeComponent).where(KnowledgeComponent.kc_id.in_(list(per_kc)))
        )
    }
    rows = []
    for kc_id, values in per_kc.items():
        below = sum(v < WEAK_BELOW for v in values)
        if below:
            rows.append(
                {
                    "kc_id": kc_id,
                    "name": names.get(kc_id),
                    "learners_with_evidence": len(values),
                    "learners_below_threshold": below,
                    "share_below_threshold": round(below / len(values), 4),
                    "average_mastery_probability": round(sum(values) / len(values), 4),
                }
            )
    rows.sort(
        key=lambda r: (-r["share_below_threshold"], r["average_mastery_probability"], r["kc_id"])
    )
    return rows
