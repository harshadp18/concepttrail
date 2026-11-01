"""Proposed migration 0003 and its features, on DISPOSABLE databases only.

The persistent database never sees these tables. Covers: the migration is additive and fully
reversible; notifications are off by default, per-user, idempotent and generated from stored
facts; tutor conversation history is off by default, owner-only, ordered and bounded.
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

import app.api.v1.doubts as doubts_api
import app.api.v1.interventions as interventions_api
import app.api.v1.notifications as notifications_api
from app.core.config import get_settings
from app.core.security import hash_password
from app.db.models import (
    ClassEnrollment,
    Classroom,
    KnowledgeComponent,
    Learner,
    Role,
    StudentKcState,
    Subject,
    TeacherClassAssignment,
    User,
    UserRole,
)
from app.db.session import get_db
from app.main import create_app
from app.services import conversations, notifications
from app.services.ai_generation import GroundedResult

pytestmark = pytest.mark.migration_db
NEW_TABLES = {"notification", "doubt_conversation", "doubt_message"}


def test_proposal_0003_is_additive_and_reversible(alembic, fresh_database) -> None:  # noqa: F811
    target = fresh_database()
    command.upgrade(alembic(target), "0001")
    baseline = inspect_database(target)
    cfg = with_proposals(alembic(target))
    command.upgrade(cfg, "0002")
    at_0002 = inspect_database(target)
    command.upgrade(cfg, "0003")
    upgraded = inspect_database(target)
    assert set(upgraded["snapshot"]) - set(at_0002["snapshot"]) == NEW_TABLES
    for name, table in baseline["snapshot"].items():
        assert upgraded["snapshot"][name] == table  # no baseline table changed
    engine = _engine(target)
    user, learner, conv = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with engine.begin() as c:
        c.execute(text("INSERT INTO concepttrail.users (user_id) VALUES (:u)"), {"u": user})
        c.execute(
            text("INSERT INTO concepttrail.learners (learner_id, user_id) VALUES (:l, :u)"),
            {"l": learner, "u": user},
        )
        c.execute(
            text(
                "INSERT INTO concepttrail.doubt_conversation (conversation_id, learner_id,"
                " class_level) VALUES (:c, :l, 7)"
            ),
            {"c": conv, "l": learner},
        )
        c.execute(
            text(
                "INSERT INTO concepttrail.doubt_message (message_id, conversation_id, seq, role,"
                " content) VALUES (:m, :c, 1, 'student', 'q')"
            ),
            {"m": uuid.uuid4(), "c": conv},
        )
        c.execute(
            text(
                "INSERT INTO concepttrail.notification (notification_id, user_id, kind, title,"
                " dedupe_key) VALUES (:n, :u, 'system', 't', 'k1')"
            ),
            {"n": uuid.uuid4(), "u": user},
        )
    bad_statements = [
        # duplicate sequence number, bad role, bad grounding, bad level, bad kind, duplicate key
        "INSERT INTO concepttrail.doubt_message (message_id, conversation_id, seq, role, content)"
        f" VALUES ('{uuid.uuid4()}', '{conv}', 1, 'tutor', 'x')",
        "INSERT INTO concepttrail.doubt_message (message_id, conversation_id, seq, role, content)"
        f" VALUES ('{uuid.uuid4()}', '{conv}', 2, 'teacher', 'x')",
        "INSERT INTO concepttrail.doubt_message (message_id, conversation_id, seq, role, content,"
        f" grounding) VALUES ('{uuid.uuid4()}', '{conv}', 3, 'tutor', 'x', 'maybe')",
        "INSERT INTO concepttrail.doubt_conversation (conversation_id, learner_id, class_level)"
        f" VALUES ('{uuid.uuid4()}', '{learner}', 11)",
        "INSERT INTO concepttrail.notification (notification_id, user_id, kind, title)"
        f" VALUES ('{uuid.uuid4()}', '{user}', 'spam', 't')",
        "INSERT INTO concepttrail.notification (notification_id, user_id, kind, title, dedupe_key)"
        f" VALUES ('{uuid.uuid4()}', '{user}', 'system', 't', 'k1')",
    ]
    for statement in bad_statements:
        with pytest.raises(IntegrityError), engine.begin() as c:
            c.execute(text(statement))
    with engine.begin() as c:  # messages cascade with their conversation
        c.execute(text("DELETE FROM concepttrail.doubt_conversation"))
        assert c.execute(text("SELECT count(*) FROM concepttrail.doubt_message")).scalar() == 0
        c.execute(text("DELETE FROM concepttrail.notification"))
        c.execute(text("DELETE FROM concepttrail.learners"))
        c.execute(text("DELETE FROM concepttrail.users"))
    engine.dispose()
    command.downgrade(cfg, "0002")
    assert set(inspect_database(target)["snapshot"]) == set(at_0002["snapshot"])
    command.downgrade(cfg, "0001")
    assert_is_baseline(inspect_database(target))


@pytest.fixture
def world(fresh_database, alembic):  # noqa: F811
    target = fresh_database()
    command.upgrade(with_proposals(alembic(target)), "0003")
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
        s.add_all(
            [
                Role(role_code="teacher"),
                Role(role_code="student"),
                Subject(subject_id="mathematics", active=True),
            ]
        )
        room = Classroom(classroom_id=uuid.uuid4(), grade_level=7, active=True)
        teachers = [user(f"t{i}@example.invalid", "teacher-password-123") for i in range(2)]
        students = [user(f"stu{i}", "12345678") for i in range(4)]
        s.add_all([room, *teachers, *students])
        s.flush()
        learners = [Learner(learner_id=uuid.uuid4(), user_id=u.user_id) for u in students]
        s.add_all(
            [
                *learners,
                *[UserRole(user_id=u.user_id, role_code="student") for u in students],
                *[UserRole(user_id=t.user_id, role_code="teacher") for t in teachers],
                *[
                    TeacherClassAssignment(
                        classroom_id=room.classroom_id, user_id=t.user_id, assigned_at=now
                    )
                    for t in teachers
                ],
                KnowledgeComponent(
                    kc_id="KC1",
                    subject_id="mathematics",
                    stable_key="n.kc1",
                    name="Fractions",
                    review_status="approved",
                ),
            ]
        )
        s.flush()
        for learner in learners:
            s.add(
                ClassEnrollment(
                    enrollment_id=uuid.uuid4(),
                    learner_id=learner.learner_id,
                    classroom_id=room.classroom_id,
                    enrolled_at=now,
                )
            )
        s.commit()
        ids = {
            "room": room.classroom_id,
            "teachers": [t.user_id for t in teachers],
            "learners": [x.learner_id for x in learners],
        }
    yield engine, ids
    engine.dispose()


def make_client(engine, monkeypatch, **flags):
    settings = get_settings().model_copy(
        update={"rag_index_generation": "ig-disposable", "doubt_requests_per_hour": 100, **flags}
    )
    for module in (notifications_api, interventions_api, doubts_api):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    app = create_app()

    def db():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[doubts_api.get_llm] = lambda: object()
    app.dependency_overrides[doubts_api.get_embedder] = lambda: object()
    return TestClient(app)


def login(client, who, secret):
    r = client.post("/api/v1/auth/login", json={"login_identifier": who, "credential": secret})
    assert r.status_code == 200, r.json()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_features_are_off_by_default(world, monkeypatch) -> None:
    engine, _ids = world
    client = make_client(engine, monkeypatch)
    teacher = login(client, "t0@example.invalid", "teacher-password-123")
    student = login(client, "stu0", "12345678")
    for path in ("/api/v1/notifications",):
        r = client.get(path, headers=teacher)
        assert r.status_code == 503 and r.json()["error"]["code"] == "feature_not_enabled"
    for path in ("/api/v1/student/doubts/conversations",):
        r = client.get(path, headers=student)
        assert r.status_code == 503 and r.json()["error"]["code"] == "feature_not_enabled"


def test_notifications_are_private_idempotent_and_marked_read(world, monkeypatch) -> None:
    engine, ids = world
    with Session(engine) as s:
        a, b = ids["teachers"]
        first = notifications.create(
            s, a, "system", "Hello", classroom_id=ids["room"], dedupe_key="k", synthetic=True
        )
        assert first is not None
        assert notifications.create(s, a, "system", "Hello", dedupe_key="k") is None  # replay
        assert notifications.create(s, b, "system", "Hello", dedupe_key="k") is not None
        with pytest.raises(notifications.NotificationError):
            notifications.create(s, a, "advert", "x")
        s.commit()
        nid = first.notification_id
    client = make_client(engine, monkeypatch, notifications_enabled=True)
    ta = login(client, "t0@example.invalid", "teacher-password-123")
    tb = login(client, "t1@example.invalid", "teacher-password-123")
    listed = client.get("/api/v1/notifications", headers=ta).json()
    assert listed["count"] == 1 and listed["unread_count"] == 1
    assert listed["notifications"][0]["is_synthetic"] is True  # labelled as demo data
    assert client.post(f"/api/v1/notifications/{nid}/read", headers=tb).status_code == 404
    done = client.post(f"/api/v1/notifications/{nid}/read", headers=ta)
    assert done.status_code == 200 and done.json()["read_at"]
    again = client.post(f"/api/v1/notifications/{nid}/read", headers=ta).json()
    assert again["read_at"] == done.json()["read_at"]  # idempotent
    assert client.get("/api/v1/notifications?unread_only=true", headers=ta).json()["count"] == 0
    assert client.get("/api/v1/notifications?unread_only=true", headers=tb).json()["count"] == 1
    assert client.post("/api/v1/notifications/read-all", headers=tb).json() == {"marked_read": 1}
    assert client.get("/api/v1/notifications").status_code == 401


def test_intervention_notifies_only_the_other_teacher_of_the_class(world, monkeypatch) -> None:
    engine, ids = world
    client = make_client(
        engine, monkeypatch, notifications_enabled=True, interventions_enabled=True
    )
    ta = login(client, "t0@example.invalid", "teacher-password-123")
    tb = login(client, "t1@example.invalid", "teacher-password-123")
    base = f"/api/v1/teacher/classes/{ids['room']}/interventions"
    made = client.post(base, headers=ta, json={"intervention_type": "reteach", "kc_id": "KC1"})
    assert made.status_code == 201
    assert client.get("/api/v1/notifications", headers=ta).json()["count"] == 0  # not the actor
    other = client.get("/api/v1/notifications", headers=tb).json()
    assert other["count"] == 1 and other["notifications"][0]["kind"] == "intervention_update"
    iid = made.json()["intervention_id"]
    client.post(f"{base}/{iid}/status", headers=ta, json={"status": "completed"})
    assert client.get("/api/v1/notifications", headers=tb).json()["count"] == 2


def test_class_alerts_come_from_stored_mastery_and_are_idempotent(world) -> None:
    engine, ids = world
    now = datetime.now(UTC)
    with Session(engine) as s:
        for learner, p in zip(ids["learners"], (0.2, 0.3, 0.1, 0.9), strict=True):
            s.add(
                StudentKcState(
                    learner_id=learner,
                    kc_id="KC1",
                    mastery_probability=Decimal(str(p)),
                    evidence_count=5,
                    updated_at=now,
                )
            )
        s.commit()
        written = notifications.generate_class_alerts(s, ids["room"], ids["learners"], today=now)
        assert written == 2  # one per teacher; 3 of 4 learners are below the cut-off
        assert notifications.generate_class_alerts(s, ids["room"], ids["learners"], today=now) == 0
        # too few learners with evidence: no alert
        assert (
            notifications.generate_class_alerts(s, ids["room"], ids["learners"][:2], today=now) == 0
        )
        s.commit()


def fake_explain(status="ok"):
    def run(session, question, **kwargs):
        calls.append(kwargs.get("retrieval_context"))
        if status != "ok":
            return GroundedResult(status)
        return GroundedResult(
            "ok",
            output={
                "concept": "c",
                "explanation": f"Answer to {question}",
                "steps": [],
                "hint": "",
            },
            citations=[
                {
                    "label": "E1",
                    "source_id": "SRC-X",
                    "pdf_page_index": 3,
                    "printed_page_label": "4",
                    "item_title": "t",
                }
            ],
            model_id="fake:model",
        )

    return run


calls: list = []


def test_conversation_history_is_ordered_owner_only_and_followups_use_context(
    world, monkeypatch
) -> None:
    engine, ids = world
    calls.clear()
    client = make_client(engine, monkeypatch, doubt_history_enabled=True)
    monkeypatch.setattr("app.services.learning.explain_for_learner", fake_explain())
    a = login(client, "stu0", "12345678")
    b = login(client, "stu1", "12345678")
    first = client.post("/api/v1/doubts", headers=a, json={"question": "What is a fraction?"})
    assert first.status_code == 200, first.json()
    cid = first.json()["conversation_id"]
    assert cid and calls == [None]  # first turn has no earlier context
    follow = client.post(
        "/api/v1/doubts", headers=a, json={"question": "Why does it work?", "conversation_id": cid}
    )
    assert follow.status_code == 200 and follow.json()["conversation_id"] == cid
    assert calls[1] == "What is a fraction?"  # earlier student question, retrieval only
    detail = client.get(f"/api/v1/student/doubts/conversations/{cid}", headers=a).json()
    assert [m["seq"] for m in detail["messages"]] == [1, 2, 3, 4]
    assert [m["role"] for m in detail["messages"]] == ["student", "tutor", "student", "tutor"]
    assert detail["messages"][1]["citations"][0]["label"] == "E1"
    assert detail["messages"][1]["grounding"] == "grounded"
    # another learner can neither read, continue nor archive it
    assert client.get(f"/api/v1/student/doubts/conversations/{cid}", headers=b).status_code == 404
    hijack = client.post(
        "/api/v1/doubts", headers=b, json={"question": "Why does it work?", "conversation_id": cid}
    )
    assert hijack.status_code == 404 and hijack.json()["error"]["code"] == "conversation_not_found"
    assert (
        client.post(f"/api/v1/student/doubts/conversations/{cid}/archive", headers=b).status_code
        == 404
    )
    assert client.get("/api/v1/student/doubts/conversations", headers=b).json()["count"] == 0
    listed = client.get("/api/v1/student/doubts/conversations", headers=a).json()
    assert listed["count"] == 1 and listed["conversations"][0]["conversation_id"] == cid
    assert (
        client.post(f"/api/v1/student/doubts/conversations/{cid}/archive", headers=a).status_code
        == 204
    )
    assert client.get("/api/v1/student/doubts/conversations", headers=a).json()["count"] == 0
    teacher = login(client, "t0@example.invalid", "teacher-password-123")
    assert client.get("/api/v1/student/doubts/conversations", headers=teacher).status_code == 403


def test_abstentions_are_stored_as_abstentions_and_history_is_bounded(world, monkeypatch) -> None:
    engine, ids = world
    client = make_client(engine, monkeypatch, doubt_history_enabled=True)
    monkeypatch.setattr(
        "app.services.learning.explain_for_learner", fake_explain("insufficient_evidence")
    )
    a = login(client, "stu0", "12345678")
    first = client.post("/api/v1/doubts", headers=a, json={"question": "Who won the cricket?"})
    cid = first.json()["conversation_id"]
    assert first.json()["grounding"] == "abstained"
    stored = client.get(f"/api/v1/student/doubts/conversations/{cid}", headers=a).json()
    tutor = stored["messages"][1]
    assert tutor["grounding"] == "abstained" and tutor["citations"] == []
    assert tutor["status"] == "insufficient_evidence"
    for _ in range(conversations.MAX_TURNS // 2 - 1):
        assert (
            client.post(
                "/api/v1/doubts",
                headers=a,
                json={"question": "Who won the cricket?", "conversation_id": cid},
            ).status_code
            == 200
        )
    full = client.post(
        "/api/v1/doubts",
        headers=a,
        json={"question": "One more question", "conversation_id": cid},
    )
    assert full.status_code == 409 and full.json()["error"]["code"] == "conversation_full"
    with Session(engine) as s:  # the refused turn left no half-written exchange
        assert len(conversations.messages(s, uuid.UUID(cid))) == conversations.MAX_TURNS


def test_history_off_keeps_doubts_stateless(world, monkeypatch) -> None:
    engine, _ids = world
    client = make_client(engine, monkeypatch)
    monkeypatch.setattr("app.services.learning.explain_for_learner", fake_explain())
    a = login(client, "stu0", "12345678")
    r = client.post("/api/v1/doubts", headers=a, json={"question": "What is a fraction?"})
    assert r.status_code == 200 and r.json()["conversation_id"] is None
    ignored = client.post(
        "/api/v1/doubts",
        headers=a,
        json={"question": "What is a fraction?", "conversation_id": str(uuid.uuid4())},
    )
    assert ignored.status_code == 200 and ignored.json()["conversation_id"] is None
    with Session(engine) as s:
        assert s.execute(text("SELECT count(*) FROM concepttrail.doubt_message")).scalar() == 0
