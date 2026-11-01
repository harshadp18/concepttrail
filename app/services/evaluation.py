"""Deterministic answer evaluation. No model is ever consulted for scoring.

Supported `questions.item_type` values and their answer shapes:

- `single_choice` (alias `mcq`): `{"option_key": "B"}`; key: exactly one correct option.
- `multiple_select`: `{"option_keys": ["A", "C"]}`; key: the exact set (all-or-nothing).
- `true_false`: `{"value": true}`; key: `expected_answer = {"value": true}`.
- `numeric`: `{"value": "3.5"}` or a number; key: `expected_answer = {"value": 3.5,
  "abs_tolerance": 0.01, "rel_tolerance": 0}`.
- `short_answer`, `structured_response`: free text, **never auto-scored** (`review_required`).

A result is `correct`, `incorrect`, `invalid` (malformed submission) or `review_required`
(no deterministic key, or the key itself is broken). Only `correct`/`incorrect` produce a BKT
evidence event, and only for a single approved KC unless the rubric gives per-KC scores.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

SINGLE = ("single_choice", "mcq", "mcq_single")
MULTIPLE = ("multiple_select", "mcq_multi")
SUPPORTED = (*SINGLE, *MULTIPLE, "true_false", "numeric")
REVIEW_ONLY = ("short_answer", "structured_response", "long_answer")
SCORE_METHODS = {
    "single": "single_choice_option_key_v1",
    "multiple": "multiple_select_exact_set_v1",
    "true_false": "true_false_exact_v1",
    "numeric": "numeric_tolerance_v1",
}


@dataclass(frozen=True)
class Option:
    option_key: str
    is_correct: bool
    option_id: Any = None


@dataclass(frozen=True)
class QuestionKey:
    question_id: str
    version: int
    item_type: str
    options: tuple[Option, ...] = ()
    expected_answer: Mapping[str, Any] | None = None
    rubric: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class Evaluation:
    status: str  # correct | incorrect | invalid | review_required
    score: Decimal | None
    score_method: str | None
    reason: str | None = None
    normalized_answer: dict[str, Any] = field(default_factory=dict)

    @property
    def scored(self) -> bool:
        return self.status in ("correct", "incorrect")

    @property
    def correct(self) -> bool:
        return self.status == "correct"


def _result(correct: bool, method: str, answer: dict[str, Any]) -> Evaluation:
    return Evaluation(
        "correct" if correct else "incorrect",
        Decimal("1.0") if correct else Decimal("0.0"),
        SCORE_METHODS[method],
        None,
        answer,
    )


def _invalid(reason: str) -> Evaluation:
    return Evaluation("invalid", None, None, reason)


def _review(reason: str) -> Evaluation:
    return Evaluation("review_required", None, None, reason)


def validate_submission(question: QuestionKey, submitted: Any) -> str | None:
    """Return a reason the submission is malformed for this question type, else None."""
    if not isinstance(submitted, Mapping):
        return "answer_must_be_an_object"
    kind = question.item_type
    if kind in SINGLE:
        key = submitted.get("option_key")
        return (
            None
            if isinstance(key, str) and key.strip() and set(submitted) == {"option_key"}
            else "expected_option_key"
        )
    if kind in MULTIPLE:
        keys = submitted.get("option_keys")
        if set(submitted) != {"option_keys"} or not isinstance(keys, list) or not keys:
            return "expected_option_keys"
        if not all(isinstance(k, str) and k.strip() for k in keys):
            return "expected_option_keys"
        if len({k.strip() for k in keys}) != len(keys):
            return "duplicate_option_keys"
        return None
    if kind == "true_false":
        return (
            None
            if set(submitted) == {"value"} and isinstance(submitted["value"], bool)
            else "expected_boolean_value"
        )
    if kind == "numeric":
        if set(submitted) != {"value"}:
            return "expected_numeric_value"
        return None if _number(submitted["value"]) is not None else "not_a_number"
    return None


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return Decimal(str(value))
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text or len(text) > 40:
            return None
        try:
            number = Decimal(text)
        except InvalidOperation:
            return None
        return number if number.is_finite() else None
    return None


def evaluate_answer(question: QuestionKey, submitted: Any) -> Evaluation:
    kind = question.item_type
    if kind in REVIEW_ONLY:
        return _review("requires_rubric_review")
    if kind not in SUPPORTED:
        return _review("unsupported_item_type")
    if problem := validate_submission(question, submitted):
        return _invalid(problem)
    if kind in SINGLE or kind in MULTIPLE:
        keys = [o.option_key for o in question.options]
        if len(set(keys)) != len(keys) or not keys:
            return _review("answer_key_invalid")
        correct = {o.option_key for o in question.options if o.is_correct}
        if kind in SINGLE:
            if len(correct) != 1:
                return _review("answer_key_invalid")
            chosen = submitted["option_key"].strip()
            if chosen not in keys:
                return _invalid("unknown_option_key")
            return _result(chosen in correct, "single", {"option_key": chosen})
        if len(correct) < 1:
            return _review("answer_key_invalid")
        chosen_set = {k.strip() for k in submitted["option_keys"]}
        if not chosen_set <= set(keys):
            return _invalid("unknown_option_key")
        return _result(chosen_set == correct, "multiple", {"option_keys": sorted(chosen_set)})
    expected = question.expected_answer or {}
    if kind == "true_false":
        if not isinstance(expected.get("value"), bool):
            return _review("answer_key_invalid")
        value = submitted["value"]
        return _result(value is expected["value"], "true_false", {"value": value})
    # numeric
    target = _number(expected.get("value"))
    abs_tol = _number(expected.get("abs_tolerance", 0))
    rel_tol = _number(expected.get("rel_tolerance", 0))
    if target is None or abs_tol is None or rel_tol is None or abs_tol < 0 or rel_tol < 0:
        return _review("answer_key_invalid")
    value = _number(submitted["value"])
    assert value is not None  # validated above
    allowed = max(abs_tol, rel_tol * abs(target))
    return _result(abs(value - target) <= allowed, "numeric", {"value": str(value)})


@dataclass(frozen=True)
class LearningEvidence:
    kc_id: str
    observed_correct: bool
    reason: str | None = None


def build_learning_evidence(
    evaluation: Evaluation,
    approved_kc_ids: Sequence[str],
    hint_tier: int = 0,
    *,
    per_kc_correct: Mapping[str, bool] | None = None,
    high_hint_tier: int = 2,
) -> tuple[list[LearningEvidence], str | None]:
    """BKT evidence events for one scored attempt, and why none were produced if so.

    One correctness value is never copied to several KCs: a multi-KC question needs
    KC-specific evidence in `per_kc_correct`. A correct answer given with a high-tier hint
    (tier >= 2) is observed as incorrect (the existing attempt-policy rule).
    """
    if not evaluation.scored:
        return [], f"not_scored:{evaluation.status}"
    kcs = sorted(set(approved_kc_ids))
    if not kcs:
        return [], "no_approved_kc_mapping"

    def observed(correct: bool) -> bool:
        return correct and hint_tier < high_hint_tier

    note = (
        "high_tier_hint_counted_as_incorrect"
        if evaluation.correct and hint_tier >= high_hint_tier
        else None
    )
    if len(kcs) == 1:
        return [LearningEvidence(kcs[0], observed(evaluation.correct), note)], None
    if per_kc_correct is None or set(per_kc_correct) != set(kcs):
        return [], "multi_kc_question_requires_kc_specific_evidence"
    return [LearningEvidence(k, observed(per_kc_correct[k]), note) for k in kcs], None
