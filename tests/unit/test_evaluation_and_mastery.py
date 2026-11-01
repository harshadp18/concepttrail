"""Deterministic scoring, BKT maths, and the live mastery engine (rolled back; synthetic)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from live_db_fixtures import World, live_engine, pg_fixture  # noqa: F401  (fixtures)
from sqlalchemy import select

from app.db.models import Attempt, StudentKcState
from app.services import mastery
from app.services.bkt_service import (
    BKTParameters,
    ConfigVersion,
    observe,
    replay,
    select_config,
    transition,
    update_mastery,
)
from app.services.evaluation import (
    Option,
    QuestionKey,
    build_learning_evidence,
    evaluate_answer,
)

OPTS = (Option("A", False), Option("B", True), Option("C", False))


def q(kind: str, **kw) -> QuestionKey:
    return QuestionKey("Q1", 1, kind, **kw)


# --- evaluation ------------------------------------------------------------------------


def test_single_choice() -> None:
    assert (
        evaluate_answer(q("single_choice", options=OPTS), {"option_key": "B"}).status == "correct"
    )
    wrong = evaluate_answer(q("single_choice", options=OPTS), {"option_key": "A"})
    assert wrong.status == "incorrect" and wrong.score == Decimal("0.0")
    assert (
        evaluate_answer(q("single_choice", options=OPTS), {"option_key": "Z"}).status == "invalid"
    )
    assert evaluate_answer(q("single_choice", options=OPTS), {"x": 1}).status == "invalid"
    two = (Option("A", True), Option("B", True), Option("C", False))
    assert (
        evaluate_answer(q("single_choice", options=two), {"option_key": "A"}).reason
        == "answer_key_invalid"
    )


def test_multiple_select_is_exact_set() -> None:
    opts = (Option("A", True), Option("B", False), Option("C", True))
    assert evaluate_answer(q("multiple_select", options=opts), {"option_keys": ["C", "A"]}).correct
    assert not evaluate_answer(q("multiple_select", options=opts), {"option_keys": ["A"]}).correct
    assert (
        evaluate_answer(q("multiple_select", options=opts), {"option_keys": ["A", "A"]}).status
        == "invalid"
    )


def test_true_false_and_numeric_tolerance() -> None:
    tf = q("true_false", expected_answer={"value": False})
    assert evaluate_answer(tf, {"value": False}).correct
    assert evaluate_answer(tf, {"value": "false"}).status == "invalid"
    num = q("numeric", expected_answer={"value": 3.5, "abs_tolerance": 0.01})
    assert evaluate_answer(num, {"value": "3.509"}).correct
    assert not evaluate_answer(num, {"value": 3.52}).correct
    assert evaluate_answer(num, {"value": "three"}).status == "invalid"
    assert evaluate_answer(num, {"value": float("nan")}).status == "invalid"
    rel = q("numeric", expected_answer={"value": 1000, "rel_tolerance": 0.01})
    assert evaluate_answer(rel, {"value": "1,009"}).correct
    broken = q("numeric", expected_answer={"value": 1, "abs_tolerance": -1})
    assert evaluate_answer(broken, {"value": 1}).status == "review_required"


def test_free_text_is_never_auto_scored() -> None:
    for kind in ("short_answer", "structured_response"):
        assert evaluate_answer(q(kind), {"text": "anything"}).status == "review_required"
    assert evaluate_answer(q("essay"), {"text": "x"}).reason == "unsupported_item_type"


def test_learning_evidence_rules() -> None:
    right = evaluate_answer(q("single_choice", options=OPTS), {"option_key": "B"})
    events, why = build_learning_evidence(right, ["K1"])
    assert [(e.kc_id, e.observed_correct) for e in events] == [("K1", True)] and why is None
    events, _ = build_learning_evidence(right, ["K1"], hint_tier=2)
    assert events[0].observed_correct is False and events[0].reason
    assert build_learning_evidence(right, ["K1", "K2"]) == (
        [],
        "multi_kc_question_requires_kc_specific_evidence",
    )
    events, _ = build_learning_evidence(
        right, ["K1", "K2"], per_kc_correct={"K1": True, "K2": False}
    )
    assert [(e.kc_id, e.observed_correct) for e in events] == [("K1", True), ("K2", False)]
    review = evaluate_answer(q("short_answer"), {"text": "x"})
    assert build_learning_evidence(review, ["K1"])[1] == "not_scored:review_required"


# --- BKT maths --------------------------------------------------------------------------

P = BKTParameters(0.30, 0.15, 0.20, 0.10)


def test_bkt_steps_exact() -> None:
    # correct: 0.3*0.9 / (0.27 + 0.7*0.2) = 0.27/0.41
    assert observe(0.3, True, P) == pytest.approx(0.27 / 0.41)
    assert transition(0.27 / 0.41, P) == pytest.approx(0.27 / 0.41 + (1 - 0.27 / 0.41) * 0.15)
    # incorrect: 0.3*0.1 / (0.03 + 0.7*0.8)
    assert observe(0.3, False, P) == pytest.approx(0.03 / 0.59)
    assert update_mastery(0.3, True, P) == pytest.approx(0.7097560975609757)  # teammate value
    with pytest.raises(ValueError):
        observe(1.5, True, P)
    with pytest.raises(ValueError):
        BKTParameters.from_mapping({"p_l0": 0.2, "p_t": 0.1, "p_g": 0.6, "p_s": 0.5})


def test_sequential_updates_and_version_transition() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    v1 = ConfigVersion("v1", t0, P)
    v2 = ConfigVersion("v2", t0 + timedelta(days=10), BKTParameters(0.5, 0.05, 0.25, 0.05))
    assert select_config([v1, v2], t0 - timedelta(days=1)) is None
    assert select_config([v1, v2], t0 + timedelta(days=5)).version == "v1"
    assert select_config([v1, v2], t0 + timedelta(days=11)).version == "v2"
    obs = [
        ("a", t0 + timedelta(days=1), True),
        ("b", t0 + timedelta(days=2), False),
        ("c", t0 + timedelta(days=12), True),
    ]
    steps = replay(obs, [v1, v2])
    m1 = update_mastery(0.3, True, P)
    m2 = update_mastery(m1, False, P)
    m3 = update_mastery(m2, True, v2.parameters)  # carries the estimate, new parameters
    assert [s.mastery for s in steps] == pytest.approx([m1, m2, m3])
    assert [s.config_version for s in steps] == ["v1", "v1", "v2"]
    assert replay(list(reversed(obs)), [v1, v2]) == steps  # order by time, not input order


# --- live mastery engine ------------------------------------------------------------------


def attempt(world: World, qid: str, correct: bool, at: datetime, hint: int = 0) -> Attempt:
    a = Attempt(
        attempt_id=uuid.uuid4(),
        learner_id=world.learner.learner_id,
        question_id=qid,
        question_version=1,
        submitted_answer={"option_key": "B" if correct else "A"},
        scored_correct=correct,
        score=Decimal(int(correct)),
        score_method="single_choice_option_key_v1",
        hint_tier=hint,
        attempted_at=at,
        idempotency_key=f"syn-{uuid.uuid4().hex}",
    )
    world.s.add(a)
    world.s.flush()
    return a


@pytest.mark.live_db
def test_live_sequential_duplicate_hint_and_replay(pg) -> None:
    w = World(pg)
    base = datetime(2026, 6, 1, tzinfo=UTC)
    w.config("cfg", base - timedelta(days=1))
    qid = w.question([w.kc_a])
    a1 = attempt(w, qid, True, base)
    r1 = mastery.process_attempt(pg, a1)
    assert r1.updated and r1.mastery_probability == pytest.approx(update_mastery(0.3, True, P))
    assert mastery.process_attempt(pg, a1).reason == "duplicate_event_already_applied"
    a2 = attempt(w, qid, True, base + timedelta(minutes=1), hint=2)
    r2 = mastery.process_attempt(pg, a2)
    assert r2.reason == "high_tier_hint_counted_as_incorrect"
    assert r2.mastery_probability == pytest.approx(update_mastery(r1.mastery_probability, False, P))
    state = pg.get(StudentKcState, (w.learner.learner_id, w.kc_a))
    assert state.evidence_count == 2 and state.bkt_config_version == f"cfg-{w.tag}"
    result = mastery.replay_mastery_history(pg, w.learner.learner_id, w.kc_a)
    assert result.consistent and result.events == 2
    view = mastery.get_kc_mastery(pg, w.learner.learner_id, w.kc_a)
    assert view.has_evidence and view.mastery_probability == pytest.approx(r2.mastery_probability)
    assert not mastery.get_kc_mastery(pg, w.learner.learner_id, w.kc_b).has_evidence


@pytest.mark.live_db
def test_live_reconciliation_and_out_of_step_state(pg) -> None:
    w = World(pg)
    base = datetime(2026, 6, 1, tzinfo=UTC)
    w.config("cfg", base - timedelta(days=1))
    qid = w.question([w.kc_a])
    a1 = attempt(w, qid, True, base)
    a2 = attempt(w, qid, False, base + timedelta(minutes=1))
    # a2 cannot be applied before a1: the state is out of step, nothing is written
    assert mastery.process_attempt(pg, a2).reason == "state_requires_reconciliation"
    report = mastery.reconcile(pg, w.learner.learner_id, w.kc_a, apply=True)
    assert not report.consistent and report.events == 2
    assert mastery.replay_mastery_history(pg, w.learner.learner_id, w.kc_a).consistent
    assert mastery.process_attempt(pg, a1).reason == "duplicate_event_already_applied"


@pytest.mark.live_db
def test_live_multi_kc_and_unapproved_mapping_and_no_config(pg) -> None:
    w = World(pg)
    base = datetime(2026, 6, 1, tzinfo=UTC)
    multi = w.question([w.kc_a, w.kc_b])
    assert (
        mastery.process_attempt(pg, attempt(w, multi, True, base)).reason
        == "multi_kc_question_requires_kc_specific_evidence"
    )
    unapproved = w.question([w.kc_a], mapping_status="needs_review")
    assert not mastery.process_attempt(pg, attempt(w, unapproved, True, base)).updated
    early = w.question([w.kc_b])
    old = attempt(w, early, True, datetime(2020, 1, 1, tzinfo=UTC))
    assert mastery.process_attempt(pg, old).reason == "versioned_bkt_config_unavailable"
    assert pg.scalar(select(StudentKcState).where(StudentKcState.kc_id == w.kc_b)) is None


@pytest.mark.live_db
def test_live_config_version_transition_is_traceable(pg) -> None:
    w = World(pg)
    base = datetime(2026, 6, 1, tzinfo=UTC)
    w.config("old", base - timedelta(days=1))
    w.config("new", base + timedelta(days=1), p_l0=0.5, p_t=0.05)
    qid = w.question([w.kc_a])
    assert mastery.process_attempt(pg, attempt(w, qid, True, base)).config_version == f"old-{w.tag}"
    late = mastery.process_attempt(pg, attempt(w, qid, True, base + timedelta(days=2)))
    assert late.config_version == f"new-{w.tag}"
    assert mastery.replay_mastery_history(pg, w.learner.learner_id, w.kc_a).consistent


def test_state_update_takes_a_row_lock() -> None:
    from sqlalchemy.dialects import postgresql

    statement = select(StudentKcState).with_for_update()
    assert "FOR UPDATE" in str(statement.compile(dialect=postgresql.dialect()))
    import inspect

    assert "with_for_update" in inspect.getsource(mastery._lock_state)
