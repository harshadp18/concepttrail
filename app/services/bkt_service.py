"""Pure Bayesian Knowledge Tracing update logic.

Runtime parameters are supplied by a versioned database configuration. This module
never chooses or silently invents production parameters.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class BKTParameters:
    initial_knowledge: float
    learning: float
    guess: float
    slip: float

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> BKTParameters:
        """Parse the canonical versioned JSON keys and validate probabilities.

        Canonical keys: p_l0, p_t, p_g, p_s. The long names are also accepted to
        make stored configuration self-documenting.
        """
        aliases = {
            "initial_knowledge": ("p_l0", "initial_knowledge"),
            "learning": ("p_t", "learning"),
            "guess": ("p_g", "guess"),
            "slip": ("p_s", "slip"),
        }
        values: dict[str, float] = {}
        for field, keys in aliases.items():
            value = next((raw[key] for key in keys if key in raw), None)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"BKT configuration is missing numeric {keys[0]}")
            number = float(value)
            if not 0.0 <= number <= 1.0:
                raise ValueError(f"BKT parameter {keys[0]} must be between 0 and 1")
            values[field] = number
        if values["guess"] + values["slip"] >= 1.0:
            raise ValueError("BKT guess plus slip must be less than 1")
        if values["learning"] >= 1.0:
            raise ValueError("BKT learning probability must be less than 1")
        return cls(**values)


def observe(current_mastery: float, observed_correct: bool, params: BKTParameters) -> float:
    """The Bayes step only: P(L | observation), before any learning transition."""
    if not 0.0 <= current_mastery <= 1.0:
        raise ValueError("current_mastery must be between 0 and 1")
    if observed_correct:
        numerator = current_mastery * (1.0 - params.slip)
        denominator = numerator + (1.0 - current_mastery) * params.guess
    else:
        numerator = current_mastery * params.slip
        denominator = numerator + (1.0 - current_mastery) * (1.0 - params.guess)
    if denominator <= 0.0:
        raise ValueError("BKT observation has zero probability under the supplied parameters")
    return numerator / denominator


def transition(posterior: float, params: BKTParameters) -> float:
    """The learning step: P(L_next) = P(L|obs) + [1 - P(L|obs)] T."""
    return min(1.0, max(0.0, posterior + (1.0 - posterior) * params.learning))


def update_mastery(current_mastery: float, observed_correct: bool, params: BKTParameters) -> float:
    """Apply one standard BKT observation and learning transition.

    Formula:
      P(L|correct) = L(1-S) / [L(1-S) + (1-L)G]
      P(L|wrong)   = LS / [LS + (1-L)(1-G)]
      P(L_next)    = P(L|obs) + [1-P(L|obs)]T
    """
    return transition(observe(current_mastery, observed_correct, params), params)


@dataclass(frozen=True)
class ConfigVersion:
    """One `bkt_config_version` row, parsed. Parameters are provisional until fitted."""

    version: str
    effective_at: datetime
    parameters: BKTParameters


def select_config(configs: Iterable[ConfigVersion], at: datetime) -> ConfigVersion | None:
    """The version in force at `at`: the latest `effective_at` not after it (ties: by name)."""
    eligible = [c for c in configs if c.effective_at <= at]
    return max(eligible, key=lambda c: (c.effective_at, c.version)) if eligible else None


@dataclass(frozen=True)
class ReplayStep:
    attempt_id: object
    observed_correct: bool
    config_version: str
    prior: float
    posterior: float
    mastery: float


def replay(
    observations: Iterable[tuple[object, datetime, bool]],
    configs: Iterable[ConfigVersion],
) -> list[ReplayStep]:
    """Recompute mastery from ordered (attempt_id, attempted_at, observed_correct) events.

    The prior starts at P(L0) of the version in force at the first event. When the version
    changes mid-history, the running estimate carries over and later steps use the new
    parameters (the configuration is never applied retroactively). Events without a version in
    force are skipped (no estimate can be made for them).
    """
    configs = list(configs)
    steps: list[ReplayStep] = []
    mastery: float | None = None
    for attempt_id, at, correct in sorted(observations, key=lambda o: (o[1], str(o[0]))):
        config = select_config(configs, at)
        if config is None:
            continue
        prior = config.parameters.initial_knowledge if mastery is None else mastery
        posterior = observe(prior, correct, config.parameters)
        mastery = transition(posterior, config.parameters)
        steps.append(ReplayStep(attempt_id, correct, config.version, prior, posterior, mastery))
    return steps
