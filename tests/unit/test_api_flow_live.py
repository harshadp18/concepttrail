"""End-to-end regression of the teammate API with the owner services, on live PostgreSQL.

The app's `get_db` is overridden with a session inside an outer transaction that is rolled back,
so the synthetic classroom, KCs, questions, attempts and mastery never persist.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from live_db_fixtures import World, live_engine, pg_fixture  # noqa: F401  (fixtures)

from app.db.session import get_db
from app.main import create_app
from app.services.bkt_service import BKTParameters, update_mastery

pytestmark = pytest.mark.live_db


@pytest.fixture
def client_world(pg):
    world = World(pg)
    world.config("api", datetime.now(UTC) - timedelta(days=1))
    app = create_app()
    app.dependency_overrides[get_db] = lambda: pg
    with TestClient(app) as client:
        yield client, world


def login(client, identifier: str, credential: str) -> dict[str, str]:
    r = client.post(
        "/api/v1/auth/login", json={"login_identifier": identifier, "credential": credential}
    )
    assert r.status_code == 200, r.json()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_student_flow_scoring_bkt_replay_and_progress(client_world) -> None:
    client, w = client_world
    qid = w.question([w.kc_a], correct="B")
    student = login(client, w.student_user.login_identifier, w.pin)
    listed = client.get(f"/api/v1/topics/{w.kc_a}/questions", headers=student).json()
    assert [q["question_id"] for q in listed["questions"]] == [qid]
    assert "is_correct" not in str(listed)  # no answer keys delivered
    body = {
        "question_id": qid,
        "question_version": 1,
        "submitted_answer": {"option_key": "B"},
        "idempotency_key": "synthetic-attempt-0001",
    }
    r = client.post("/api/v1/attempts", json=body, headers=student)
    assert r.status_code == 201, r.json()
    result = r.json()
    assert result["scored_correct"] is True and result["bkt"]["updated"] is True
    assert result["bkt"]["mastery_probability"] == pytest.approx(
        update_mastery(0.3, True, BKTParameters(0.3, 0.15, 0.2, 0.1))
    )
    again = client.post("/api/v1/attempts", json=body, headers=student).json()
    assert again["duplicate_replay"] is True and again["bkt"]["updated"] is False
    wrong = dict(
        body, submitted_answer={"option_key": "A"}, idempotency_key="synthetic-attempt-0002"
    )
    assert (
        client.post("/api/v1/attempts", json=wrong, headers=student).json()["scored_correct"]
        is False
    )
    progress = client.get("/api/v1/student/progress", headers=student).json()
    assert progress["attempt_summary"]["total_attempts"] == 2
    assert progress["mastery_estimates"][0]["evidence_count"] == 2


def test_multi_kc_and_hint_policy_through_the_api(client_world) -> None:
    client, w = client_world
    student = login(client, w.student_user.login_identifier, w.pin)
    multi = w.question([w.kc_a, w.kc_b])
    r = client.post(
        "/api/v1/attempts",
        headers=student,
        json={
            "question_id": multi,
            "question_version": 1,
            "submitted_answer": {"option_key": "B"},
            "idempotency_key": "synthetic-attempt-0003",
        },
    ).json()
    assert r["bkt"] == {
        "updated": False,
        "reason": "multi_kc_question_requires_kc_specific_evidence",
        "kc_id": None,
        "mastery_probability": None,
        "config_version": None,
    }
    single = w.question([w.kc_b])
    hinted = client.post(
        "/api/v1/attempts",
        headers=student,
        json={
            "question_id": single,
            "question_version": 1,
            "submitted_answer": {"option_key": "B"},
            "hint_tier": 2,
            "idempotency_key": "synthetic-attempt-0004",
        },
    ).json()
    assert hinted["scored_correct"] is True
    assert hinted["bkt"]["reason"] == "high_tier_hint_counted_as_incorrect"


def test_teacher_dashboard_and_access_control(client_world) -> None:
    client, w = client_world
    teacher = login(client, w.teacher_user.login_identifier, w.password)
    student = login(client, w.student_user.login_identifier, w.pin)
    cid = w.classroom.classroom_id
    dash = client.get(f"/api/v1/teacher/classes/{cid}/dashboard", headers=teacher)
    assert dash.status_code == 200 and dash.json()["learner_count"] == 1
    assert (
        client.get(f"/api/v1/teacher/classes/{cid}/dashboard", headers=student).status_code == 403
    )
    assert (
        client.post(
            "/api/v1/attempts",
            headers=teacher,
            json={
                "question_id": "x",
                "question_version": 1,
                "submitted_answer": {"option_key": "A"},
                "idempotency_key": "synthetic-attempt-0005",
            },
        ).status_code
        == 403
    )
    assert client.get("/api/v1/me").status_code == 401
    unapproved = w.question([w.kc_a], status="validated_draft")
    listed = client.get(f"/api/v1/topics/{w.kc_a}/questions", headers=student).json()
    assert unapproved not in [q["question_id"] for q in listed["questions"]]
