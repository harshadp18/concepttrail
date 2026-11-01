"""What a student may reach, derived only from the server-side active enrollment.

A knowledge component is in a learner's scope when a servable curriculum mapping places it in
a class level the learner is actively enrolled in, or when it is a prerequisite (in the runtime
graph: the released snapshot in production, the demo graph in demo mode) of a KC at that level.
The second rule lets remediation reach earlier-class prerequisites without opening every lower
class. A client-supplied class level is never an input here.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.content_release import servable_curriculum_statuses, servable_review_statuses
from app.db.models import (
    ClassEnrollment,
    Classroom,
    CurriculumItem,
    CurriculumVersion,
    KcCurriculumMap,
    QuestionKc,
)
from app.services.graph_runtime import ReleasedGraph, get_runtime_graph


@dataclass(frozen=True)
class LearnerAccess:
    learner_id: uuid.UUID
    class_levels: tuple[int, ...]

    @property
    def enrolled(self) -> bool:
        return bool(self.class_levels)


def learner_access(session: Session, learner_id: uuid.UUID) -> LearnerAccess:
    levels = session.scalars(
        select(Classroom.grade_level)
        .join(ClassEnrollment, ClassEnrollment.classroom_id == Classroom.classroom_id)
        .where(
            ClassEnrollment.learner_id == learner_id,
            ClassEnrollment.ended_at.is_(None),
            Classroom.active.is_(True),
            Classroom.grade_level.is_not(None),
        )
    ).all()
    return LearnerAccess(learner_id, tuple(sorted({int(v) for v in levels})))


def kc_class_levels(session: Session, kc_ids: Iterable[str]) -> dict[str, set[int]]:
    """Class levels of each KC through servable mappings, items and curriculum versions."""
    ids = list(set(kc_ids))
    out: dict[str, set[int]] = {k: set() for k in ids}
    if not ids:
        return out
    rows = session.execute(
        select(KcCurriculumMap.kc_id, CurriculumVersion.class_level)
        .join(CurriculumItem, CurriculumItem.item_id == KcCurriculumMap.item_id)
        .join(
            CurriculumVersion,
            CurriculumVersion.curriculum_version_id == CurriculumItem.curriculum_version_id,
        )
        .where(
            KcCurriculumMap.kc_id.in_(ids),
            KcCurriculumMap.review_status.in_(servable_review_statuses()),
            CurriculumItem.status.in_(servable_curriculum_statuses()),
            CurriculumVersion.status.in_(servable_curriculum_statuses()),
        )
    )
    for kc_id, level in rows:
        if level is not None:
            out[kc_id].add(int(level))
    return out


def _remediation_reachable(graph: ReleasedGraph, kc_id: str, levels: tuple[int, ...]) -> bool:
    if kc_id not in graph.kcs:
        return False
    for dependent in graph.graph.dependents(kc_id):
        if set(graph.kcs.get(dependent, {}).get("class_levels", ())) & set(levels):
            return True
    return False


def accessible_kcs(session: Session, access: LearnerAccess, kc_ids: Iterable[str]) -> set[str]:
    """The subset of `kc_ids` this learner may open."""
    if not access.enrolled:
        return set()
    levels = kc_class_levels(session, kc_ids)
    allowed = {k for k, lv in levels.items() if lv & set(access.class_levels)}
    lower = [
        k
        for k, lv in levels.items()
        if k not in allowed and lv and min(lv) < max(access.class_levels)
    ]
    if lower:
        graph = get_runtime_graph(session)
        if isinstance(graph, ReleasedGraph):
            allowed |= {k for k in lower if _remediation_reachable(graph, k, access.class_levels)}
    return allowed


def can_access_kc(session: Session, access: LearnerAccess, kc_id: str) -> bool:
    return kc_id in accessible_kcs(session, access, [kc_id])


def can_access_question(session: Session, access: LearnerAccess, question_id: str) -> bool:
    """Every servable KC the question is mapped to must be in scope (none: not reachable)."""
    kcs = session.scalars(
        select(QuestionKc.kc_id).where(
            QuestionKc.question_id == question_id,
            QuestionKc.review_status.in_(servable_review_statuses()),
        )
    ).all()
    return bool(kcs) and set(kcs) <= accessible_kcs(session, access, kcs)


def student_access_for_user(session: Session, user_id: uuid.UUID) -> LearnerAccess | None:
    """Scope for a user holding a learner record; None for staff accounts."""
    from app.db.repositories.auth_repository import AuthRepository

    learner = AuthRepository(session).learner_for_user(user_id)
    return learner_access(session, learner.learner_id) if learner is not None else None


def kc_class_levels_any_status(session: Session, kc_ids: Iterable[str]) -> dict[str, set[int]]:
    """Class levels through curriculum mappings regardless of review status (staff review only)."""
    ids = list(set(kc_ids))
    out: dict[str, set[int]] = {k: set() for k in ids}
    if not ids:
        return out
    rows = session.execute(
        select(KcCurriculumMap.kc_id, CurriculumVersion.class_level)
        .join(CurriculumItem, CurriculumItem.item_id == KcCurriculumMap.item_id)
        .join(
            CurriculumVersion,
            CurriculumVersion.curriculum_version_id == CurriculumItem.curriculum_version_id,
        )
        .where(KcCurriculumMap.kc_id.in_(ids))
    )
    for kc_id, level in rows:
        if level is not None:
            out[kc_id].add(int(level))
    return out
