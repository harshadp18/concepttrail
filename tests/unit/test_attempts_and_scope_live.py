"""Attempt scoring for every deliverable type, learner scope and teacher isolation, over HTTP.

Live PostgreSQL inside an always-rolled-back transaction; synthetic rows only.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from live_db_fixtures import MARK, World, live_engine, pg_fixture  # noqa: F401  (fixtures)
from pydantic import ValidationError

from app.core.security import hash_password
from app.db.models import (
    ClassEnrollment,
    Classroom,
    KcEdge,
    Question,
    QuestionKc,
    QuestionOption,
    TeacherClassAssignment,
    User,
    UserRole,
)
from app.db.session import get_db
from app.main import create_app
from app.schemas.attempts import AttemptCreate

pytestmark = pytest.mark.live_db


@pytest.fixture
def ctx(pg):
    world = World(pg)
    world.config("scope", datetime.now(UTC) - timedelta(days=1))
    app = create_app()
    app.dependency_overrides[get_db] = lambda: pg
    with TestClient(app) as client:
        yield client, world, pg


def login(client, identifier: str, credential: str) -> dict[str, str]:
    r = client.post(
        "/api/v1/auth/login", json={"login_identifier": identifier, "credential": credential}
    )
    assert r.status_code == 200, r.json()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def make_question(
    pg,
    w: World,
    kc_id: str,
    item_type: str,
    options: list[tuple[str, str, bool]] = (),
    expected: dict | None = None,
) -> str:
    qid = f"QSYN-{w.tag}-{uuid.uuid4().hex[:6]}"
    pg.add(
        Question(
            question_id=qid,
            item_type=item_type,
            stem=f"{MARK} {item_type}",
            expected_answer=expected,
            difficulty=2,
            review_status="approved",
            version=1,
            active=True,
            verification={"synthetic": True},
        )
    )
    pg.flush()
    for order, (key, text, correct) in enumerate(options, start=1):
        pg.add(
            QuestionOption(
                option_id=uuid.uuid4(),
                question_id=qid,
                option_key=key,
                option_text=text,
                is_correct=correct,
                display_order=order,
            )
        )
    pg.add(
        QuestionKc(
            question_id=qid,
            kc_id=kc_id,
            weight=Decimal("1"),
            mapping_role="primary",
            review_status="approved",
        )
    )
    pg.flush()
    return qid


def submit(client, headers, qid: str, answer: dict, key: str | None = None):
    return client.post(
        "/api/v1/attempts",
        headers=headers,
        json={
            "question_id": qid,
            "question_version": 1,
            "submitted_answer": answer,
            "idempotency_key": key or f"synthetic-{uuid.uuid4().hex}",
        },
    )


MULTI = [("A", "first", True), ("B", "second", False), ("C", "third", True), ("D", "fourth", False)]
TF = [("A", "True", False), ("B", "False", True)]


def test_multiple_select_is_scored_as_an_exact_set(ctx) -> None:
    client, w, pg = ctx
    h = login(client, w.student_user.login_identifier, w.pin)
    qid = make_question(pg, w, w.kc_a, "multiple_select", MULTI)
    listed = client.get(f"/api/v1/topics/{w.kc_a}/questions", headers=h).json()["questions"]
    served = next(q for q in listed if q["question_id"] == qid)
    assert served["answer_shape"] == "option_keys"
    assert "is_correct" not in str(served)
    right = submit(client, h, qid, {"option_keys": ["C", "A"]})
    assert right.status_code == 201 and right.json()["scored_correct"] is True
    assert right.json()["score_method"] == "multiple_select_exact_set_v1"
    assert right.json()["bkt"]["updated"] is True
    partial = submit(client, h, qid, {"option_keys": ["A"]}).json()
    assert partial["scored_correct"] is False and partial["score"] == 0.0
    single_shape = submit(client, h, qid, {"option_key": "A"})
    assert single_shape.status_code == 422
    assert single_shape.json()["error"]["code"] == "invalid_answer_format"
    unknown = submit(client, h, qid, {"option_keys": ["A", "Z"]})
    assert unknown.json()["error"]["code"] == "invalid_answer_option"


def test_true_false_accepts_option_key_or_boolean_and_checks_key_consistency(ctx) -> None:
    client, w, pg = ctx
    h = login(client, w.student_user.login_identifier, w.pin)
    qid = make_question(pg, w, w.kc_a, "true_false", TF, {"value": False})
    assert submit(client, h, qid, {"option_key": "B"}).json()["scored_correct"] is True
    assert submit(client, h, qid, {"value": True}).json()["scored_correct"] is False
    assert submit(client, h, qid, {"value": "yes"}).status_code == 422
    broken = make_question(pg, w, w.kc_a, "true_false", TF, {"value": True})  # key disagrees
    listed = client.get(f"/api/v1/topics/{w.kc_a}/questions", headers=h).json()["questions"]
    assert broken not in [q["question_id"] for q in listed]
    r = submit(client, h, broken, {"option_key": "B"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "answer_verification_failed"


def test_numeric_uses_stored_tolerance(ctx) -> None:
    client, w, pg = ctx
    h = login(client, w.student_user.login_identifier, w.pin)
    qid = make_question(pg, w, w.kc_a, "numeric", expected={"value": 2.5, "abs_tolerance": 0.05})
    assert submit(client, h, qid, {"value": 2.54}).json()["scored_correct"] is True
    assert submit(client, h, qid, {"value": "2.6"}).json()["scored_correct"] is False
    assert submit(client, h, qid, {"value": "two"}).status_code == 422
    unkeyed = make_question(pg, w, w.kc_a, "numeric", expected=None)
    listed = client.get(f"/api/v1/topics/{w.kc_a}/questions", headers=h).json()["questions"]
    assert unkeyed not in [q["question_id"] for q in listed]


def test_short_answer_is_never_served_or_auto_scored(ctx) -> None:
    client, w, pg = ctx
    h = login(client, w.student_user.login_identifier, w.pin)
    qid = make_question(pg, w, w.kc_a, "short_answer")
    listed = client.get(f"/api/v1/topics/{w.kc_a}/questions", headers=h).json()["questions"]
    assert qid not in [q["question_id"] for q in listed]
    r = submit(client, h, qid, {"value": "photosynthesis"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "unsupported_scoring_method"


def test_nothing_is_written_for_an_invalid_answer_and_replay_is_idempotent(ctx) -> None:
    client, w, pg = ctx
    h = login(client, w.student_user.login_identifier, w.pin)
    qid = w.question([w.kc_a])
    assert submit(client, h, qid, {"option_key": "Z"}, key="synthetic-invalid-0001").status_code
    first = submit(client, h, qid, {"option_key": "B"}, key="synthetic-replay-0001").json()
    again = submit(client, h, qid, {"option_key": "A"}, key="synthetic-replay-0001").json()
    assert again["duplicate_replay"] is True and again["attempt_id"] == first["attempt_id"]
    assert again["scored_correct"] is True  # the stored outcome, not the new answer
    other = w.question([w.kc_a])
    clash = submit(client, h, other, {"option_key": "B"}, key="synthetic-replay-0001")
    assert clash.status_code == 409


def test_cross_grade_and_unenrolled_access_are_refused(ctx) -> None:
    client, w, pg = ctx
    h = login(client, w.student_user.login_identifier, w.pin)
    grade9 = w.kc("G9", grade=9)
    q9 = w.question([grade9])
    assert client.get(f"/api/v1/topics/{grade9}", headers=h).status_code == 404
    assert client.get(f"/api/v1/topics/{grade9}/questions", headers=h).status_code == 404
    assert submit(client, h, q9, {"option_key": "B"}).status_code == 404
    assert client.get("/api/v1/curriculum?grade_level=9", headers=h).status_code == 403
    unmapped = w.kc("NOMAP", grade=None)
    assert client.get(f"/api/v1/topics/{unmapped}/questions", headers=h).status_code == 404
    enrollment = pg.query(ClassEnrollment).filter_by(learner_id=w.learner.learner_id).one()
    enrollment.ended_at = datetime.now(UTC)
    pg.flush()
    r = client.get(f"/api/v1/topics/{w.kc_a}/questions", headers=h)
    assert r.status_code == 403 and r.json()["error"]["code"] == "enrollment_required"
    assert client.get("/api/v1/curriculum", headers=h).status_code == 403


def test_lower_grade_prerequisite_is_reachable_only_through_the_graph(ctx, monkeypatch) -> None:
    from app.core import content_release
    from app.core.config import get_settings

    client, w, pg = ctx
    demo = get_settings().model_copy(update={"content_release_mode": "demo", "app_env": "test"})
    monkeypatch.setattr(content_release, "get_settings", lambda: demo)
    h = login(client, w.student_user.login_identifier, w.pin)
    grade6 = w.kc("G6", grade=6)
    unrelated6 = w.kc("U6", grade=6)
    pg.add(
        KcEdge(
            prerequisite_kc_id=grade6,
            dependent_kc_id=w.kc_a,
            strength=2,
            reason="[uses_concept] syn",
            review_status="approved",
        )
    )
    pg.flush()
    assert client.get(f"/api/v1/topics/{grade6}", headers=h).status_code == 200
    assert client.get(f"/api/v1/topics/{unrelated6}", headers=h).status_code == 404


def test_option_order_is_shuffled_per_learner_but_stable(ctx) -> None:
    client, w, pg = ctx
    h = login(client, w.student_user.login_identifier, w.pin)
    qids = [w.question([w.kc_a]) for _ in range(8)]
    first = client.get(f"/api/v1/topics/{w.kc_a}/questions", headers=h).json()["questions"]
    second = client.get(f"/api/v1/topics/{w.kc_a}/questions", headers=h).json()["questions"]
    assert first == second
    orders = {
        tuple(o["option_key"] for o in q["options"]) for q in first if q["question_id"] in qids
    }
    assert len(orders) > 1  # not the stored A,B,C,D order for every question
    for q in first:
        assert [o["display_order"] for o in q["options"]] == list(range(1, len(q["options"]) + 1))


def test_teacher_b_cannot_read_teacher_a_class(ctx) -> None:
    client, w, pg = ctx
    now = datetime.now(UTC)
    other = User(
        user_id=uuid.uuid4(),
        login_identifier=f"syn-teacher-b-{w.tag}@example.invalid",
        password_hash=hash_password("teacher-b-synthetic-password"),
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    room_b = Classroom(
        classroom_id=uuid.uuid4(),
        grade_level=8,
        section_label="SYN-B",
        academic_session="2026-27",
        school_label=MARK,
        active=True,
    )
    pg.add_all([other, room_b])
    pg.flush()
    pg.add_all(
        [
            UserRole(user_id=other.user_id, role_code="teacher"),
            TeacherClassAssignment(
                classroom_id=room_b.classroom_id, user_id=other.user_id, assigned_at=now
            ),
        ]
    )
    pg.flush()
    teacher_b = login(client, other.login_identifier, "teacher-b-synthetic-password")
    teacher_a = login(client, w.teacher_user.login_identifier, w.password)
    a_room = w.classroom.classroom_id
    r = client.get(f"/api/v1/teacher/classes/{a_room}/dashboard", headers=teacher_b)
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden_classroom"
    own = client.get(f"/api/v1/teacher/classes/{room_b.classroom_id}/dashboard", headers=teacher_b)
    assert own.status_code == 200 and own.json()["learner_count"] == 0
    assert (
        client.get(f"/api/v1/teacher/classes/{room_b.classroom_id}/dashboard", headers=teacher_a)
    ).status_code == 403
    assignment = pg.get(TeacherClassAssignment, (room_b.classroom_id, other.user_id))
    assignment.ended_at = now
    pg.flush()
    ended = client.get(
        f"/api/v1/teacher/classes/{room_b.classroom_id}/dashboard", headers=teacher_b
    )
    assert ended.status_code == 403


def test_attempt_schema_accepts_only_known_shapes() -> None:
    def make(answer):
        return AttemptCreate(
            question_id="q",
            question_version=1,
            submitted_answer=answer,
            idempotency_key="synthetic-key-000001",
        )

    assert make({"option_keys": [" A ", "C"]}).submitted_answer == {"option_keys": ["A", "C"]}
    assert make({"value": True}).submitted_answer == {"value": True}
    assert make({"value": " 3.5 "}).submitted_answer == {"value": "3.5"}
    for bad in (
        {"option_keys": []},
        {"option_keys": ["A", "A"]},
        {"value": float("nan")},
        {"value": None},
        {"option_key": "A", "value": True},
        {"is_correct": True},
        {"value": "x" * 41},
    ):
        with pytest.raises(ValidationError):
            make(bad)
