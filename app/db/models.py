"""SQLAlchemy 2.x mappings for the 26 existing tables in the `concepttrail` schema.

These mappings mirror the live database as introspected read-only on 2026-10-31, which
is identical to `db/schema/001_initial_schema.sql`:

- only primary-key columns are NOT NULL; every other column is nullable;
- no server defaults, CHECK constraints or ON DELETE/ON UPDATE actions;
- VARCHAR without length, NUMERIC without precision, `embedding` as unbounded VECTOR;
- `subject_id` and curriculum/content/KC/question identifiers are VARCHAR;
  user, learner, attempt, job, option, note, classroom and chunk identifiers are UUID.

Columns are declared in live ordinal order. The mappings never create or alter tables;
any change to them requires an approved Alembic migration first.

ORM relationships are intentionally not declared yet; repositories add them when a
query needs them. Foreign-key constraints are fully declared below.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import ForeignKey, Index, SmallInteger, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import DB_SCHEMA, Base

JSONValue = dict[str, Any] | list[Any]


def _fk(target: str, *, name: str | None = None) -> ForeignKey:
    return ForeignKey(f"{DB_SCHEMA}.{target}", name=name)


# --- Curriculum and sources -------------------------------------------------------


class Subject(Base):
    __tablename__ = "subject"

    subject_id: Mapped[str] = mapped_column(primary_key=True)
    display_name: Mapped[str | None]
    subject_family: Mapped[str | None]
    active: Mapped[bool | None]


class CurriculumVersion(Base):
    __tablename__ = "curriculum_version"

    curriculum_version_id: Mapped[str] = mapped_column(primary_key=True)
    board: Mapped[str | None]
    academic_session: Mapped[str | None]
    class_level: Mapped[int | None] = mapped_column(SmallInteger)
    course_or_language: Mapped[str | None]
    source_url: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[datetime | None]
    status: Mapped[str | None]


class SourceDocument(Base):
    __tablename__ = "source_document"
    __table_args__ = (
        Index("idx_source_document_subject", "subject_id"),
        Index("idx_source_document_curriculum_version", "curriculum_version_id"),
    )

    source_id: Mapped[str] = mapped_column(primary_key=True)
    subject_id: Mapped[str | None] = mapped_column(_fk("subject.subject_id"))
    curriculum_version_id: Mapped[str | None] = mapped_column(
        _fk("curriculum_version.curriculum_version_id")
    )
    title: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    publisher: Mapped[str | None] = mapped_column(Text)
    edition_label: Mapped[str | None]
    acquired_at: Mapped[datetime | None]
    sha256: Mapped[str | None]
    rights_status: Mapped[str | None]
    permitted_uses: Mapped[JSONValue | None] = mapped_column(JSONB)
    permission_reference: Mapped[str | None] = mapped_column(Text)
    last_verified_at: Mapped[datetime | None]
    status: Mapped[str | None]


class CurriculumItem(Base):
    __tablename__ = "curriculum_item"
    __table_args__ = (
        Index("idx_curriculum_item_curriculum_version", "curriculum_version_id"),
        Index("idx_curriculum_item_subject", "subject_id"),
        Index("idx_curriculum_item_parent", "parent_item_id"),
    )

    item_id: Mapped[str] = mapped_column(primary_key=True)
    curriculum_version_id: Mapped[str | None] = mapped_column(
        _fk("curriculum_version.curriculum_version_id")
    )
    subject_id: Mapped[str | None] = mapped_column(_fk("subject.subject_id"))
    parent_item_id: Mapped[str | None] = mapped_column(_fk("curriculum_item.item_id"))
    item_type: Mapped[str | None]
    title: Mapped[str | None] = mapped_column(Text)
    sequence_label: Mapped[str | None]
    learning_objectives: Mapped[JSONValue | None] = mapped_column(JSONB)
    status: Mapped[str | None]


class ContentUnit(Base):
    __tablename__ = "content_unit"
    __table_args__ = (
        Index("idx_content_unit_source", "source_id"),
        Index("idx_content_unit_item", "item_id"),
    )

    content_unit_id: Mapped[str] = mapped_column(primary_key=True)
    source_id: Mapped[str | None] = mapped_column(_fk("source_document.source_id"))
    item_id: Mapped[str | None] = mapped_column(_fk("curriculum_item.item_id"))
    unit_type: Mapped[str | None]
    title: Mapped[str | None] = mapped_column(Text)
    content_text: Mapped[str | None] = mapped_column(Text)
    pdf_page_index: Mapped[int | None]
    printed_page_label: Mapped[str | None]
    asset_refs: Mapped[JSONValue | None] = mapped_column(JSONB)
    content_sha256: Mapped[str | None]
    extraction_status: Mapped[str | None]
    review_status: Mapped[str | None]
    pipeline_version: Mapped[str | None]


# --- Knowledge components and prerequisite graph ---------------------------------


class KnowledgeComponent(Base):
    __tablename__ = "knowledge_component"
    __table_args__ = (Index("idx_knowledge_component_subject", "subject_id"),)

    kc_id: Mapped[str] = mapped_column(primary_key=True)
    subject_id: Mapped[str | None] = mapped_column(_fk("subject.subject_id"))
    stable_key: Mapped[str | None] = mapped_column(unique=True)
    name: Mapped[str | None]
    description: Mapped[str | None] = mapped_column(Text)
    kc_type: Mapped[str | None]
    difficulty_tier: Mapped[int | None] = mapped_column(SmallInteger)
    misconceptions: Mapped[JSONValue | None] = mapped_column(JSONB)
    review_status: Mapped[str | None]
    content_version: Mapped[str | None]


class ContentUnitKc(Base):
    __tablename__ = "content_unit_kcs"

    content_unit_id: Mapped[str] = mapped_column(
        _fk("content_unit.content_unit_id"), primary_key=True
    )
    kc_id: Mapped[str] = mapped_column(_fk("knowledge_component.kc_id"), primary_key=True)
    mapping_role: Mapped[str | None]
    mapping_confidence: Mapped[Decimal | None]
    review_status: Mapped[str | None]
    created_at: Mapped[datetime | None]


class KcCurriculumMap(Base):
    __tablename__ = "kc_curriculum_map"

    kc_id: Mapped[str] = mapped_column(_fk("knowledge_component.kc_id"), primary_key=True)
    item_id: Mapped[str] = mapped_column(_fk("curriculum_item.item_id"), primary_key=True)
    mapping_role: Mapped[str | None]
    review_status: Mapped[str | None]
    created_at: Mapped[datetime | None]


class KcEdge(Base):
    """Prerequisite edge: `prerequisite_kc_id` is a prerequisite of `dependent_kc_id`."""

    __tablename__ = "kc_edge"

    prerequisite_kc_id: Mapped[str] = mapped_column(
        _fk("knowledge_component.kc_id"), primary_key=True
    )
    dependent_kc_id: Mapped[str] = mapped_column(_fk("knowledge_component.kc_id"), primary_key=True)
    strength: Mapped[int | None] = mapped_column(SmallInteger)
    reason: Mapped[str | None] = mapped_column(Text)
    review_status: Mapped[str | None]


# --- Question bank and notes -------------------------------------------------------


class Question(Base):
    __tablename__ = "questions"

    question_id: Mapped[str] = mapped_column(primary_key=True)
    item_type: Mapped[str | None]
    stem: Mapped[str | None] = mapped_column(Text)
    expected_answer: Mapped[JSONValue | None] = mapped_column(JSONB)
    rubric: Mapped[JSONValue | None] = mapped_column(JSONB)
    difficulty: Mapped[int | None] = mapped_column(SmallInteger)
    misconception_map: Mapped[JSONValue | None] = mapped_column(JSONB)
    source_refs: Mapped[JSONValue | None] = mapped_column(JSONB)
    verification: Mapped[JSONValue | None] = mapped_column(JSONB)
    review_status: Mapped[str | None]
    version: Mapped[int | None]
    active: Mapped[bool | None]


class QuestionKc(Base):
    __tablename__ = "question_kcs"

    question_id: Mapped[str] = mapped_column(_fk("questions.question_id"), primary_key=True)
    kc_id: Mapped[str] = mapped_column(_fk("knowledge_component.kc_id"), primary_key=True)
    weight: Mapped[Decimal | None]
    mapping_role: Mapped[str | None]
    review_status: Mapped[str | None]


class QuestionOption(Base):
    __tablename__ = "question_options"
    __table_args__ = (Index("idx_question_options_question", "question_id"),)

    option_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    question_id: Mapped[str | None] = mapped_column(_fk("questions.question_id"))
    option_key: Mapped[str | None]
    option_text: Mapped[str | None] = mapped_column(Text)
    is_correct: Mapped[bool | None]
    explanation: Mapped[str | None] = mapped_column(Text)
    display_order: Mapped[int | None] = mapped_column(SmallInteger)


class Note(Base):
    __tablename__ = "note"
    __table_args__ = (Index("idx_note_kc", "kc_id"),)

    note_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    kc_id: Mapped[str | None] = mapped_column(_fk("knowledge_component.kc_id"))
    title: Mapped[str | None] = mapped_column(Text)
    content_markdown: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None]
    note_type: Mapped[str | None]
    recipe_version: Mapped[str | None]
    model_id: Mapped[str | None]
    prompt_version: Mapped[str | None]
    content_version: Mapped[str | None]
    review_status: Mapped[str | None]
    # The live constraint name is not PostgreSQL's default, so it is set explicitly.
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        _fk("users.user_id", name="fk_note_approved_by")
    )
    approved_at: Mapped[datetime | None]


# --- Users, learners and roles -----------------------------------------------------


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    login_identifier: Mapped[str | None] = mapped_column(unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool | None]
    created_at: Mapped[datetime | None]
    updated_at: Mapped[datetime | None]


class Learner(Base):
    __tablename__ = "learners"

    learner_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(_fk("users.user_id"), unique=True)
    display_name: Mapped[str | None]
    created_at: Mapped[datetime | None]


class Role(Base):
    __tablename__ = "role"

    role_code: Mapped[str] = mapped_column(primary_key=True)
    description: Mapped[str | None] = mapped_column(Text)


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(_fk("users.user_id"), primary_key=True)
    role_code: Mapped[str] = mapped_column(_fk("role.role_code"), primary_key=True)
    assigned_at: Mapped[datetime | None]


# --- Attempts and mastery ----------------------------------------------------------


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (
        Index("idx_attempts_learner", "learner_id"),
        Index("idx_attempts_question", "question_id"),
    )

    attempt_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    learner_id: Mapped[uuid.UUID | None] = mapped_column(_fk("learners.learner_id"))
    question_id: Mapped[str | None] = mapped_column(_fk("questions.question_id"))
    question_version: Mapped[int | None]
    submitted_answer: Mapped[JSONValue | None] = mapped_column(JSONB)
    scored_correct: Mapped[bool | None]
    score: Mapped[Decimal | None]
    score_method: Mapped[str | None]
    hint_tier: Mapped[int | None] = mapped_column(SmallInteger)
    attempted_at: Mapped[datetime | None]
    idempotency_key: Mapped[str | None] = mapped_column(unique=True)


class BktConfigVersion(Base):
    __tablename__ = "bkt_config_version"

    bkt_config_version: Mapped[str] = mapped_column(primary_key=True)
    parameters: Mapped[JSONValue | None] = mapped_column(JSONB)
    effective_at: Mapped[datetime | None]
    created_at: Mapped[datetime | None]
    notes: Mapped[str | None] = mapped_column(Text)


class StudentKcState(Base):
    __tablename__ = "student_kc_state"
    __table_args__ = (Index("idx_student_kc_state_kc", "kc_id"),)

    learner_id: Mapped[uuid.UUID] = mapped_column(_fk("learners.learner_id"), primary_key=True)
    kc_id: Mapped[str] = mapped_column(_fk("knowledge_component.kc_id"), primary_key=True)
    mastery_probability: Mapped[float | None]
    bkt_config_version: Mapped[str | None] = mapped_column(
        _fk("bkt_config_version.bkt_config_version")
    )
    updated_at: Mapped[datetime | None]
    evidence_count: Mapped[int | None]


# --- Retrieval index -----------------------------------------------------------------


class EmbeddingChunk(Base):
    """Exactly the nine agreed columns; `embedding` stays dimension-unbounded VECTOR."""

    __tablename__ = "embedding_chunk"
    __table_args__ = (Index("idx_embedding_chunk_content_unit", "content_unit_id"),)

    chunk_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    content_unit_id: Mapped[str | None] = mapped_column(_fk("content_unit.content_unit_id"))
    chunk_order: Mapped[int | None]
    chunk_text: Mapped[str | None] = mapped_column(Text)
    token_count: Mapped[int | None]
    embedding_model_id: Mapped[str | None]
    embedding: Mapped[Any] = mapped_column(VECTOR(), nullable=True)
    index_generation: Mapped[str | None]
    created_at: Mapped[datetime | None]


# --- Ingestion jobs ------------------------------------------------------------------


class IngestionJob(Base):
    __tablename__ = "ingestion_job"
    __table_args__ = (Index("idx_ingestion_job_created_by", "created_by"),)

    job_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    job_type: Mapped[str | None]
    pipeline_version: Mapped[str | None]
    status: Mapped[str | None]
    created_at: Mapped[datetime | None]
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    created_by: Mapped[uuid.UUID | None] = mapped_column(_fk("users.user_id"))
    error_summary: Mapped[str | None] = mapped_column(Text)


class IngestionJobDocument(Base):
    __tablename__ = "ingestion_job_documents"
    __table_args__ = (Index("idx_ingestion_job_documents_source", "source_id"),)

    job_id: Mapped[uuid.UUID] = mapped_column(_fk("ingestion_job.job_id"), primary_key=True)
    source_id: Mapped[str] = mapped_column(_fk("source_document.source_id"), primary_key=True)
    document_status: Mapped[str | None]
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    error_summary: Mapped[str | None] = mapped_column(Text)


# --- Classrooms --------------------------------------------------------------------


class Classroom(Base):
    __tablename__ = "classroom"

    classroom_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    grade_level: Mapped[int | None] = mapped_column(SmallInteger)
    section_label: Mapped[str | None]
    academic_session: Mapped[str | None]
    school_label: Mapped[str | None]
    active: Mapped[bool | None]


class ClassEnrollment(Base):
    __tablename__ = "class_enrollments"
    __table_args__ = (
        Index("idx_class_enrollments_learner", "learner_id"),
        Index("idx_class_enrollments_classroom", "classroom_id"),
    )

    enrollment_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    learner_id: Mapped[uuid.UUID | None] = mapped_column(_fk("learners.learner_id"))
    classroom_id: Mapped[uuid.UUID | None] = mapped_column(_fk("classroom.classroom_id"))
    enrolled_at: Mapped[datetime | None]
    ended_at: Mapped[datetime | None]


class TeacherClassAssignment(Base):
    __tablename__ = "teacher_class_assignments"
    __table_args__ = (Index("idx_teacher_class_assignments_user", "user_id"),)

    classroom_id: Mapped[uuid.UUID] = mapped_column(_fk("classroom.classroom_id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(_fk("users.user_id"), primary_key=True)
    assigned_role: Mapped[str | None]
    assigned_at: Mapped[datetime | None]
    ended_at: Mapped[datetime | None]
