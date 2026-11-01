"""Concurrent attempts on a DISPOSABLE PostgreSQL database (real connections, real row locks).

Same disposable-server guard as test_migrations.py: a fresh database is built with Alembic, used
by several threads with their own sessions, and dropped. Verifies that concurrent attempts by
one learner on one KC serialise on the `student_kc_state` row lock (every event applied exactly
once, final mastery equal to a sequential replay) and that one idempotency key yields one attempt.
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_migrations import _engine, admin_url, alembic, fresh_database  # noqa: F401

from app.db.models import (
    Attempt,
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
    StudentKcState,
    Subject,
    User,
    UserRole,
)
from app.services.attempt_service import AttemptError, submit_attempt
from app.services.bkt_service import BKTParameters, update_mastery

pytestmark = pytest.mark.migration_db
PARAMS = {"p_l0": 0.2, "p_t": 0.1, "p_g": 0.2, "p_s": 0.1}


def seed(engine, n_questions: int) -> tuple[uuid.UUID, list[str]]:
    now = datetime.now(UTC)
    with Session(engine) as s:
        s.add_all([Role(role_code="student"), Subject(subject_id="mathematics", active=True)])
        user = User(user_id=uuid.uuid4(), login_identifier="conc-student", is_active=True)
        room = Classroom(classroom_id=uuid.uuid4(), grade_level=7, active=True)
        s.add_all([user, room])
        s.flush()
        learner = Learner(learner_id=uuid.uuid4(), user_id=user.user_id)
        s.add_all([learner, UserRole(user_id=user.user_id, role_code="student")])
        s.flush()
        s.add(
            ClassEnrollment(
                enrollment_id=uuid.uuid4(),
                learner_id=learner.learner_id,
                classroom_id=room.classroom_id,
                enrolled_at=now,
            )
        )
        s.add(CurriculumVersion(curriculum_version_id="V7", class_level=7, status="published"))
        s.add(
            KnowledgeComponent(
                kc_id="KC1",
                subject_id="mathematics",
                stable_key="conc.kc1",
                name="KC1",
                review_status="approved",
            )
        )
        s.add(
            BktConfigVersion(
                bkt_config_version="conc-v1",
                parameters=PARAMS,
                effective_at=now - timedelta(days=1),
                created_at=now,
            )
        )
        s.flush()
        s.add(
            CurriculumItem(
                item_id="I7",
                curriculum_version_id="V7",
                subject_id="mathematics",
                status="published",
            )
        )
        s.flush()
        s.add(KcCurriculumMap(kc_id="KC1", item_id="I7", review_status="approved"))
        qids = []
        for n in range(n_questions):
            qid = f"Q{n}"
            s.add(
                Question(
                    question_id=qid,
                    item_type="single_choice",
                    stem=f"q{n}",
                    review_status="approved",
                    version=1,
                    active=True,
                    difficulty=2,
                )
            )
            s.flush()
            for key in "AB":
                s.add(
                    QuestionOption(
                        option_id=uuid.uuid4(),
                        question_id=qid,
                        option_key=key,
                        option_text=key,
                        is_correct=key == "A",
                        display_order=1,
                    )
                )
            s.add(
                QuestionKc(
                    question_id=qid, kc_id="KC1", weight=Decimal("1"), review_status="approved"
                )
            )
            qids.append(qid)
        s.commit()
        return learner.learner_id, qids


def submit(engine, learner_id, qid, key, answer="A"):
    with Session(engine) as s:
        try:
            out = submit_attempt(
                s,
                learner_id,
                question_id=qid,
                question_version=1,
                submitted_answer={"option_key": answer},
                hint_tier=0,
                idempotency_key=key,
            )
            return out.duplicate_replay, out.mastery.reason if out.mastery else None
        except AttemptError as exc:
            return "error", exc.code


@pytest.fixture
def database(fresh_database, alembic):  # noqa: F811
    target = fresh_database()
    command.upgrade(alembic(target), "head")
    engine = _engine(target, connect_args={"options": "-c search_path=concepttrail,public"})
    yield engine
    engine.dispose()


def test_concurrent_attempts_on_one_kc_apply_every_event_once(database) -> None:
    learner, qids = seed(database, 16)
    answers = ["A" if i % 3 else "B" for i in range(16)]
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(
            pool.map(
                lambda i: submit(
                    database, learner, qids[i], f"conc-key-{i:04d}-xxxxxxxx", answers[i]
                ),
                range(16),
            )
        )
    with Session(database) as s:
        attempts = s.scalars(
            select(Attempt).order_by(Attempt.attempted_at, Attempt.attempt_id)
        ).all()
        state = s.get(StudentKcState, (learner, "KC1"))
    assert len(attempts) == 16
    # The (learner, KC) lock is taken before each attempt is timestamped, so every event is
    # applied exactly once and in commit order: no skips, no reconciliation backlog.
    assert [reason for _dup, reason in results] == [None] * 16
    assert state.evidence_count == 16
    params = BKTParameters.from_mapping(PARAMS)
    value = params.initial_knowledge
    for a in attempts:
        value = update_mastery(value, bool(a.scored_correct), params)
    assert abs(float(state.mastery_probability) - value) < 1e-9


def test_one_idempotency_key_yields_one_attempt_under_a_race(database) -> None:
    learner, qids = seed(database, 1)
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(
            pool.map(
                lambda _: submit(database, learner, qids[0], "conc-same-key-0000000"), range(12)
            )
        )
    with Session(database) as s:
        count = s.scalar(select(func.count()).select_from(Attempt))
        state = s.get(StudentKcState, (learner, "KC1"))
    assert count == 1
    assert sum(1 for dup, _ in results if dup is False) == 1
    assert all(dup in (True, False) for dup, _ in results)  # replays, not errors
    assert state.evidence_count == 1
