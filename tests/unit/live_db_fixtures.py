"""Live PostgreSQL fixtures for owner-service tests. Imported explicitly by test modules.

Every test runs inside an outer transaction on the verified LOCAL development database and is
always rolled back, so nothing persists. Synthetic records are marked `SYNTHETIC-DEV-ONLY`.
Tests skip when the local development database is not available.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.models import (
    BktConfigVersion,
    ClassEnrollment,
    Classroom,
    CurriculumItem,
    CurriculumVersion,
    KcCurriculumMap,
    KnowledgeComponent,
    Learner,
    Question,
    QuestionKc,
    QuestionOption,
    Role,
    Subject,
    TeacherClassAssignment,
    User,
    UserRole,
)

MARK = "SYNTHETIC-DEV-ONLY"


@pytest.fixture(scope="session")
def live_engine():
    from app.db.session import create_db_engine
    from scripts.seed_dev_auth import preflight

    try:
        engine = create_db_engine()
        pre = preflight(engine)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"local development database unavailable: {type(exc).__name__}")
    if not pre.ok:
        pytest.skip(f"not the verified local development database: {pre.problems}")
    return engine


@pytest.fixture(name="pg")
def pg_fixture(live_engine) -> Iterator[Session]:
    connection = live_engine.connect()
    outer = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        connection.close()


class World:
    """A synthetic classroom with one student, one teacher, KCs and approved questions."""

    def __init__(self, session: Session) -> None:
        self.s = session
        tag = uuid.uuid4().hex[:8]
        self.tag = tag
        now = datetime.now(UTC)
        for code in ("student", "teacher"):
            if session.get(Role, code) is None:
                session.add(Role(role_code=code, description=MARK))
        if session.get(Subject, "mathematics") is None:
            session.add(Subject(subject_id="mathematics", display_name="Mathematics", active=True))
        self.pin = "13572468"
        self.password = f"teacher-{tag}-password"
        self.student_user = User(
            user_id=uuid.uuid4(),
            login_identifier=f"syn-student-{tag}",
            password_hash=hash_password(self.pin),
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        self.teacher_user = User(
            user_id=uuid.uuid4(),
            login_identifier=f"syn-teacher-{tag}@example.invalid",
            password_hash=hash_password(self.password),
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        session.add_all([self.student_user, self.teacher_user])
        session.flush()
        self.learner = Learner(
            learner_id=uuid.uuid4(),
            user_id=self.student_user.user_id,
            display_name=MARK,
            created_at=now,
        )
        self.classroom = Classroom(
            classroom_id=uuid.uuid4(),
            grade_level=7,
            section_label="SYN",
            academic_session="2026-27",
            school_label=MARK,
            active=True,
        )
        session.add_all(
            [
                self.learner,
                self.classroom,
                UserRole(user_id=self.student_user.user_id, role_code="student"),
                UserRole(user_id=self.teacher_user.user_id, role_code="teacher"),
            ]
        )
        session.flush()
        session.add_all(
            [
                ClassEnrollment(
                    enrollment_id=uuid.uuid4(),
                    learner_id=self.learner.learner_id,
                    classroom_id=self.classroom.classroom_id,
                    enrolled_at=now,
                ),
                TeacherClassAssignment(
                    classroom_id=self.classroom.classroom_id,
                    user_id=self.teacher_user.user_id,
                    assigned_at=now,
                ),
            ]
        )
        self.items: dict[int, str] = {}
        self.kc_a = self.kc("A")
        self.kc_b = self.kc("B")
        session.flush()

    def grade_item(self, level: int) -> str:
        """A published synthetic chapter at `level` (learner scope is derived from these)."""
        if level not in self.items:
            vid, item = f"SYN-WV{level}-{self.tag}", f"SYN-WI{level}-{self.tag}"
            self.s.add(
                CurriculumVersion(
                    curriculum_version_id=vid,
                    board="SYN",
                    class_level=level,
                    academic_session="2026-27",
                    status="published",
                )
            )
            self.s.flush()
            self.s.add(
                CurriculumItem(
                    item_id=item,
                    curriculum_version_id=vid,
                    subject_id="mathematics",
                    title=f"{MARK} chapter",
                    status="published",
                )
            )
            self.s.flush()
            self.items[level] = item
        return self.items[level]

    def kc(self, letter: str, status: str = "approved", grade: int | None = 7) -> str:
        kc_id = f"SYN-{self.tag}-{letter}"
        self.s.add(
            KnowledgeComponent(
                kc_id=kc_id,
                subject_id="mathematics",
                stable_key=f"syn.{self.tag}.{letter.lower()}",
                name=f"{MARK} KC {letter}",
                review_status=status,
                content_version="kc-v1",
            )
        )
        self.s.flush()
        if grade is not None:
            self.s.add(
                KcCurriculumMap(
                    kc_id=kc_id, item_id=self.grade_item(grade), review_status="approved"
                )
            )
            self.s.flush()
        return kc_id

    def config(self, version: str, effective: datetime, **params: float) -> None:
        values = {"p_l0": 0.3, "p_t": 0.15, "p_g": 0.2, "p_s": 0.1, **params}
        self.s.add(
            BktConfigVersion(
                bkt_config_version=f"{version}-{self.tag}",
                parameters=values,
                effective_at=effective,
                created_at=effective,
                notes=MARK,
            )
        )
        self.s.flush()

    def question(
        self,
        kc_ids: list[str],
        *,
        correct: str = "B",
        difficulty: int = 2,
        status: str = "approved",
        mapping_status: str = "approved",
    ) -> str:
        qid = f"QSYN-{self.tag}-{uuid.uuid4().hex[:6]}"
        self.s.add(
            Question(
                question_id=qid,
                item_type="single_choice",
                stem=f"{MARK} question",
                difficulty=difficulty,
                review_status=status,
                version=1,
                active=True,
                verification={"synthetic": True},
            )
        )
        self.s.flush()
        for order, key in enumerate("ABCD", start=1):
            self.s.add(
                QuestionOption(
                    option_id=uuid.uuid4(),
                    question_id=qid,
                    option_key=key,
                    option_text=f"option {key}",
                    is_correct=key == correct,
                    display_order=order,
                )
            )
        for kc_id in kc_ids:
            self.s.add(
                QuestionKc(
                    question_id=qid,
                    kc_id=kc_id,
                    weight=Decimal("1"),
                    mapping_role="primary",
                    review_status=mapping_status,
                )
            )
        self.s.flush()
        return qid
