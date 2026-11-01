"""Teacher question review over HTTP (live PostgreSQL, rolled back; synthetic rows only)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from live_db_fixtures import MARK, World, live_engine, pg_fixture  # noqa: F401  (fixtures)

from app.core.security import hash_password
from app.db.models import Classroom, Question, TeacherClassAssignment, User, UserRole
from app.db.session import get_db
from app.main import create_app

pytestmark = pytest.mark.live_db


@pytest.fixture
def ctx(pg):
    w = World(pg)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: pg
    with TestClient(app) as client:
        yield client, w, pg


def login(client, identifier, credential):
    r = client.post(
        "/api/v1/auth/login", json={"login_identifier": identifier, "credential": credential}
    )
    assert r.status_code == 200, r.json()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def other_teacher(pg, w, grade: int) -> tuple[str, str]:
    now = datetime.now(UTC)
    user = User(
        user_id=uuid.uuid4(),
        login_identifier=f"syn-rev-{w.tag}@example.invalid",
        password_hash=hash_password("synthetic-reviewer-pass"),
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    room = Classroom(
        classroom_id=uuid.uuid4(),
        grade_level=grade,
        section_label="SYN-R",
        academic_session="2026-27",
        school_label=MARK,
        active=True,
    )
    pg.add_all([user, room])
    pg.flush()
    pg.add_all(
        [
            UserRole(user_id=user.user_id, role_code="teacher"),
            TeacherClassAssignment(
                classroom_id=room.classroom_id, user_id=user.user_id, assigned_at=now
            ),
        ]
    )
    pg.flush()
    return user.login_identifier, "synthetic-reviewer-pass"


def test_review_queue_is_teacher_only_and_class_scoped(ctx) -> None:
    client, w, pg = ctx
    qid = w.question([w.kc_a], status="validated_draft")
    teacher = login(client, w.teacher_user.login_identifier, w.password)
    queue = client.get(
        "/api/v1/teacher/review/questions?status=validated_draft&limit=100", headers=teacher
    )
    assert queue.status_code == 200
    item = next(q for q in queue.json()["questions"] if q["question_id"] == qid)
    assert any(o["is_correct"] for o in item["options"])  # teachers see keys
    student = login(client, w.student_user.login_identifier, w.pin)
    assert client.get("/api/v1/teacher/review/questions", headers=student).status_code == 403
    other = login(client, *other_teacher(pg, w, grade=9))
    listed = client.get(
        "/api/v1/teacher/review/questions?status=validated_draft&limit=100", headers=other
    ).json()
    assert qid not in [q["question_id"] for q in listed["questions"]]
    r = client.post(
        f"/api/v1/teacher/review/questions/{qid}",
        headers=other,
        json={"decision": "rejected", "rationale": "not my class"},
    )
    assert r.status_code == 404


def test_demo_content_cannot_be_approved_and_reviews_are_attributed(ctx) -> None:
    client, w, pg = ctx
    demo = w.question([w.kc_a], status="demo_release")
    teacher = login(client, w.teacher_user.login_identifier, w.password)
    refused = client.post(
        f"/api/v1/teacher/review/questions/{demo}",
        headers=teacher,
        json={"decision": "approved", "rationale": "looks fine"},
    )
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "review_refused"
    assert pg.get(Question, demo).review_status == "demo_release"
    rejected = client.post(
        f"/api/v1/teacher/review/questions/{demo}",
        headers=teacher,
        json={"decision": "revision_required", "rationale": "Option C is ambiguous."},
    )
    assert rejected.status_code == 200 and rejected.json()["review_status"] == "draft"
    review = pg.get(Question, demo).verification["reviews"][-1]
    assert review["reviewer_user_id"] == str(w.teacher_user.user_id) and review["decided_at"]
    draft = w.question([w.kc_a], status="validated_draft")
    q = pg.get(Question, draft)
    q.verification = {"validation": {"ok": True}, "provenance": {}}
    pg.flush()
    ok = client.post(
        f"/api/v1/teacher/review/questions/{draft}",
        headers=teacher,
        json={"decision": "approved", "rationale": "Key and wording checked."},
    )
    assert ok.status_code == 200 and ok.json()["review_status"] == "approved"
    short = client.post(
        f"/api/v1/teacher/review/questions/{demo}",
        headers=teacher,
        json={"decision": "rejected", "rationale": ""},
    )
    assert short.status_code == 422
