"""Class/subject availability, chapter detail and topic prerequisites.

Read-only. A student sees only their enrolled class levels; a teacher only the levels of
their active class assignments. Nothing here invents curriculum: a class-subject pair with no
servable chapters is reported as `not_available`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.content_release import (
    demo_enabled,
    servable_curriculum_statuses,
    servable_review_statuses,
)
from app.db.models import (
    CurriculumItem,
    CurriculumVersion,
    KcCurriculumMap,
    KnowledgeComponent,
    Subject,
    User,
)
from app.db.repositories.auth_repository import AuthRepository
from app.db.session import get_db
from app.services import learner_scope, learning
from app.services.adaptive import DEFAULT_THRESHOLDS
from app.services.graph_runtime import GraphUnavailable, get_runtime_graph
from app.services.mastery import get_learner_mastery

router = APIRouter(tags=["catalog"])
ALL_LEVELS = (6, 7, 8, 9, 10)


def _not_found(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": code, "message": message})


def visible_levels(session: Session, user: User) -> tuple[int, ...]:
    """Class levels this account may see, from the server-side enrollment or assignment."""
    repository = AuthRepository(session)
    learner = repository.learner_for_user(user.user_id)
    if learner is not None:
        levels = learner_scope.learner_access(session, learner.learner_id).class_levels
        if not levels:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "enrollment_required",
                    "message": "An active class enrollment is required.",
                },
            )
        return levels
    assigned = repository.assigned_classrooms(user.user_id)
    levels = tuple(sorted({int(c.grade_level) for c in assigned if c.grade_level is not None}))
    if not levels:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "forbidden_classroom",
                "message": "No active class enrollment or assignment.",
            },
        )
    return levels


@router.get("/catalog/classes")
def list_class_subject_availability(
    session: Session = Depends(get_db),  # noqa: B008
    user: User = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    """Every class-subject pair in the caller's scope with its content availability.

    `state`: `published` (all chapters human-approved), `demo_release` (AI-generated, not
    teacher-reviewed) or `not_available`. Counts are servable chapters and topics only.
    """
    levels = visible_levels(session, user)
    subjects = session.scalars(
        select(Subject).where(Subject.active.is_(True)).order_by(Subject.display_name)
    ).all()
    chapter_counts = {
        (level, sid): (int(n), int(published))
        for level, sid, n, published in session.execute(
            select(
                CurriculumVersion.class_level,
                CurriculumItem.subject_id,
                func.count(CurriculumItem.item_id),
                func.count(CurriculumItem.item_id).filter(CurriculumItem.status == "published"),
            )
            .join(
                CurriculumVersion,
                CurriculumVersion.curriculum_version_id == CurriculumItem.curriculum_version_id,
            )
            .where(
                CurriculumVersion.status.in_(servable_curriculum_statuses()),
                CurriculumItem.status.in_(servable_curriculum_statuses()),
                CurriculumVersion.class_level.in_(levels),
            )
            .group_by(CurriculumVersion.class_level, CurriculumItem.subject_id)
        )
    }
    topic_counts = {
        (level, sid): int(n)
        for level, sid, n in session.execute(
            select(
                CurriculumVersion.class_level,
                CurriculumItem.subject_id,
                func.count(func.distinct(KcCurriculumMap.kc_id)),
            )
            .join(
                CurriculumVersion,
                CurriculumVersion.curriculum_version_id == CurriculumItem.curriculum_version_id,
            )
            .join(KcCurriculumMap, KcCurriculumMap.item_id == CurriculumItem.item_id)
            .join(KnowledgeComponent, KnowledgeComponent.kc_id == KcCurriculumMap.kc_id)
            .where(
                CurriculumVersion.status.in_(servable_curriculum_statuses()),
                CurriculumItem.status.in_(servable_curriculum_statuses()),
                KcCurriculumMap.review_status.in_(servable_review_statuses()),
                KnowledgeComponent.review_status.in_(servable_review_statuses()),
                CurriculumVersion.class_level.in_(levels),
            )
            .group_by(CurriculumVersion.class_level, CurriculumItem.subject_id)
        )
    }
    combos = []
    for level in levels:
        for subject in subjects:
            chapters, published = chapter_counts.get((level, subject.subject_id), (0, 0))
            combos.append(
                {
                    "grade_level": level,
                    "subject_id": subject.subject_id,
                    "subject_name": subject.display_name,
                    "chapters": chapters,
                    "topics": topic_counts.get((level, subject.subject_id), 0),
                    "state": (
                        "not_available"
                        if chapters == 0
                        else "published"
                        if chapters == published
                        else "demo_release"
                    ),
                }
            )
    return {
        "content_release": "demo" if demo_enabled() else "production",
        "grade_levels": list(levels),
        "subjects": [
            {"subject_id": s.subject_id, "display_name": s.display_name} for s in subjects
        ],
        "combinations": combos,
        "note": "not_available means no servable chapters exist; nothing is invented.",
    }


@router.get("/curriculum/items/{item_id}")
def get_chapter(
    item_id: str,
    session: Session = Depends(get_db),  # noqa: B008
    user: User = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    """Chapter detail: objectives, sub-items and topics (a student sees only in-scope topics)."""
    levels = visible_levels(session, user)
    row = session.execute(
        select(CurriculumItem, CurriculumVersion)
        .join(
            CurriculumVersion,
            CurriculumVersion.curriculum_version_id == CurriculumItem.curriculum_version_id,
        )
        .where(
            CurriculumItem.item_id == item_id,
            CurriculumItem.status.in_(servable_curriculum_statuses()),
            CurriculumVersion.status.in_(servable_curriculum_statuses()),
        )
    ).first()
    if row is None or row[1].class_level not in levels:
        raise _not_found("item_not_found", "The requested chapter is unavailable.")
    item, version = row
    learner = AuthRepository(session).learner_for_user(user.user_id)
    topics = learning.chapter_topics(session, item_id, learner.learner_id if learner else None)
    if learner is not None and topics is None:
        raise _not_found("item_not_found", "The requested chapter is unavailable.")
    children = session.scalars(
        select(CurriculumItem)
        .where(
            CurriculumItem.parent_item_id == item_id,
            CurriculumItem.status.in_(servable_curriculum_statuses()),
        )
        .order_by(CurriculumItem.sequence_label, CurriculumItem.item_id)
    ).all()
    subject = session.get(Subject, item.subject_id) if item.subject_id else None
    return {
        "item_id": item.item_id,
        "parent_item_id": item.parent_item_id,
        "item_type": item.item_type,
        "title": item.title,
        "sequence_label": item.sequence_label,
        "grade_level": version.class_level,
        "subject_id": item.subject_id,
        "subject_name": subject.display_name if subject else None,
        "learning_objectives": item.learning_objectives,
        "release_state": "published" if item.status == "published" else "demo_release",
        "curriculum": {
            "curriculum_version_id": version.curriculum_version_id,
            "board": version.board,
            "academic_session": version.academic_session,
            "source_url": version.source_url,
            "verified_at": version.verified_at.isoformat() if version.verified_at else None,
        },
        "sub_items": [
            {"item_id": c.item_id, "title": c.title, "sequence_label": c.sequence_label}
            for c in children
        ],
        "topics": (topics or {}).get("topics", []),
        "topics_available": bool(topics and topics["topics"]),
    }


@router.get("/topics/{kc_id}/prerequisites")
def get_topic_prerequisites(
    kc_id: str,
    session: Session = Depends(get_db),  # noqa: B008
    user: User = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    """Direct and transitive prerequisites from the runtime graph, with readiness.

    Edges are AI-proposed unless the graph is a released (human-approved) snapshot; the
    response says which. For a student each prerequisite carries their own estimate and
    whether it meets the provisional readiness threshold.
    """
    kc = session.get(KnowledgeComponent, kc_id)
    if kc is None or kc.review_status not in servable_review_statuses():
        raise _not_found("topic_not_found", "The requested topic is unavailable.")
    access = learner_scope.student_access_for_user(session, user.user_id)
    if access is not None and not learner_scope.can_access_kc(session, access, kc_id):
        raise _not_found("topic_not_found", "The requested topic is unavailable.")
    graph = get_runtime_graph(session)
    if isinstance(graph, GraphUnavailable) or kc_id not in graph.kcs:
        return {
            "kc_id": kc_id,
            "graph_available": False,
            "reason": graph.reason if isinstance(graph, GraphUnavailable) else "kc_not_in_graph",
            "direct": [],
            "transitive": [],
        }
    mastery = get_learner_mastery(session, access.learner_id) if access else {}
    names = {
        k.kc_id: k.name
        for k in session.scalars(select(KnowledgeComponent)).all()
        if k.kc_id in graph.kcs
    }
    direct = graph.graph.direct_prerequisites(kc_id)
    everything = graph.graph.prerequisites(kc_id)

    def view(k: str) -> dict[str, Any]:
        m = mastery.get(k)
        p = m.mastery_probability if m else None
        return {
            "kc_id": k,
            "name": names.get(k),
            "mastery_probability": p,
            "ready": (p is not None and p >= DEFAULT_THRESHOLDS.prerequisite_ready)
            if access
            else None,
        }

    return {
        "kc_id": kc_id,
        "graph_available": True,
        "graph_version": graph.version,
        "edge_provenance": "ai_proposed_demo" if graph.kind == "demo" else "released_snapshot",
        "readiness_threshold": DEFAULT_THRESHOLDS.prerequisite_ready,
        "thresholds_provisional": True,
        "direct": [view(k) for k in direct],
        "transitive": [view(k) for k in everything],
        "all_direct_ready": (all(view(k)["ready"] for k in direct) if access and direct else None),
    }
