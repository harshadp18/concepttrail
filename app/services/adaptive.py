"""Deterministic adaptive recommendation engine (no randomness, no model).

Inputs: the released prerequisite graph, the learner's BKT mastery estimates (probabilities,
not quiz percentages), approved-question availability and the learner's scope. Thresholds are
**provisional policy values**, not empirically calibrated; they are explicit and versioned.

Policy (`adaptive-policy-v1`):
1. No released graph → `insufficient_data: graph_not_released` (never recommend raw KCs).
2. Candidates are released, active KCs in scope (declared class matches, or foundation KCs
   that a scoped KC depends on). Mastered KCs (p ≥ `mastery_target`) are done.
3. A KC is blocked while any direct prerequisite is below `prerequisite_ready` or has no
   evidence; its unmet prerequisites become remediation candidates.
4. Only KCs with at least one approved question are recommendable.
5. Rank: remediation gaps first, then KCs in progress (lowest mastery first), then new KCs;
   ties by graph layer, then by how many scoped KCs it unblocks (desc), then KC ID.
6. The question is an approved one not yet attempted whose difficulty is closest to the
   learner's estimate (1 + 4p); ties by question ID.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Attempt
from app.services.graph_runtime import GraphUnavailable, ReleasedGraph
from app.services.mastery import get_learner_mastery
from app.services.question_bank import get_approved_questions

POLICY_VERSION = "adaptive-policy-v1"


@dataclass(frozen=True)
class Thresholds:
    mastery_target: float = 0.95
    prerequisite_ready: float = 0.70
    provisional: bool = True


DEFAULT_THRESHOLDS = Thresholds()


@dataclass(frozen=True)
class MasteryView:
    probability: float | None
    evidence_count: int

    @property
    def has_evidence(self) -> bool:
        return self.evidence_count > 0 and self.probability is not None


@dataclass(frozen=True)
class QuestionView:
    question_id: str
    difficulty: int | None


@dataclass(frozen=True)
class Candidate:
    kc_id: str
    category: Literal["remediate_prerequisite", "continue", "new"]
    mastery: float | None
    layer: int
    unblocks: int
    rationale: tuple[str, ...]

    def sort_key(self) -> tuple:
        order = {"remediate_prerequisite": 0, "continue": 1, "new": 2}[self.category]
        mastery = self.mastery if self.mastery is not None else 1.0
        return (
            order,
            mastery if self.category == "continue" else 0.0,
            self.layer,
            -self.unblocks,
            self.kc_id,
        )


@dataclass(frozen=True)
class Recommendation:
    kc_id: str
    question_id: str
    category: str
    rationale: tuple[str, ...]
    mastery: float | None
    policy_version: str
    graph_version: str
    thresholds: Thresholds
    status: Literal["ok"] = "ok"


@dataclass(frozen=True)
class InsufficientData:
    reason: str
    detail: tuple[str, ...] = ()
    policy_version: str = POLICY_VERSION
    status: Literal["insufficient_data"] = "insufficient_data"


@dataclass(frozen=True)
class LearnerScope:
    class_level: int
    subject_ids: tuple[str, ...] | None = None


@dataclass
class _Ranking:
    candidates: list[Candidate] = field(default_factory=list)
    blocked: dict[str, list[str]] = field(default_factory=dict)
    mastered: list[str] = field(default_factory=list)


def rank_learning_candidates(
    released: ReleasedGraph,
    scope: LearnerScope,
    mastery: Mapping[str, MasteryView],
    question_counts: Mapping[str, int],
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> _Ranking:
    graph = released.graph
    layer = {k: i for i, layer_ids in enumerate(graph.layers()) for k in layer_ids}

    def view(kc_id: str) -> MasteryView:
        return mastery.get(kc_id, MasteryView(None, 0))

    def in_scope(kc_id: str) -> bool:
        kc = released.kcs[kc_id]
        if scope.subject_ids is not None and kc["subject_id"] not in scope.subject_ids:
            return False
        return kc.get("scope") == "target" and scope.class_level in kc.get("class_levels", [])

    scoped = sorted(k for k in released.kcs if in_scope(k))
    result = _Ranking()
    gaps: dict[str, set[str]] = {}
    for kc_id in scoped:
        v = view(kc_id)
        if v.has_evidence and v.probability >= thresholds.mastery_target:  # type: ignore[operator]
            result.mastered.append(kc_id)
            continue
        unmet = [
            p
            for p in graph.direct_prerequisites(kc_id)
            if not view(p).has_evidence or view(p).probability < thresholds.prerequisite_ready
        ]  # type: ignore[operator]
        if unmet:
            result.blocked[kc_id] = unmet
            for p in unmet:
                gaps.setdefault(p, set()).add(kc_id)
            continue
        if question_counts.get(kc_id, 0) < 1:
            continue
        if v.has_evidence:
            why = (
                f"in progress: mastery estimate {v.probability:.2f} below target "
                f"{thresholds.mastery_target:.2f} after {v.evidence_count} observations",
            )
            category = "continue"
        else:
            why = ("no evidence yet for this KC (missing evidence, not low mastery)",)
            category = "new"
        prereqs = graph.direct_prerequisites(kc_id)
        if prereqs:
            why += (f"prerequisites ready: {', '.join(prereqs)}",)
        result.candidates.append(
            Candidate(kc_id, category, v.probability, layer.get(kc_id, 0), 0, why)
        )  # type: ignore[arg-type]
    for gap, dependents in sorted(gaps.items()):
        v = view(gap)
        if question_counts.get(gap, 0) < 1:
            continue
        if any(
            not view(p).has_evidence or view(p).probability < thresholds.prerequisite_ready  # type: ignore[operator]
            for p in graph.direct_prerequisites(gap)
        ):
            continue  # its own prerequisites come first; they surface as gaps of gaps later
        state = f"low mastery {v.probability:.2f}" if v.has_evidence else "no evidence"
        why = (
            f"prerequisite gap ({state}, below readiness {thresholds.prerequisite_ready:.2f})",
            f"blocks: {', '.join(sorted(dependents))}",
        )
        result.candidates.append(
            Candidate(
                gap,
                "remediate_prerequisite",
                v.probability,
                layer.get(gap, 0),
                len(dependents),
                why,
            )
        )
    gap_ids = {c.kc_id for c in result.candidates if c.category == "remediate_prerequisite"}
    result.candidates = [
        c
        for c in result.candidates
        if c.category == "remediate_prerequisite" or c.kc_id not in gap_ids
    ]
    result.candidates.sort(key=Candidate.sort_key)
    return result


def choose_question(
    questions: Sequence[QuestionView], attempted: set[str], mastery: float | None
) -> QuestionView | None:
    target = 1 + 4 * (mastery if mastery is not None else 0.0)
    fresh = [q for q in questions if q.question_id not in attempted] or list(questions)
    if not fresh:
        return None
    return min(fresh, key=lambda q: (abs((q.difficulty or 3) - target), q.question_id))


def recommend(
    released: ReleasedGraph | GraphUnavailable,
    scope: LearnerScope,
    mastery: Mapping[str, MasteryView],
    questions: Mapping[str, Sequence[QuestionView]],
    attempted: set[str],
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> Recommendation | InsufficientData:
    if not isinstance(released, ReleasedGraph):
        return InsufficientData(released.reason, released.detail)
    ranking = rank_learning_candidates(
        released, scope, mastery, {k: len(v) for k, v in questions.items()}, thresholds
    )
    for candidate in ranking.candidates:
        question = choose_question(questions.get(candidate.kc_id, ()), attempted, candidate.mastery)
        if question is not None:
            return Recommendation(
                candidate.kc_id,
                question.question_id,
                candidate.category,
                candidate.rationale,
                candidate.mastery,
                POLICY_VERSION,
                released.version,
                thresholds,
            )
    if ranking.mastered and not ranking.candidates and not ranking.blocked:
        return InsufficientData("all_scoped_kcs_mastered", tuple(ranking.mastered))
    if not any(released.kcs.get(k) for k in released.kcs):
        return InsufficientData("no_kcs_released")
    return InsufficientData(
        "no_recommendable_content",
        tuple(f"{k} blocked by {', '.join(v)}" for k, v in sorted(ranking.blocked.items())),
    )


def explain_recommendation(rec: Recommendation | InsufficientData) -> dict[str, object]:
    if isinstance(rec, InsufficientData):
        return {
            "status": rec.status,
            "reason": rec.reason,
            "detail": list(rec.detail),
            "policy_version": rec.policy_version,
        }
    return {
        "status": "ok",
        "kc_id": rec.kc_id,
        "question_id": rec.question_id,
        "category": rec.category,
        "rationale": list(rec.rationale),
        "mastery_probability": rec.mastery,
        "policy_version": rec.policy_version,
        "graph_version": rec.graph_version,
        "thresholds": {
            "mastery_target": rec.thresholds.mastery_target,
            "prerequisite_ready": rec.thresholds.prerequisite_ready,
            "provisional": rec.thresholds.provisional,
        },
    }


def recommend_next_learning_step(
    session: Session,
    learner_id: uuid.UUID,
    released: ReleasedGraph | GraphUnavailable,
    scope: LearnerScope,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> Recommendation | InsufficientData:
    """Database wrapper: real mastery, approved questions and attempt history."""
    if not isinstance(released, ReleasedGraph):
        return InsufficientData(released.reason, released.detail)
    states = get_learner_mastery(session, learner_id)
    mastery = {k: MasteryView(v.mastery_probability, v.evidence_count) for k, v in states.items()}
    questions = {
        kc_id: [
            QuestionView(q.question_id, q.difficulty)
            for q in get_approved_questions(session, kc_id)
        ]
        for kc_id in released.kcs
    }
    attempted = set(
        session.scalars(
            select(Attempt.question_id).where(Attempt.learner_id == learner_id).distinct()
        )
    )
    return recommend(released, scope, mastery, questions, attempted, thresholds)
