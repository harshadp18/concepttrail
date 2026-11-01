"""Bell-Ringer topic analysis and class heatmap (live PostgreSQL, rolled back).

Synthetic learners and states are created per test so every count is known exactly. Cycles need
the proposed table and are covered on disposable databases
(`tests/integration/test_bell_ringer_cycles_disposable.py`); here they must answer 503.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from live_db_fixtures import MARK, World, live_engine, pg_fixture  # noqa: F401  (fixtures)
from test_review_api_live import login, other_teacher

from app.core.security import hash_password
from app.db.models import Attempt, ClassEnrollment, Learner, StudentKcState, User
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


def extra_learner(pg, w, n: int) -> uuid.UUID:
    now = datetime.now(UTC)
    user = User(
        user_id=uuid.uuid4(),
        login_identifier=f"syn-br-{w.tag}-{n}",
        password_hash=hash_password("24681357"),
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    pg.add(user)
    pg.flush()
    learner = Learner(
        learner_id=uuid.uuid4(), user_id=user.user_id, display_name=f"{MARK} {n}", created_at=now
    )
    pg.add(learner)
    pg.flush()
    pg.add(
        ClassEnrollment(
            enrollment_id=uuid.uuid4(),
            learner_id=learner.learner_id,
            classroom_id=w.classroom.classroom_id,
            enrolled_at=now,
        )
    )
    pg.flush()
    return learner.learner_id


def state(pg, learner_id, kc: str, p: float, evidence: int) -> None:
    pg.add(
        StudentKcState(
            learner_id=learner_id,
            kc_id=kc,
            mastery_probability=p,
            evidence_count=evidence,
            updated_at=datetime.now(UTC),
        )
    )
    pg.flush()


def attempt(pg, learner_id, qid: str, key: str, correct: bool, days_ago: int = 0) -> None:
    pg.add(
        Attempt(
            attempt_id=uuid.uuid4(),
            learner_id=learner_id,
            question_id=qid,
            question_version=1,
            submitted_answer={"option_key": key},
            scored_correct=correct,
            score=1 if correct else 0,
            score_method="exact_option",
            hint_tier=0,
            attempted_at=datetime.now(UTC) - timedelta(days=days_ago),
            idempotency_key=f"syn-{uuid.uuid4().hex}",
        )
    )
    pg.flush()


def setup_class(pg, w):
    """Four learners: two weak on A, one strong on A, one with no activity at all."""
    first = w.learner.learner_id
    second, third, idle = (extra_learner(pg, w, n) for n in (2, 3, 4))
    q = w.question([w.kc_a])
    for _ in range(5):  # one learner failing five times is still ONE affected learner
        attempt(pg, first, q, "A", False)
    attempt(pg, second, q, "C", False)
    attempt(pg, second, q, "A", False, days_ago=40)  # outside a 14-day window
    attempt(pg, third, q, "B", True)
    state(pg, first, w.kc_a, 0.2, 5)
    state(pg, second, w.kc_a, 0.3, 2)
    state(pg, third, w.kc_a, 0.9, 3)
    state(pg, first, w.kc_b, 0.1, 1)  # a single answer is not enough evidence
    return (first, second, third, idle), q


def test_topic_analysis_counts_unique_learners_with_denominators(ctx) -> None:
    client, w, pg = ctx
    (first, second, third, idle), q = setup_class(pg, w)
    teacher = login(client, w.teacher_user.login_identifier, w.password)
    cid = w.classroom.classroom_id
    body = client.get(f"/api/v1/teacher/classes/{cid}/bell-ringer/topics", headers=teacher).json()
    assert body["enrolled_learners"] == 4 and body["window"]["days"] == 14
    assert body["criteria"]["provisional"] is True and body["flagged_count"] == 1
    a = next(t for t in body["topics"] if t["kc_id"] == w.kc_a)
    assert a["flagged"] and a["rank"] == 1 and a["severity"] == "high"
    assert a["learners_with_evidence"] == 3 and a["learners_below_threshold"] == 2
    assert a["learners_not_attempted"] == 1 and a["coverage"] == 0.75
    assert a["affected_share"] == 0.6667
    assert a["recent_failed_attempts"] == 6  # the 40-day-old attempt is outside the window
    assert a["recent_learners_with_failed_attempts"] == 2
    card = a["activity"]
    assert [s["minutes"] for s in card["steps"]] == [1, 3, 1]
    assert card["board_question"]["question_id"] == q
    assert card["watch_for"] == {
        "source": "class_attempts",
        "option_key": "A",
        "option_text": "option A",
        "wrong_attempts": 6,
    }
    assert "language model" in card["generated_by"]
    b = next(t for t in body["topics"] if t["kc_id"] == w.kc_b)
    assert b["flagged"] is False and "activity" not in b
    assert b["learners_with_evidence"] == 0 and b["average_mastery_probability"] is None
    assert set(b["unmet_criteria"]) == {
        "coverage_below_minimum",
        "too_few_affected_learners",
        "affected_share_below_minimum",
    }
    wide = client.get(
        f"/api/v1/teacher/classes/{cid}/bell-ringer/topics?window_days=60", headers=teacher
    ).json()
    assert next(t for t in wide["topics"] if t["kc_id"] == w.kc_a)["recent_failed_attempts"] == 7


def test_heatmap_cells_never_turn_missing_data_into_zero(ctx) -> None:
    client, w, pg = ctx
    (first, second, third, idle), _q = setup_class(pg, w)
    teacher = login(client, w.teacher_user.login_identifier, w.password)
    cid = w.classroom.classroom_id
    body = client.get(f"/api/v1/teacher/classes/{cid}/heatmap", headers=teacher).json()
    cols = [t["kc_id"] for t in body["topics"]]
    assert {w.kc_a, w.kc_b} <= set(cols) and body["learner_count"] == 4
    rows = {r["learner_id"]: r for r in body["learners"]}
    a, b = cols.index(w.kc_a), cols.index(w.kc_b)
    assert rows[str(first)]["cells"][a]["band"] == "needs_practice"
    assert rows[str(first)]["cells"][a]["attempts"] == 5
    assert rows[str(first)]["cells"][b] == {
        "mastery_probability": None,
        "evidence_count": 1,
        "attempts": 0,
        "correct": 0,
        "last_attempt_at": None,
        "band": "insufficient_evidence",
    }
    assert rows[str(third)]["cells"][a]["band"] == "developing"  # 0.9 is below 0.95
    assert all(c["band"] == "no_data" for c in rows[str(idle)]["cells"])
    assert rows[str(idle)]["average_mastery_probability"] is None
    col_a = body["topics"][a]
    assert col_a["learners_with_estimate"] == 3 and col_a["learners_needing_practice"] == 2
    windowed = client.get(
        f"/api/v1/teacher/classes/{cid}/heatmap?window_days=14", headers=teacher
    ).json()
    second_row = next(r for r in windowed["learners"] if r["learner_id"] == str(second))
    assert second_row["cells"][a]["attempts"] == 1  # the old attempt is outside the window
    assert second_row["cells"][a]["mastery_probability"] == 0.3  # the estimate is current
    other = client.get(
        f"/api/v1/teacher/classes/{cid}/heatmap?subject_id=science", headers=teacher
    ).json()
    assert other["topics"] == [] and all(r["cells"] == [] for r in other["learners"])


def test_bell_ringer_and_heatmap_refuse_other_classes_and_students(ctx) -> None:
    client, w, pg = ctx
    setup_class(pg, w)
    cid = w.classroom.classroom_id
    paths = (
        f"/api/v1/teacher/classes/{cid}/bell-ringer/topics",
        f"/api/v1/teacher/classes/{cid}/heatmap",
        f"/api/v1/teacher/classes/{cid}/bell-ringer/cycles",
    )
    student = login(client, w.student_user.login_identifier, w.pin)
    other = login(client, *other_teacher(pg, w, grade=9))
    for path in paths:
        assert client.get(path, headers=student).status_code == 403, path
        r = client.get(path, headers=other)
        assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden_classroom", path
        assert client.get(path).status_code == 401, path


def test_cycles_answer_503_until_the_migration_is_approved(ctx) -> None:
    client, w, pg = ctx
    teacher = login(client, w.teacher_user.login_identifier, w.password)
    cid = w.classroom.classroom_id
    base = f"/api/v1/teacher/classes/{cid}/bell-ringer/cycles"
    for r in (
        client.get(base, headers=teacher),
        client.post(base, json={"kc_id": w.kc_a}, headers=teacher),
        client.get(f"{base}/{uuid.uuid4()}", headers=teacher),
        client.post(f"{base}/{uuid.uuid4()}/status", json={"status": "completed"}, headers=teacher),
    ):
        assert r.status_code == 503 and r.json()["error"]["code"] == "feature_not_enabled"
    topics = client.get(f"/api/v1/teacher/classes/{cid}/bell-ringer/topics", headers=teacher)
    assert topics.status_code == 200 and topics.json()["cycles_enabled"] is False
