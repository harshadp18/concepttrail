"""Mastery engine over the existing `attempts` and `student_kc_state` tables.

There is no learning-event table: an attempt is a BKT event for KC k when its question has
exactly one approved KC mapping (k) and the attempt was scored. `student_kc_state.evidence_count`
counts the events applied, in `attempted_at` order, so:

- an event is applied only when `evidence_count` equals the number of eligible events strictly
  before it; if it already includes the event, it is a duplicate and is skipped; any other
  count means the state is out of step and needs `reconcile`, never a silent update;
- the state row is locked (`SELECT ... FOR UPDATE`) for the update, so concurrent attempts by
  the same learner on the same KC serialise;
- the configuration is the `bkt_config_version` in force at `attempted_at`; replay reproduces
  the stored value from history and reports any difference.

Mastery is a model estimate (probability), not a quiz percentage. Parameters are provisional
until fitted on suitable response data.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.content_release import servable_review_statuses
from app.db.models import Attempt, BktConfigVersion, QuestionKc, StudentKcState
from app.services.bkt_service import (
    BKTParameters,
    ConfigVersion,
    observe,
    replay,
    select_config,
    transition,
)

HIGH_HINT_TIER = 2


@dataclass(frozen=True)
class MasteryUpdate:
    updated: bool
    reason: str | None = None
    kc_id: str | None = None
    mastery_probability: float | None = None
    config_version: str | None = None


@dataclass(frozen=True)
class KcMastery:
    kc_id: str
    mastery_probability: float | None
    evidence_count: int
    config_version: str | None
    updated_at: datetime | None
    has_evidence: bool


def load_configs(session: Session) -> list[ConfigVersion]:
    """Every valid stored version; an invalid row is skipped (never guessed)."""
    out = []
    for row in session.scalars(select(BktConfigVersion)):
        if row.effective_at is None or not isinstance(row.parameters, dict):
            continue
        try:
            params = BKTParameters.from_mapping(row.parameters)
        except ValueError:
            continue
        out.append(ConfigVersion(row.bkt_config_version, row.effective_at, params))
    return out


def single_approved_kc(session: Session, question_id: str) -> tuple[str | None, int]:
    kcs = session.scalars(
        select(QuestionKc.kc_id).where(
            QuestionKc.question_id == question_id,
            QuestionKc.review_status.in_(servable_review_statuses()),
        )
    ).all()
    return (kcs[0] if len(kcs) == 1 else None), len(kcs)


def _single_kc_questions(kc_id: str):
    """Questions whose only approved KC mapping is `kc_id`."""
    approved = select(QuestionKc.question_id).where(
        QuestionKc.review_status.in_(servable_review_statuses())
    )
    single = (
        select(QuestionKc.question_id)
        .where(QuestionKc.review_status.in_(servable_review_statuses()))
        .group_by(QuestionKc.question_id)
        .having(func.count() == 1)
    )
    return (
        select(QuestionKc.question_id)
        .where(QuestionKc.kc_id == kc_id, QuestionKc.question_id.in_(approved))
        .where(
            QuestionKc.question_id.in_(single),
            QuestionKc.review_status.in_(servable_review_statuses()),
        )
    )


def eligible_events(session: Session, learner_id: uuid.UUID, kc_id: str) -> list[Attempt]:
    return list(
        session.scalars(
            select(Attempt)
            .where(
                Attempt.learner_id == learner_id,
                Attempt.question_id.in_(_single_kc_questions(kc_id)),
                Attempt.scored_correct.is_not(None),
                Attempt.attempted_at.is_not(None),
            )
            .order_by(Attempt.attempted_at, Attempt.attempt_id)
        )
    )


def observed_correct(attempt: Attempt) -> bool:
    return bool(attempt.scored_correct) and (attempt.hint_tier or 0) < HIGH_HINT_TIER


def _lock_state(session: Session, learner_id: uuid.UUID, kc_id: str) -> StudentKcState | None:
    return session.scalar(
        select(StudentKcState)
        .where(StudentKcState.learner_id == learner_id, StudentKcState.kc_id == kc_id)
        .with_for_update()
    )


def lock_learning_state(session: Session, learner_id: uuid.UUID, kc_id: str) -> None:
    """Take the (learner, KC) row lock BEFORE an attempt is inserted and timestamped.

    Callers then stamp `attempted_at` inside the lock (database clock), so attempts on the same
    KC commit in timestamp order. Without this, a transaction that started earlier but commits
    later would carry an earlier `attempted_at` than an already-applied event and be skipped.
    """
    session.execute(
        insert(StudentKcState)
        .values(learner_id=learner_id, kc_id=kc_id, evidence_count=0)
        .on_conflict_do_nothing(index_elements=["learner_id", "kc_id"])
    )
    _lock_state(session, learner_id, kc_id)


def process_learning_event(session: Session, attempt: Attempt, kc_id: str) -> MasteryUpdate:
    """Apply one flushed attempt to (learner, kc). Does not commit; the caller owns the unit."""
    if attempt.scored_correct is None or attempt.attempted_at is None:
        return MasteryUpdate(False, "attempt_not_scored", kc_id)
    configs = load_configs(session)
    config = select_config(configs, attempt.attempted_at)
    if config is None:
        return MasteryUpdate(False, "versioned_bkt_config_unavailable", kc_id)
    # Create the row if absent without racing another transaction, then lock it.
    session.execute(
        insert(StudentKcState)
        .values(learner_id=attempt.learner_id, kc_id=kc_id, evidence_count=0)
        .on_conflict_do_nothing(index_elements=["learner_id", "kc_id"])
    )
    state = _lock_state(session, attempt.learner_id, kc_id)
    assert state is not None
    session.refresh(state)
    events = eligible_events(session, attempt.learner_id, kc_id)
    ids = [e.attempt_id for e in events]
    if attempt.attempt_id not in ids:
        return MasteryUpdate(False, "attempt_not_eligible_for_kc", kc_id)
    position = ids.index(attempt.attempt_id)
    applied = state.evidence_count or 0
    if applied > position:
        return MasteryUpdate(
            False,
            "duplicate_event_already_applied",
            kc_id,
            state.mastery_probability,
            state.bkt_config_version,
        )
    if applied < position or (applied > 0 and state.mastery_probability is None):
        return MasteryUpdate(False, "state_requires_reconciliation", kc_id)
    prior = (
        config.parameters.initial_knowledge
        if applied == 0 or state.mastery_probability is None
        else float(state.mastery_probability)
    )
    value = transition(
        observe(prior, observed_correct(attempt), config.parameters), config.parameters
    )
    state.mastery_probability = value
    state.bkt_config_version = config.version
    state.updated_at = datetime.now(UTC)
    state.evidence_count = applied + 1
    session.flush()
    reason = (
        "high_tier_hint_counted_as_incorrect"
        if attempt.scored_correct and not observed_correct(attempt)
        else None
    )
    return MasteryUpdate(True, reason, kc_id, value, config.version)


def process_attempt(session: Session, attempt: Attempt) -> MasteryUpdate:
    """Route a flushed attempt to its single approved KC, if any."""
    kc_id, count = single_approved_kc(session, attempt.question_id or "")
    if count > 1:
        return MasteryUpdate(False, "multi_kc_question_requires_kc_specific_evidence")
    if kc_id is None:
        return MasteryUpdate(False, "not_eligible_for_single_kc_update")
    return process_learning_event(session, attempt, kc_id)


def initialize_mastery(session: Session, learner_id: uuid.UUID, kc_id: str) -> KcMastery:
    """No row is written before evidence exists; this returns the no-evidence state."""
    return get_kc_mastery(session, learner_id, kc_id)


def get_kc_mastery(session: Session, learner_id: uuid.UUID, kc_id: str) -> KcMastery:
    state = session.get(StudentKcState, (learner_id, kc_id))
    count = (state.evidence_count or 0) if state else 0
    return KcMastery(
        kc_id,
        float(state.mastery_probability)
        if state and state.mastery_probability is not None
        else None,
        count,
        state.bkt_config_version if state else None,
        state.updated_at if state else None,
        count > 0,
    )


def get_learner_mastery(session: Session, learner_id: uuid.UUID) -> dict[str, KcMastery]:
    rows = session.scalars(select(StudentKcState).where(StudentKcState.learner_id == learner_id))
    return {r.kc_id: get_kc_mastery(session, learner_id, r.kc_id) for r in rows}


@dataclass(frozen=True)
class ReplayResult:
    kc_id: str
    events: int
    replayed_mastery: float | None
    replayed_config_version: str | None
    stored_mastery: float | None
    stored_evidence_count: int
    consistent: bool


def replay_mastery_history(
    session: Session, learner_id: uuid.UUID, kc_id: str, *, tolerance: float = 1e-9
) -> ReplayResult:
    events = eligible_events(session, learner_id, kc_id)
    steps = replay(
        ((e.attempt_id, e.attempted_at, observed_correct(e)) for e in events), load_configs(session)
    )
    stored = get_kc_mastery(session, learner_id, kc_id)
    replayed = steps[-1].mastery if steps else None
    consistent = stored.evidence_count == len(steps) and (
        (replayed is None and stored.mastery_probability is None)
        or (
            replayed is not None
            and stored.mastery_probability is not None
            and abs(replayed - stored.mastery_probability) <= tolerance
        )
    )
    return ReplayResult(
        kc_id,
        len(steps),
        replayed,
        steps[-1].config_version if steps else None,
        stored.mastery_probability,
        stored.evidence_count,
        consistent,
    )


def reconcile(session: Session, learner_id: uuid.UUID, kc_id: str, *, apply: bool = False):
    """Report (and, with `apply`, write) the replayed state. Never deletes; does not commit."""
    result = replay_mastery_history(session, learner_id, kc_id)
    if apply and not result.consistent:
        state = _lock_state(session, learner_id, kc_id)
        if state is None and result.events:
            state = StudentKcState(learner_id=learner_id, kc_id=kc_id)
            session.add(state)
        if state is not None:
            state.mastery_probability = result.replayed_mastery
            state.bkt_config_version = result.replayed_config_version
            state.evidence_count = result.events
            state.updated_at = datetime.now(UTC)
            session.flush()
    return result
