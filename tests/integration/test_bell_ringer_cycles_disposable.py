"""Proposed migration 0004 (`bell_ringer_cycle`) and the cycle API, on DISPOSABLE databases only.

Covers: the migration is additive and reversible and allows one open cycle per class and topic;
cycles are topic-specific, idempotent, follow a fixed status order, keep a baseline and report a
follow-up computed from persisted state; another teacher's class is refused.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_intervention_migration_proposal import with_proposals
from test_migrations import (  # noqa: F401  (fixtures)
    _engine,
    admin_url,
    alembic,
    assert_is_baseline,
    fresh_database,
    inspect_database,
)

import app.api.v1.bell_ringer as bell_ringer_api
import app.services.bell_ringer as bell_ringer_service
from app.core.config import get_settings
from app.core.security import hash_password
from app.db.models import (
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
    TeacherClassAssignment,
    User,
    UserRole,
)
from app.db.session import get_db
from app.main import create_app

pytestmark = pytest.mark.migration_db


def test_proposal_0004_is_additive_reversible_and_one_open_per_topic(alembic, fresh_database):  # noqa: F811
    target = fresh_database()
    cfg = with_proposals(alembic(target))
    command.upgrade(cfg, "0003")
    before = inspect_database(target)
    command.upgrade(cfg, "0004")
    after = inspect_database(target)
    assert set(after["snapshot"]) - set(before["snapshot"]) == {"bell_ringer_cycle"}
    for name, table in before["snapshot"].items():
        assert after["snapshot"][name] == table  # nothing existing changed
    engine = _engine(target)
    user, room = uuid.uuid4(), uuid.uuid4()
    insert = (
        "INSERT INTO concepttrail.bell_ringer_cycle (cycle_id, classroom_id, kc_id, created_by,"
        " status) VALUES (:c, :r, :k, :u, :s)"
    )
    with engine.begin() as c:
        c.execute(text("INSERT INTO concepttrail.users (user_id) VALUES (:u)"), {"u": user})
        c.execute(
            text("INSERT INTO concepttrail.classroom (classroom_id) VALUES (:r)"), {"r": room}
        )
        c.execute(text("INSERT INTO concepttrail.subject (subject_id) VALUES ('mathematics')"))
        for kc in ("K1", "K2"):
            c.execute(
                text(
                    "INSERT INTO concepttrail.knowledge_component (kc_id, subject_id, stable_key,"
                    " name) VALUES (:k, 'mathematics', :k, :k)"
                ),
                {"k": kc},
            )
        base = {"r": room, "u": user}
        c.execute(text(insert), {**base, "c": uuid.uuid4(), "k": "K1", "s": "planned"})
        c.execute(text(insert), {**base, "c": uuid.uuid4(), "k": "K2", "s": "in_progress"})
        c.execute(text(insert), {**base, "c": uuid.uuid4(), "k": "K1", "s": "completed"})
    for status in ("planned", "in_progress"):  # a second OPEN cycle for K1 is refused
        with pytest.raises(IntegrityError), engine.begin() as c:
            c.execute(text(insert), {**base, "c": uuid.uuid4(), "k": "K1", "s": status})
    with pytest.raises(IntegrityError), engine.begin() as c:
        c.execute(text(insert), {**base, "c": uuid.uuid4(), "k": "K2", "s": "maybe"})
    with engine.begin() as c:
        c.execute(text("DELETE FROM concepttrail.bell_ringer_cycle"))
        c.execute(text("DELETE FROM concepttrail.knowledge_component"))
        c.execute(text("DELETE FROM concepttrail.subject"))
        c.execute(text("DELETE FROM concepttrail.classroom"))
        c.execute(text("DELETE FROM concepttrail.users"))
    engine.dispose()
    command.downgrade(cfg, "0003")
    assert set(inspect_database(target)["snapshot"]) == set(before["snapshot"])
    command.downgrade(cfg, "0001")
    assert_is_baseline(inspect_database(target))


@pytest.fixture
def world(fresh_database, alembic):  # noqa: F811
    target = fresh_database()
    command.upgrade(with_proposals(alembic(target)), "0004")
    engine = _engine(target, connect_args={"options": "-c search_path=concepttrail,public"})
    now = datetime.now(UTC)

    def user(name: str, secret: str) -> User:
        return User(
            user_id=uuid.uuid4(),
            login_identifier=name,
            password_hash=hash_password(secret),
            is_active=True,
            created_at=now,
            updated_at=now,
        )

    with Session(engine) as s:
        s.add_all([Role(role_code="teacher"), Role(role_code="student")])
        s.add(Subject(subject_id="mathematics", display_name="Mathematics", active=True))
        s.flush()
        s.add(
            CurriculumVersion(
                curriculum_version_id="V7",
                board="SYN",
                class_level=7,
                academic_session="2026-27",
                status="published",
            )
        )
        s.flush()
        s.add(
            CurriculumItem(
                item_id="I7",
                curriculum_version_id="V7",
                subject_id="mathematics",
                title="Fractions",
                status="published",
            )
        )
        rooms = [Classroom(classroom_id=uuid.uuid4(), grade_level=7, active=True) for _ in "ab"]
        teachers = [user(f"t{i}@example.invalid", "teacher-password-123") for i in range(2)]
        students = [user(f"stu{i}", "12345678") for i in range(4)]
        s.add_all([*rooms, *teachers, *students])
        s.flush()
        for kc in ("KA", "KB"):
            s.add(
                KnowledgeComponent(
                    kc_id=kc,
                    subject_id="mathematics",
                    stable_key=kc.lower(),
                    name=f"Topic {kc}",
                    review_status="approved",
                )
            )
            s.flush()
            s.add(KcCurriculumMap(kc_id=kc, item_id="I7", review_status="approved"))
            for n in (1, 2):
                qid = f"Q-{kc}-{n}"
                s.add(
                    Question(
                        question_id=qid,
                        item_type="single_choice",
                        stem=f"{kc} question {n}",
                        difficulty=n,
                        review_status="approved",
                        version=1,
                        active=True,
                    )
                )
                s.flush()
                for order, key in enumerate("ABCD", start=1):
                    s.add(
                        QuestionOption(
                            option_id=uuid.uuid4(),
                            question_id=qid,
                            option_key=key,
                            option_text=f"{key}",
                            is_correct=key == "B",
                            display_order=order,
                        )
                    )
                s.add(
                    QuestionKc(
                        question_id=qid,
                        kc_id=kc,
                        weight=Decimal("1"),
                        mapping_role="primary",
                        review_status="approved",
                    )
                )
        learners = [
            Learner(learner_id=uuid.uuid4(), user_id=u.user_id, display_name=f"L{i}")
            for i, u in enumerate(students)
        ]
        s.add_all(
            [
                *learners,
                *[UserRole(user_id=u.user_id, role_code="student") for u in students],
                *[UserRole(user_id=t.user_id, role_code="teacher") for t in teachers],
                TeacherClassAssignment(
                    classroom_id=rooms[0].classroom_id, user_id=teachers[0].user_id, assigned_at=now
                ),
                TeacherClassAssignment(
                    classroom_id=rooms[1].classroom_id, user_id=teachers[1].user_id, assigned_at=now
                ),
            ]
        )
        s.flush()
        for learner in learners:
            s.add(
                ClassEnrollment(
                    enrollment_id=uuid.uuid4(),
                    learner_id=learner.learner_id,
                    classroom_id=rooms[0].classroom_id,
                    enrolled_at=now,
                )
            )
        # KA: three of four learners weak with evidence; KB: two weak of three
        for learner, (pa, pb) in zip(
            learners, ((0.2, 0.3), (0.25, 0.35), (0.3, 0.9), (0.9, None)), strict=True
        ):
            for kc, p in (("KA", pa), ("KB", pb)):
                if p is not None:
                    s.add(
                        StudentKcState(
                            learner_id=learner.learner_id,
                            kc_id=kc,
                            mastery_probability=p,
                            evidence_count=3,
                            updated_at=now,
                        )
                    )
        s.commit()
        ids = {
            "rooms": [r.classroom_id for r in rooms],
            "learners": [x.learner_id for x in learners],
        }
    yield engine, ids
    engine.dispose()


def make_client(engine, monkeypatch, **flags):
    settings = get_settings().model_copy(update=flags)
    for module in (bell_ringer_api, bell_ringer_service):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    app = create_app()

    def db():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_db] = db
    return TestClient(app)


def login(client, who, secret):
    r = client.post("/api/v1/auth/login", json={"login_identifier": who, "credential": secret})
    assert r.status_code == 200, r.json()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_cycles_are_topic_specific_idempotent_and_followed_up(world, monkeypatch) -> None:
    engine, ids = world
    client = make_client(engine, monkeypatch, bell_ringer_enabled=True)
    teacher = login(client, "t0@example.invalid", "teacher-password-123")
    room = ids["rooms"][0]
    base = f"/api/v1/teacher/classes/{room}/bell-ringer/cycles"
    topics = client.get(f"/api/v1/teacher/classes/{room}/bell-ringer/topics", headers=teacher)
    flagged = [t["kc_id"] for t in topics.json()["topics"] if t["flagged"]]
    assert flagged == ["KA", "KB"] and topics.json()["cycles_enabled"] is True

    first = client.post(base, json={"kc_id": "KA", "note": "pairs"}, headers=teacher)
    assert first.status_code == 201 and first.json()["created"] is True
    cycle = first.json()
    assert cycle["status"] == "planned" and cycle["affected_count"] == 3
    assert cycle["baseline"]["learners_below_threshold"] == 3
    assert cycle["baseline"]["enrolled_learners"] == 4
    assert cycle["board_question_id"] == "Q-KA-1" and cycle["bridge_question_id"] == "Q-KA-2"
    again = client.post(base, json={"kc_id": "KA"}, headers=teacher)
    assert again.status_code == 200 and again.json()["cycle_id"] == cycle["cycle_id"]
    other_topic = client.post(base, json={"kc_id": "KB"}, headers=teacher)
    assert other_topic.status_code == 201 and other_topic.json()["cycle_id"] != cycle["cycle_id"]
    listed = client.get(base, headers=teacher).json()
    assert listed["count"] == 2 and {c["kc_id"] for c in listed["cycles"]} == {"KA", "KB"}
    missing = client.post(base, json={"kc_id": "NOPE"}, headers=teacher)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "topic_not_found"

    cid = cycle["cycle_id"]
    started = client.post(f"{base}/{cid}/status", json={"status": "in_progress"}, headers=teacher)
    assert started.status_code == 200 and started.json()["started_at"]
    with Session(engine) as s:  # one affected learner recovers after the warm-up
        state = s.get(StudentKcState, (ids["learners"][0], "KA"))
        state.mastery_probability = Decimal("0.7")
        s.commit()
    detail = client.get(f"{base}/{cid}", headers=teacher).json()
    follow = detail["follow_up"]
    assert follow["affected_at_start"] == 3 and follow["now_at_or_above_cut_off"] == 1
    recovered = [x for x in follow["learners"] if x["now_at_or_above_cut_off"]]
    assert [x["mastery_at_start"] for x in recovered] == [0.2]
    assert detail["activity"]["board_question"]["question_id"] == "Q-KA-1"
    done = client.post(f"{base}/{cid}/status", json={"status": "completed"}, headers=teacher)
    assert done.status_code == 200 and done.json()["completed_at"]
    back = client.post(f"{base}/{cid}/status", json={"status": "in_progress"}, headers=teacher)
    assert back.status_code == 409 and back.json()["error"]["code"] == "invalid_transition"
    reopened = client.post(
        base, json={"kc_id": "KA"}, headers=teacher
    )  # a new cycle after completion
    assert reopened.status_code == 201 and reopened.json()["cycle_id"] != cid


def test_cycles_are_refused_for_another_teachers_class(world, monkeypatch) -> None:
    engine, ids = world
    client = make_client(engine, monkeypatch, bell_ringer_enabled=True)
    owner = login(client, "t0@example.invalid", "teacher-password-123")
    other = login(client, "t1@example.invalid", "teacher-password-123")
    room = ids["rooms"][0]
    base = f"/api/v1/teacher/classes/{room}/bell-ringer/cycles"
    cid = client.post(base, json={"kc_id": "KA"}, headers=owner).json()["cycle_id"]
    for r in (
        client.get(base, headers=other),
        client.post(base, json={"kc_id": "KA"}, headers=other),
        client.get(f"{base}/{cid}", headers=other),
        client.post(f"{base}/{cid}/status", json={"status": "cancelled"}, headers=other),
    ):
        assert r.status_code == 403
    other_room = ids["rooms"][1]
    wrong_class = client.get(
        f"/api/v1/teacher/classes/{other_room}/bell-ringer/cycles/{cid}", headers=other
    )
    assert wrong_class.status_code == 404  # a cycle is only visible through its own class
    student = login(client, "stu0", "12345678")
    assert client.get(base, headers=student).status_code == 403
