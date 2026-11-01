"""Learner-level entry points for the API layer (the teammate's endpoints call these).

`recommend_for_learner` resolves scope from the learner's active enrollment (never from a
client value), selects the runtime graph (production: verified released snapshot; demo mode:
the demo graph) and returns the deterministic recommendation with its rationale.
`explain_for_learner` retrieves evidence in the matching mode (production: approved pages;
demo: usable unflagged pages), then calls the grounded explanation service, which checks the
purpose-specific rights for every evidence source. Neither changes scores or mastery.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.content_release import (
    demo_enabled,
    servable_curriculum_statuses,
    servable_review_statuses,
)
from app.db.models import (
    ClassEnrollment,
    Classroom,
    CurriculumItem,
    CurriculumVersion,
    KcCurriculumMap,
    KnowledgeComponent,
)
from app.services import adaptive, ai_generation, learner_scope
from app.services.embeddings import Embedder, EmbeddingError
from app.services.graph_runtime import get_runtime_graph
from app.services.llm import LocalLLM
from app.services.mastery import get_learner_mastery
from app.services.question_bank import get_approved_questions
from app.services.rag import RetrievalFilter, retrieve_evidence


def learner_class_levels(session: Session, learner_id: uuid.UUID) -> list[int]:
    return sorted(
        {
            c.grade_level
            for c in session.scalars(
                select(Classroom)
                .join(ClassEnrollment, ClassEnrollment.classroom_id == Classroom.classroom_id)
                .where(
                    ClassEnrollment.learner_id == learner_id,
                    ClassEnrollment.ended_at.is_(None),
                    Classroom.active.is_(True),
                )
            )
            if c.grade_level is not None
        }
    )


def recommend_for_learner(
    session: Session, learner_id: uuid.UUID, subject_id: str | None = None
) -> dict[str, Any]:
    levels = learner_class_levels(session, learner_id)
    if not levels:
        return adaptive.explain_recommendation(adaptive.InsufficientData("no_active_enrollment"))
    scope = adaptive.LearnerScope(levels[-1], (subject_id,) if subject_id else None)
    graph = get_runtime_graph(session)
    result = adaptive.recommend_next_learning_step(session, learner_id, graph, scope)
    out = adaptive.explain_recommendation(result)
    out["content_release"] = "demo" if demo_enabled() else "production"
    return out


def explain_for_learner(
    session: Session,
    question: str,
    *,
    llm: LocalLLM,
    embedder: Embedder,
    index_generation: str,
    check_use: Any,
    class_level: int,
    subject_id: str | None = None,
    hint_only: bool = False,
    retrieval_context: str | None = None,
) -> ai_generation.GroundedResult:
    """`class_level` is required: callers derive it from the learner's enrollment, so retrieval
    can never span every class."""
    try:
        model = embedder.describe()
        # A follow-up may be unclear on its own ("why?"): the previous student question is
        # added to the retrieval query only. The model is still shown just the current question
        # and the retrieved evidence, so earlier turns are never treated as evidence.
        query = f"{retrieval_context} {question}" if retrieval_context else question
        vector = embedder.embed([query])[0]
    except EmbeddingError:
        return ai_generation.GroundedResult("model_unavailable")
    evidence = retrieve_evidence(
        session,
        vector,
        embedding_model_id=model.model_id,
        index_generation=index_generation,
        filters=RetrievalFilter(class_level=class_level, subject_id=subject_id),
        mode="demo" if demo_enabled() else "student",
        k=4,
    )
    if hint_only:
        return ai_generation.generate_hint(llm, question, evidence, check_use)
    return ai_generation.generate_explanation(llm, question, evidence, check_use)


def chapter_topics(
    session: Session, item_id: str, learner_id: uuid.UUID | None
) -> dict[str, Any] | None:
    """Servable KCs of one curriculum item, with the learner's own mastery when a learner asks.

    Returns None when the item is not servable, or (for a learner) when none of its KCs is in
    the learner's enrolled scope.
    """
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
    if row is None:
        return None
    item, version = row
    kcs = session.scalars(
        select(KnowledgeComponent)
        .join(KcCurriculumMap, KcCurriculumMap.kc_id == KnowledgeComponent.kc_id)
        .where(
            KcCurriculumMap.item_id == item_id,
            KcCurriculumMap.review_status.in_(servable_review_statuses()),
            KnowledgeComponent.review_status.in_(servable_review_statuses()),
        )
        .order_by(KnowledgeComponent.kc_id)
    ).all()
    mastery: dict[str, Any] = {}
    if learner_id is not None:
        access = learner_scope.learner_access(session, learner_id)
        allowed = learner_scope.accessible_kcs(session, access, [k.kc_id for k in kcs])
        if not allowed:
            return None
        kcs = [k for k in kcs if k.kc_id in allowed]
        mastery = get_learner_mastery(session, learner_id)
    topics = []
    for kc in kcs:
        state = mastery.get(kc.kc_id)
        topics.append(
            {
                "kc_id": kc.kc_id,
                "name": kc.name,
                "description": kc.description,
                "kc_type": kc.kc_type,
                "difficulty_tier": kc.difficulty_tier,
                "question_count": len(get_approved_questions(session, kc.kc_id)),
                "mastery_probability": state.mastery_probability if state else None,
                "evidence_count": state.evidence_count if state else 0,
            }
        )
    return {
        "item_id": item.item_id,
        "title": item.title,
        "subject_id": item.subject_id,
        "grade_level": version.class_level,
        "content_release": "demo" if demo_enabled() else "production",
        "topics": topics,
    }
