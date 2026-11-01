"""Catalog, student progress and teacher roster routes (live PostgreSQL, rolled back).

All rows are synthetic and created per test; attempts are inserted directly so the expected
numbers are known exactly.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from live_db_fixtures import World, live_engine, pg_fixture  # noqa: F401  (fixtures)
from test_review_api_live import login, other_teacher

from app.db.models import Attempt, KcEdge, StudentKcState
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


def attempt(pg, w, qid: str, correct: bool, minutes_ago: int = 0) -> None:
    pg.add(
        Attempt(
            attempt_id=uuid.uuid4(),
            learner_id=w.learner.learner_id,
            question_id=qid,
            question_version=1,
            submitted_answer={"option_key": "B" if correct else "A"},
            scored_correct=correct,
            score=1 if correct else 0,
            score_method="exact_option",
            hint_tier=0,
            attempted_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
            idempotency_key=f"syn-{uuid.uuid4().hex}",
        )
    )
    pg.flush()


def state(pg, w, kc: str, p: float, evidence: int) -> None:
    pg.add(
        StudentKcState(
            learner_id=w.learner.learner_id,
            kc_id=kc,
            mastery_probability=p,
            evidence_count=evidence,
            bkt_config_version=None,
            updated_at=datetime.now(UTC),
        )
    )
    pg.flush()


def test_catalog_lists_all_five_subjects_per_enrolled_level_and_empty_states(ctx) -> None:
    client, w, pg = ctx
    student = login(client, w.student_user.login_identifier, w.pin)
    body = client.get("/api/v1/catalog/classes", headers=student).json()
    assert body["grade_levels"] == [7]  # derived from the enrollment, not from the client
    mine = [c for c in body["combinations"] if c["subject_id"] == "mathematics"]
    assert mine and mine[0]["chapters"] >= 1 and mine[0]["topics"] >= 2
    assert all(
        c["state"] in ("published", "demo_release", "not_available") for c in body["combinations"]
    )
    assert all(c["grade_level"] == 7 for c in body["combinations"])
    assert client.get("/api/v1/catalog/classes").status_code == 401


def test_chapter_detail_is_scoped_and_unknown_is_not_found(ctx) -> None:
    client, w, pg = ctx
    student = login(client, w.student_user.login_identifier, w.pin)
    item = w.grade_item(7)
    ok = client.get(f"/api/v1/curriculum/items/{item}", headers=student)
    assert ok.status_code == 200
    assert {t["kc_id"] for t in ok.json()["topics"]} >= {w.kc_a, w.kc_b}
    other_class = w.grade_item(9)  # a chapter outside the enrolled class
    assert client.get(f"/api/v1/curriculum/items/{other_class}", headers=student).status_code == 404
    missing = client.get("/api/v1/curriculum/items/NOPE", headers=student)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "item_not_found"


def test_prerequisites_report_readiness_from_the_students_own_state(ctx, monkeypatch) -> None:
    client, w, pg = ctx
    pg.add(
        KcEdge(
            prerequisite_kc_id=w.kc_a,
            dependent_kc_id=w.kc_b,
            strength=3,
            reason="synthetic",
            review_status="approved",
        )
    )
    pg.flush()
    from app.core import content_release
    from app.core.config import get_settings

    demo = get_settings().model_copy(update={"content_release_mode": "demo", "app_env": "test"})
    monkeypatch.setattr(content_release, "get_settings", lambda: demo)
    student = login(client, w.student_user.login_identifier, w.pin)
    state(pg, w, w.kc_a, 0.82, 4)
    body = client.get(f"/api/v1/topics/{w.kc_b}/prerequisites", headers=student).json()
    assert body["graph_available"] and [p["kc_id"] for p in body["direct"]] == [w.kc_a]
    assert body["direct"][0]["ready"] is True and body["all_direct_ready"] is True
    assert body["edge_provenance"] == "ai_proposed_demo"


def test_student_chapter_progress_matches_known_attempts(ctx) -> None:
    client, w, pg = ctx
    student = login(client, w.student_user.login_identifier, w.pin)
    empty = client.get("/api/v1/student/progress/chapters", headers=student).json()
    mine = [c for c in empty["chapters"] if c["item_id"] == w.grade_item(7)][0]
    assert mine["topics_started"] == 0 and mine["average_mastery_probability"] is None
    assert mine["accuracy"] is None  # empty state is null, never zero
    q = w.question([w.kc_a])
    attempt(pg, w, q, True, 3)
    attempt(pg, w, q, False, 2)
    attempt(pg, w, q, True, 1)
    state(pg, w, w.kc_a, 0.96, 3)
    body = client.get("/api/v1/student/progress/chapters", headers=student).json()
    row = [c for c in body["chapters"] if c["item_id"] == w.grade_item(7)][0]
    assert row["attempts"] == 3 and row["correct_attempts"] == 2 and row["accuracy"] == 0.6667
    assert row["topics_started"] == 1 and row["topics_mastered"] == 1
    assert row["average_mastery_probability"] == 0.96
    subject = [s for s in body["subjects"] if s["subject_id"] == "mathematics"][0]
    assert subject["attempts"] >= 3 and body["thresholds_provisional"] is True


def test_activity_is_paginated_newest_first_and_hides_keys(ctx) -> None:
    client, w, pg = ctx
    student = login(client, w.student_user.login_identifier, w.pin)
    q = w.question([w.kc_a])
    for minutes, ok in ((30, False), (20, True), (10, True)):
        attempt(pg, w, q, ok, minutes)
    page = client.get("/api/v1/student/activity?limit=2", headers=student).json()
    assert page["count"] == 3 and len(page["attempts"]) == 2
    assert page["attempts"][0]["attempted_at"] > page["attempts"][1]["attempted_at"]
    assert "expected_answer" not in str(page) and "is_correct" not in str(page)
    rest = client.get("/api/v1/student/activity?limit=2&offset=2", headers=student).json()
    assert len(rest["attempts"]) == 1 and rest["attempts"][0]["scored_correct"] is False
    assert client.get("/api/v1/student/activity?limit=0", headers=student).status_code == 422


def test_weak_areas_need_enough_evidence_and_retry_list_uses_latest_attempt(ctx) -> None:
    client, w, pg = ctx
    student = login(client, w.student_user.login_identifier, w.pin)
    state(pg, w, w.kc_a, 0.2, 5)  # weak with evidence
    state(pg, w, w.kc_b, 0.1, 1)  # low but a single answer: not reported
    weak = client.get("/api/v1/student/weak-areas", headers=student).json()["weak_areas"]
    assert [x["kc_id"] for x in weak] == [w.kc_a]
    first, second = w.question([w.kc_a]), w.question([w.kc_a])
    attempt(pg, w, first, False, 10)
    attempt(pg, w, first, True, 5)  # later correct: no longer a retry candidate
    attempt(pg, w, second, False, 4)
    review = client.get("/api/v1/student/review", headers=student).json()["questions"]
    assert [r["question_id"] for r in review] == [second]
    assert review[0]["kc_ids"] == [w.kc_a]  # lets the client open the topic's practice set
    assert "is_correct" not in str(review)


def test_teacher_roster_progress_and_weak_areas_are_class_scoped(ctx) -> None:
    client, w, pg = ctx
    q = w.question([w.kc_a])
    attempt(pg, w, q, True, 2)
    attempt(pg, w, q, False, 1)
    state(pg, w, w.kc_a, 0.3, 4)
    teacher = login(client, w.teacher_user.login_identifier, w.password)
    cid = w.classroom.classroom_id
    classes = client.get("/api/v1/teacher/classes", headers=teacher).json()
    assert [c["classroom_id"] for c in classes["classes"]] == [str(cid)]
    assert classes["classes"][0]["learner_count"] == 1
    roster = client.get(f"/api/v1/teacher/classes/{cid}/learners", headers=teacher).json()
    row = roster["learners"][0]
    assert row["learner_id"] == str(w.learner.learner_id) and row["attempts"] == 2
    assert row["accuracy"] == 0.5 and row["average_mastery_probability"] == 0.3
    detail = client.get(
        f"/api/v1/teacher/classes/{cid}/learners/{w.learner.learner_id}/progress", headers=teacher
    ).json()
    assert detail["weak_areas"][0]["kc_id"] == w.kc_a
    assert detail["recent_activity"]["count"] == 2
    weak = client.get(f"/api/v1/teacher/classes/{cid}/weak-areas", headers=teacher).json()
    assert weak["weak_areas"][0]["kc_id"] == w.kc_a
    assert weak["weak_areas"][0]["share_below_threshold"] == 1.0


def test_cross_access_is_refused(ctx) -> None:
    client, w, pg = ctx
    cid = w.classroom.classroom_id
    student = login(client, w.student_user.login_identifier, w.pin)
    for path in (
        "/api/v1/teacher/classes",
        f"/api/v1/teacher/classes/{cid}/learners",
        f"/api/v1/teacher/classes/{cid}/weak-areas",
        f"/api/v1/teacher/classes/{cid}/learners/{w.learner.learner_id}/progress",
    ):
        assert client.get(path, headers=student).status_code == 403, path
    other = login(client, *other_teacher(pg, w, grade=9))
    for path in (
        f"/api/v1/teacher/classes/{cid}/learners",
        f"/api/v1/teacher/classes/{cid}/weak-areas",
        f"/api/v1/teacher/classes/{cid}/learners/{w.learner.learner_id}/progress",
    ):
        assert client.get(path, headers=other).status_code == 403, path
    teacher = login(client, w.teacher_user.login_identifier, w.password)
    ghost = client.get(
        f"/api/v1/teacher/classes/{cid}/learners/{uuid.uuid4()}/progress", headers=teacher
    )
    assert ghost.status_code == 404 and ghost.json()["error"]["code"] == "learner_not_found"
    for path in (
        "/api/v1/student/activity",
        "/api/v1/student/weak-areas",
        "/api/v1/student/review",
    ):
        assert client.get(path, headers=teacher).status_code == 403, path
