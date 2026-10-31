-- ============================================================
-- CONCEPTTRAIL — 26 TABLE BASELINE
-- PostgreSQL 18 + pgvector; schema aligned with the ERD/script
-- the owner reported executing successfully.
--
-- IMPORTANT:
-- 1. This is a clean-schema bootstrap/reference, NOT an upgrade.
-- 2. Do not rerun against an already populated concepttrail schema.
-- 3. It preserves VARCHAR subject_id as in the executed baseline.
-- 4. VECTOR is intentionally dimension-unbounded until model selection.
-- 5. Review participation/NOT NULL business constraints separately.
-- ============================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
CREATE SCHEMA IF NOT EXISTS concepttrail;
SET LOCAL search_path TO concepttrail, public;

-- 1. SUBJECT
CREATE TABLE concepttrail.subject (
    subject_id       VARCHAR PRIMARY KEY,
    display_name     VARCHAR,
    subject_family   VARCHAR,
    active           BOOLEAN
);

-- 2. CURRICULUM_VERSION
CREATE TABLE concepttrail.curriculum_version (
    curriculum_version_id  VARCHAR PRIMARY KEY,
    board                  VARCHAR,
    academic_session       VARCHAR,
    class_level            SMALLINT,
    course_or_language     VARCHAR,
    source_url             TEXT,
    verified_at            TIMESTAMPTZ,
    status                 VARCHAR
);

-- 3. SOURCE_DOCUMENT
CREATE TABLE concepttrail.source_document (
    source_id              VARCHAR PRIMARY KEY,
    subject_id             VARCHAR REFERENCES concepttrail.subject(subject_id),
    curriculum_version_id  VARCHAR REFERENCES concepttrail.curriculum_version(curriculum_version_id),
    title                  TEXT,
    source_url             TEXT,
    publisher              TEXT,
    edition_label          VARCHAR,
    acquired_at            TIMESTAMPTZ,
    sha256                 VARCHAR,
    rights_status          VARCHAR,
    permitted_uses         JSONB,
    permission_reference   TEXT,
    last_verified_at       TIMESTAMPTZ,
    status                 VARCHAR
);

-- 4. CURRICULUM_ITEM
CREATE TABLE concepttrail.curriculum_item (
    item_id                VARCHAR PRIMARY KEY,
    curriculum_version_id  VARCHAR REFERENCES concepttrail.curriculum_version(curriculum_version_id),
    subject_id             VARCHAR REFERENCES concepttrail.subject(subject_id),
    parent_item_id         VARCHAR REFERENCES concepttrail.curriculum_item(item_id),
    item_type              VARCHAR,
    title                  TEXT,
    sequence_label         VARCHAR,
    learning_objectives    JSONB,
    status                 VARCHAR
);

-- 5. CONTENT_UNIT
CREATE TABLE concepttrail.content_unit (
    content_unit_id    VARCHAR PRIMARY KEY,
    source_id          VARCHAR REFERENCES concepttrail.source_document(source_id),
    item_id            VARCHAR REFERENCES concepttrail.curriculum_item(item_id),
    unit_type          VARCHAR,
    title              TEXT,
    content_text       TEXT,
    pdf_page_index     INTEGER,
    printed_page_label VARCHAR,
    asset_refs         JSONB,
    content_sha256     VARCHAR,
    extraction_status  VARCHAR,
    review_status      VARCHAR,
    pipeline_version   VARCHAR
);

-- 6. KNOWLEDGE_COMPONENT
CREATE TABLE concepttrail.knowledge_component (
    kc_id             VARCHAR PRIMARY KEY,
    subject_id        VARCHAR REFERENCES concepttrail.subject(subject_id),
    stable_key        VARCHAR UNIQUE,
    name              VARCHAR,
    description       TEXT,
    kc_type           VARCHAR,
    difficulty_tier   SMALLINT,
    misconceptions    JSONB,
    review_status     VARCHAR,
    content_version   VARCHAR
);

-- 7. CONTENT_UNIT_KCS (M:N bridge)
CREATE TABLE concepttrail.content_unit_kcs (
    content_unit_id      VARCHAR REFERENCES concepttrail.content_unit(content_unit_id),
    kc_id                VARCHAR REFERENCES concepttrail.knowledge_component(kc_id),
    mapping_role         VARCHAR,
    mapping_confidence   NUMERIC,
    review_status        VARCHAR,
    created_at           TIMESTAMPTZ,
    PRIMARY KEY (content_unit_id, kc_id)
);

-- 8. KC_CURRICULUM_MAP (M:N bridge)
CREATE TABLE concepttrail.kc_curriculum_map (
    kc_id          VARCHAR REFERENCES concepttrail.knowledge_component(kc_id),
    item_id        VARCHAR REFERENCES concepttrail.curriculum_item(item_id),
    mapping_role   VARCHAR,
    review_status  VARCHAR,
    created_at     TIMESTAMPTZ,
    PRIMARY KEY (kc_id, item_id)
);

-- 9. KC_EDGE (recursive prerequisite relationship)
CREATE TABLE concepttrail.kc_edge (
    prerequisite_kc_id  VARCHAR REFERENCES concepttrail.knowledge_component(kc_id),
    dependent_kc_id     VARCHAR REFERENCES concepttrail.knowledge_component(kc_id),
    strength            SMALLINT,
    reason              TEXT,
    review_status       VARCHAR,
    PRIMARY KEY (prerequisite_kc_id, dependent_kc_id)
);

-- 10. QUESTIONS
CREATE TABLE concepttrail.questions (
    question_id         VARCHAR PRIMARY KEY,
    item_type           VARCHAR,
    stem                TEXT,
    expected_answer     JSONB,
    rubric              JSONB,
    difficulty          SMALLINT,
    misconception_map   JSONB,
    source_refs         JSONB,
    verification        JSONB,
    review_status       VARCHAR,
    version             INTEGER,
    active              BOOLEAN
);

-- 11. QUESTION_KCS (M:N bridge)
CREATE TABLE concepttrail.question_kcs (
    question_id    VARCHAR REFERENCES concepttrail.questions(question_id),
    kc_id          VARCHAR REFERENCES concepttrail.knowledge_component(kc_id),
    weight         NUMERIC,
    mapping_role   VARCHAR,
    review_status  VARCHAR,
    PRIMARY KEY (question_id, kc_id)
);

-- 12. QUESTION_OPTIONS
CREATE TABLE concepttrail.question_options (
    option_id      UUID PRIMARY KEY,
    question_id    VARCHAR REFERENCES concepttrail.questions(question_id),
    option_key     VARCHAR,
    option_text    TEXT,
    is_correct     BOOLEAN,
    explanation    TEXT,
    display_order  SMALLINT
);

-- 13. NOTE
CREATE TABLE concepttrail.note (
    note_id          UUID PRIMARY KEY,
    kc_id            VARCHAR REFERENCES concepttrail.knowledge_component(kc_id),
    title            TEXT,
    content_markdown TEXT,
    language         VARCHAR,
    note_type        VARCHAR,
    recipe_version   VARCHAR,
    model_id         VARCHAR,
    prompt_version   VARCHAR,
    content_version  VARCHAR,
    review_status    VARCHAR,
    approved_by      UUID,
    approved_at      TIMESTAMPTZ
);

-- 14. USERS
CREATE TABLE concepttrail.users (
    user_id           UUID PRIMARY KEY,
    login_identifier  VARCHAR UNIQUE,
    password_hash     TEXT,
    is_active         BOOLEAN,
    created_at        TIMESTAMPTZ,
    updated_at        TIMESTAMPTZ
);

-- Add NOTE.approved_by FK after USERS exists.
ALTER TABLE concepttrail.note
    ADD CONSTRAINT fk_note_approved_by
    FOREIGN KEY (approved_by) REFERENCES concepttrail.users(user_id);

-- 15. LEARNERS
CREATE TABLE concepttrail.learners (
    learner_id    UUID PRIMARY KEY,
    user_id       UUID UNIQUE REFERENCES concepttrail.users(user_id),
    display_name  VARCHAR,
    created_at    TIMESTAMPTZ
);

-- 16. ROLE
CREATE TABLE concepttrail.role (
    role_code    VARCHAR PRIMARY KEY,
    description  TEXT
);

-- 17. USER_ROLES (M:N bridge)
CREATE TABLE concepttrail.user_roles (
    user_id      UUID REFERENCES concepttrail.users(user_id),
    role_code    VARCHAR REFERENCES concepttrail.role(role_code),
    assigned_at  TIMESTAMPTZ,
    PRIMARY KEY (user_id, role_code)
);

-- 18. ATTEMPTS
CREATE TABLE concepttrail.attempts (
    attempt_id        UUID PRIMARY KEY,
    learner_id        UUID REFERENCES concepttrail.learners(learner_id),
    question_id       VARCHAR REFERENCES concepttrail.questions(question_id),
    question_version  INTEGER,
    submitted_answer  JSONB,
    scored_correct    BOOLEAN,
    score             NUMERIC,
    score_method      VARCHAR,
    hint_tier         SMALLINT,
    attempted_at      TIMESTAMPTZ,
    idempotency_key   VARCHAR UNIQUE
);

-- 19. BKT_CONFIG_VERSION
CREATE TABLE concepttrail.bkt_config_version (
    bkt_config_version  VARCHAR PRIMARY KEY,
    parameters          JSONB,
    effective_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ,
    notes               TEXT
);

-- 20. STUDENT_KC_STATE
CREATE TABLE concepttrail.student_kc_state (
    learner_id           UUID REFERENCES concepttrail.learners(learner_id),
    kc_id                VARCHAR REFERENCES concepttrail.knowledge_component(kc_id),
    mastery_probability  DOUBLE PRECISION,
    bkt_config_version   VARCHAR REFERENCES concepttrail.bkt_config_version(bkt_config_version),
    updated_at           TIMESTAMPTZ,
    evidence_count       INTEGER,
    PRIMARY KEY (learner_id, kc_id)
);

-- 21. EMBEDDING_CHUNK (exact ERD fields; unbounded VECTOR until model selection)
CREATE TABLE concepttrail.embedding_chunk (
    chunk_id            UUID PRIMARY KEY,
    content_unit_id     VARCHAR REFERENCES concepttrail.content_unit(content_unit_id),
    chunk_order         INTEGER,
    chunk_text          TEXT,
    token_count         INTEGER,
    embedding_model_id  VARCHAR,
    embedding           VECTOR,
    index_generation    VARCHAR,
    created_at          TIMESTAMPTZ
);

-- 22. INGESTION_JOB
CREATE TABLE concepttrail.ingestion_job (
    job_id            UUID PRIMARY KEY,
    job_type          VARCHAR,
    pipeline_version  VARCHAR,
    status            VARCHAR,
    created_at        TIMESTAMPTZ,
    started_at        TIMESTAMPTZ,
    finished_at       TIMESTAMPTZ,
    created_by        UUID REFERENCES concepttrail.users(user_id),
    error_summary     TEXT
);

-- 23. INGESTION_JOB_DOCUMENTS (M:N bridge)
CREATE TABLE concepttrail.ingestion_job_documents (
    job_id           UUID REFERENCES concepttrail.ingestion_job(job_id),
    source_id        VARCHAR REFERENCES concepttrail.source_document(source_id),
    document_status  VARCHAR,
    started_at       TIMESTAMPTZ,
    finished_at      TIMESTAMPTZ,
    error_summary    TEXT,
    PRIMARY KEY (job_id, source_id)
);

-- 24. CLASSROOM
CREATE TABLE concepttrail.classroom (
    classroom_id     UUID PRIMARY KEY,
    grade_level      SMALLINT,
    section_label    VARCHAR,
    academic_session VARCHAR,
    school_label     VARCHAR,
    active           BOOLEAN
);

-- 25. CLASS_ENROLLMENTS
CREATE TABLE concepttrail.class_enrollments (
    enrollment_id  UUID PRIMARY KEY,
    learner_id     UUID REFERENCES concepttrail.learners(learner_id),
    classroom_id   UUID REFERENCES concepttrail.classroom(classroom_id),
    enrolled_at    TIMESTAMPTZ,
    ended_at       TIMESTAMPTZ
);

-- 26. TEACHER_CLASS_ASSIGNMENTS
CREATE TABLE concepttrail.teacher_class_assignments (
    classroom_id   UUID REFERENCES concepttrail.classroom(classroom_id),
    user_id        UUID REFERENCES concepttrail.users(user_id),
    assigned_role  VARCHAR,
    assigned_at    TIMESTAMPTZ,
    ended_at       TIMESTAMPTZ,
    PRIMARY KEY (classroom_id, user_id)
);

-- Indexes from the original bootstrap plan; they do not change the ERD.
CREATE INDEX idx_curriculum_item_curriculum_version ON concepttrail.curriculum_item(curriculum_version_id);
CREATE INDEX idx_curriculum_item_subject ON concepttrail.curriculum_item(subject_id);
CREATE INDEX idx_curriculum_item_parent ON concepttrail.curriculum_item(parent_item_id);
CREATE INDEX idx_knowledge_component_subject ON concepttrail.knowledge_component(subject_id);
CREATE INDEX idx_source_document_subject ON concepttrail.source_document(subject_id);
CREATE INDEX idx_source_document_curriculum_version ON concepttrail.source_document(curriculum_version_id);
CREATE INDEX idx_content_unit_source ON concepttrail.content_unit(source_id);
CREATE INDEX idx_content_unit_item ON concepttrail.content_unit(item_id);
CREATE INDEX idx_embedding_chunk_content_unit ON concepttrail.embedding_chunk(content_unit_id);
CREATE INDEX idx_question_options_question ON concepttrail.question_options(question_id);
CREATE INDEX idx_student_kc_state_kc ON concepttrail.student_kc_state(kc_id);
CREATE INDEX idx_attempts_learner ON concepttrail.attempts(learner_id);
CREATE INDEX idx_attempts_question ON concepttrail.attempts(question_id);
CREATE INDEX idx_note_kc ON concepttrail.note(kc_id);
CREATE INDEX idx_ingestion_job_created_by ON concepttrail.ingestion_job(created_by);
CREATE INDEX idx_ingestion_job_documents_source ON concepttrail.ingestion_job_documents(source_id);
CREATE INDEX idx_class_enrollments_learner ON concepttrail.class_enrollments(learner_id);
CREATE INDEX idx_class_enrollments_classroom ON concepttrail.class_enrollments(classroom_id);
CREATE INDEX idx_teacher_class_assignments_user ON concepttrail.teacher_class_assignments(user_id);

COMMIT;
