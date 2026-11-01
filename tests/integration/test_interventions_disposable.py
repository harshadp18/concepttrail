"""Interventions end to end on a DISPOSABLE database with the PROPOSED migration applied.

The persistent database never sees the `teacher_intervention` table. Covers: disabled by default
(503), teacher-of-class only, learner must be enrolled in the class, status transitions, and
class isolation between teachers.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_intervention_migration_proposal import with_proposals
from test_migrations import _engine, admin_url, alembic, fresh_database  # noqa: F401

import app.api.v1.interventions as interventions_api
from app.core.config import get_settings
from app.core.security import hash_password
from app.db.models import (
    ClassEnrollment,
    Classroom,
    KnowledgeComponent,
    Learner,
    Role,
    Subject,
    TeacherClassAssignment,
    User,
    UserRole,
)
from app.db.session import get_db
from app.main import create_app

pytestmark = pytest.mark.migration_db


@pytest.fixture
def world(fresh_database, alembic):  # noqa: F811
    target = fresh_database()
    command.upgrade(with_proposals(alembic(target)), "0002")
    engine = _engine(target, connect_args={"options": "-c search_path=concepttrail,public"})
    now = datetime.now(UTC)
    with Session(engine) as s:
        s.add_all(
            [
                Role(role_code="teacher"),
                Role(role_code="student"),
                Subject(subject_id="mathematics", active=True),
            ]
        )
        rooms = [Classroom(classroom_id=uuid.uuid4(), grade_level=7, active=True) for _ in range(2)]
        teachers = [
            User(
                user_id=uuid.uuid4(),
                login_identifier=f"t{i}@example.invalid",
                password_hash=hash_password("teacher-password-123"),
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            for i in range(2)
        ]
        student = User(
            user_id=uuid.uuid4(),
            login_identifier="stu",
            password_hash=hash_password("12345678"),
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        s.add_all([*rooms, *teachers, student])
        s.flush()
        learner = Learner(learner_id=uuid.uuid4(), user_id=student.user_id)
        s.add_all(
            [
                learner,
                UserRole(user_id=student.user_id, role_code="student"),
                *[UserRole(user_id=t.user_id, role_code="teacher") for t in teachers],
                *[
                    TeacherClassAssignment(
                        classroom_id=r.classroom_id, user_id=t.user_id, assigned_at=now
                    )
                    for r, t in zip(rooms, teachers, strict=True)
                ],
                KnowledgeComponent(
                    kc_id="KC1",
                    subject_id="mathematics",
                    stable_key="i.kc1",
                    name="KC1",
                    review_status="approved",
                ),
            ]
        )
        s.flush()
        s.add(
            ClassEnrollment(
                enrollment_id=uuid.uuid4(),
                learner_id=learner.learner_id,
                classroom_id=rooms[0].classroom_id,
                enrolled_at=now,
            )
        )
        s.commit()
        ids = {
            "room_a": rooms[0].classroom_id,
            "room_b": rooms[1].classroom_id,
            "learner": learner.learner_id,
        }
    yield engine, ids
    engine.dispose()


def client_for(engine, enabled: bool, monkeypatch):
    settings = get_settings().model_copy(update={"interventions_enabled": enabled})
    monkeypatch.setattr(interventions_api, "get_settings", lambda: settings)
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


def test_disabled_by_default(world, monkeypatch) -> None:
    engine, ids = world
    client = client_for(engine, False, monkeypatch)
    h = login(client, "t0@example.invalid", "teacher-password-123")
    r = client.get(f"/api/v1/teacher/classes/{ids['room_a']}/interventions", headers=h)
    assert r.status_code == 503 and r.json()["error"]["code"] == "feature_not_enabled"


def test_full_workflow_and_isolation(world, monkeypatch) -> None:
    engine, ids = world
    client = client_for(engine, True, monkeypatch)
    a = login(client, "t0@example.invalid", "teacher-password-123")
    b = login(client, "t1@example.invalid", "teacher-password-123")
    student = login(client, "stu", "12345678")
    base = f"/api/v1/teacher/classes/{ids['room_a']}/interventions"
    created = client.post(
        base,
        headers=a,
        json={
            "intervention_type": "small_group",
            "kc_id": "KC1",
            "learner_id": str(ids["learner"]),
            "note": "Revisit triplets",
        },
    )
    assert created.status_code == 201 and created.json()["status"] == "planned"
    iid = created.json()["intervention_id"]
    assert client.post(base, headers=b, json={"intervention_type": "reteach"}).status_code == 403
    assert client.get(base, headers=student).status_code == 403
    other_room = f"/api/v1/teacher/classes/{ids['room_b']}/interventions"
    wrong_learner = client.post(
        other_room,
        headers=b,
        json={"intervention_type": "individual_support", "learner_id": str(ids["learner"])},
    )
    assert (
        wrong_learner.status_code == 404
        and wrong_learner.json()["error"]["code"] == "learner_not_in_class"
    )
    assert (
        client.post(
            base, headers=a, json={"intervention_type": "reteach", "kc_id": "NOPE"}
        ).status_code
        == 404
    )
    assert client.post(base, headers=a, json={"intervention_type": "shaming"}).status_code == 422
    moved = client.post(f"{base}/{iid}/status", headers=a, json={"status": "completed"})
    assert moved.status_code == 200 and moved.json()["completed_at"]
    again = client.post(f"{base}/{iid}/status", headers=a, json={"status": "in_progress"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "invalid_transition"
    assert (
        client.post(
            f"{other_room}/{iid}/status", headers=b, json={"status": "cancelled"}
        ).status_code
        == 404
    )
    listed = client.get(base, headers=a).json()
    assert listed["count"] == 1 and listed["interventions"][0]["status"] == "completed"
    assert client.get(other_room, headers=b).json()["count"] == 0
