"""Read-only curriculum and knowledge-component endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.content_release import servable_curriculum_statuses, servable_review_statuses
from app.db.models import (
    CurriculumItem,
    CurriculumVersion,
    KcCurriculumMap,
    KnowledgeComponent,
    Note,
    Subject,
    User,
)
from app.db.session import get_db
from app.services import learner_scope

router = APIRouter(tags=["curriculum"])


@router.get("/curriculum")
def list_curriculum(
    grade_level: int | None = Query(default=None, ge=6, le=10),
    subject_id: str | None = Query(default=None, min_length=1, max_length=100),
    academic_session: str | None = Query(default=None, min_length=1, max_length=32),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),  # noqa: B008
    user: User = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    """List published curriculum versions and their published chapter/unit items.

    The endpoint intentionally excludes draft, pending and inactive records. For a student the
    visible class levels come from the active enrollment; `grade_level` only narrows that set
    (a level outside it is refused), it never grants access.
    """
    allowed_levels: set[int] | None = None
    access = learner_scope.student_access_for_user(session, user.user_id)
    if access is not None:
        if not access.enrolled:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "enrollment_required",
                    "message": "An active class enrollment is required.",
                },
            )
        allowed_levels = set(access.class_levels)
        if grade_level is not None and grade_level not in allowed_levels:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "forbidden_grade",
                    "message": "This class level is outside your enrollment.",
                },
            )
    # Subject is linked through curriculum_item, not directly to curriculum_version.
    # Query versions first, then load their active subject/item coverage below.
    versions = session.scalars(
        select(CurriculumVersion).where(
            CurriculumVersion.status.in_(servable_curriculum_statuses())
        )
    ).all()
    results: list[dict[str, Any]] = []
    for version in versions:
        if grade_level is not None and version.class_level != grade_level:
            continue
        if allowed_levels is not None and version.class_level not in allowed_levels:
            continue
        if academic_session is not None and version.academic_session != academic_session:
            continue
        items = session.scalars(
            select(CurriculumItem)
            .join(Subject, Subject.subject_id == CurriculumItem.subject_id)
            .where(
                CurriculumItem.curriculum_version_id == version.curriculum_version_id,
                CurriculumItem.status.in_(servable_curriculum_statuses()),
                Subject.active.is_(True),
            )
            .order_by(CurriculumItem.sequence_label, CurriculumItem.title)
        ).all()
        subject_ids = sorted({item.subject_id for item in items if item.subject_id})
        for sid in subject_ids:
            if subject_id is not None and sid != subject_id:
                continue
            subject = session.get(Subject, sid)
            if subject is None or subject.active is not True:
                continue
            subject_items = [item for item in items if item.subject_id == sid]
            results.append(
                {
                    "curriculum_version_id": version.curriculum_version_id,
                    "board": version.board,
                    "academic_session": version.academic_session,
                    "grade_level": version.class_level,
                    "course_or_language": version.course_or_language,
                    "subject": {
                        "subject_id": subject.subject_id,
                        "display_name": subject.display_name,
                        "subject_family": subject.subject_family,
                    },
                    "coverage": {
                        "published_item_count": len(subject_items),
                        # Never label AI-generated demo content as published.
                        "state": (
                            "not_available"
                            if not subject_items
                            else "published"
                            if all(i.status == "published" for i in subject_items)
                            else "demo_release"
                        ),
                    },
                    "items": [
                        {
                            "item_id": item.item_id,
                            "parent_item_id": item.parent_item_id,
                            "item_type": item.item_type,
                            "title": item.title,
                            "sequence_label": item.sequence_label,
                            "learning_objectives": item.learning_objectives,
                        }
                        for item in subject_items
                    ],
                }
            )
    results.sort(
        key=lambda row: (
            row["grade_level"] or 0,
            row["subject"]["display_name"] or "",
            row["academic_session"] or "",
        )
    )
    total = len(results)
    return {
        "count": total,
        "limit": limit,
        "offset": offset,
        "curricula": results[offset : offset + limit],
    }


@router.get("/topics/{kc_id}")
def get_topic(
    kc_id: str,
    session: Session = Depends(get_db),  # noqa: B008
    user: User = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    """Return a reviewed knowledge component and its published curriculum links.

    A student sees only KCs in their enrolled scope (others are reported as not found).

    Notes are included only when their review status is exactly `approved`; content
    whose rights/review state is not represented by an explicit approval is omitted.
    """
    kc = session.get(KnowledgeComponent, kc_id)
    if kc is None or kc.review_status not in servable_review_statuses():
        raise HTTPException(
            status_code=404,
            detail={"code": "topic_not_found", "message": "The requested topic is unavailable."},
        )
    access = learner_scope.student_access_for_user(session, user.user_id)
    if access is not None and not learner_scope.can_access_kc(session, access, kc_id):
        raise HTTPException(
            status_code=404,
            detail={"code": "topic_not_found", "message": "The requested topic is unavailable."},
        )

    mappings = session.execute(
        select(KcCurriculumMap, CurriculumItem, CurriculumVersion)
        .join(CurriculumItem, CurriculumItem.item_id == KcCurriculumMap.item_id)
        .join(
            CurriculumVersion,
            CurriculumVersion.curriculum_version_id == CurriculumItem.curriculum_version_id,
        )
        .where(
            KcCurriculumMap.kc_id == kc_id,
            KcCurriculumMap.review_status.in_(servable_review_statuses()),
            CurriculumItem.status.in_(servable_curriculum_statuses()),
            CurriculumVersion.status.in_(servable_curriculum_statuses()),
        )
    ).all()

    notes = session.scalars(
        select(Note).where(Note.kc_id == kc_id, Note.review_status.in_(servable_review_statuses()))
    ).all()

    return {
        "kc_id": kc.kc_id,
        "subject_id": kc.subject_id,
        "stable_key": kc.stable_key,
        "name": kc.name,
        "description": kc.description,
        "kc_type": kc.kc_type,
        "difficulty_tier": kc.difficulty_tier,
        "misconceptions": kc.misconceptions,
        "content_version": kc.content_version,
        "curriculum_mappings": [
            {
                "item_id": item.item_id,
                "item_title": item.title,
                "item_type": item.item_type,
                "grade_level": version.class_level,
                "academic_session": version.academic_session,
                "curriculum_version_id": version.curriculum_version_id,
            }
            for _mapping, item, version in mappings
        ],
        "notes": [
            {
                "note_id": str(note.note_id),
                "title": note.title,
                "content_markdown": note.content_markdown,
                "language": note.language,
                "note_type": note.note_type,
                "content_version": note.content_version,
            }
            for note in notes
        ],
    }
