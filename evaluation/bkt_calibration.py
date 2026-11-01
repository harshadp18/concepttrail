"""BKT calibration and evaluation workflow (reproducible; nothing here changes runtime config).

    python -m evaluation.bkt_calibration simulate [--learners 300] [--seed 7]
    python -m evaluation.bkt_calibration real [--min-events 2000]

`simulate` generates SYNTHETIC learners from known parameters, fits parameters on a training
split, and evaluates on held-out learners. It tests the pipeline (does fitting recover known
parameters, are the metrics computed correctly); it is never evidence for production values.
`real` reads attempts read-only, applies the same single-KC eligibility as the mastery engine,
and refuses to fit below `--min-events` scored events or when learners/KCs are too few; it then
reports fitted parameters, held-out metrics and segments by subject and class. Any proposed
configuration still needs review and a new time-versioned `bkt_config_version` row (never an edit
of an existing one). Reports go to `.local/evaluation/` (git-ignored).

Metrics: Brier score, log loss, AUC and a 10-bin calibration table of the one-step-ahead
predicted probability of a correct answer, P(correct) = L(1 - s) + (1 - L) g, against outcomes;
parameter sensitivity is the change in held-out log loss when one parameter moves by +/-0.05.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.services.bkt_service import BKTParameters, observe, transition

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".local/evaluation"
BOUNDS = {
    "initial_knowledge": (0.01, 0.9),
    "learning": (0.01, 0.5),
    "guess": (0.01, 0.4),
    "slip": (0.01, 0.4),
}
EPS = 1e-6


@dataclass(frozen=True)
class Sequence_:
    learner: str
    kc_id: str
    outcomes: tuple[bool, ...]
    subject_id: str = "unknown"
    class_level: int | None = None


def predict(params: BKTParameters, outcomes: Sequence[bool]) -> list[float]:
    """One-step-ahead P(correct) before each observation."""
    mastery, out = params.initial_knowledge, []
    for correct in outcomes:
        out.append(mastery * (1 - params.slip) + (1 - mastery) * params.guess)
        mastery = transition(observe(mastery, correct, params), params)
    return out


def pairs(params: BKTParameters, data: Iterable[Sequence_]) -> list[tuple[float, bool]]:
    return [
        (p, y) for s in data for p, y in zip(predict(params, s.outcomes), s.outcomes, strict=True)
    ]


def log_loss(scored: list[tuple[float, bool]]) -> float:
    return -sum(math.log(max(EPS, p if y else 1 - p)) for p, y in scored) / max(1, len(scored))


def brier(scored: list[tuple[float, bool]]) -> float:
    return sum((p - float(y)) ** 2 for p, y in scored) / max(1, len(scored))


def auc(scored: list[tuple[float, bool]]) -> float | None:
    pos = [p for p, y in scored if y]
    neg = [p for p, y in scored if not y]
    if not pos or not neg:
        return None
    ranked = sorted(scored, key=lambda t: t[0])
    rank_sum, i = 0.0, 0
    while i < len(ranked):  # average ranks for ties
        j = i
        while j < len(ranked) and ranked[j][0] == ranked[i][0]:
            j += 1
        avg = (i + j + 1) / 2
        rank_sum += avg * sum(1 for k in range(i, j) if ranked[k][1])
        i = j
    return (rank_sum - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def calibration(scored: list[tuple[float, bool]], bins: int = 10) -> list[dict]:
    table = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        inside = [(p, y) for p, y in scored if lo <= p < hi or (b == bins - 1 and p == 1.0)]
        if inside:
            table.append(
                {
                    "bin": f"{lo:.1f}-{hi:.1f}",
                    "n": len(inside),
                    "mean_predicted": round(sum(p for p, _ in inside) / len(inside), 4),
                    "observed_rate": round(sum(y for _, y in inside) / len(inside), 4),
                }
            )
    return table


def metrics(params: BKTParameters, data: Sequence[Sequence_]) -> dict:
    scored = pairs(params, data)
    return {
        "events": len(scored),
        "log_loss": round(log_loss(scored), 5),
        "brier": round(brier(scored), 5),
        "auc": None if (a := auc(scored)) is None else round(a, 4),
        "calibration": calibration(scored),
    }


def _with(params: BKTParameters, name: str, value: float) -> BKTParameters:
    lo, hi = BOUNDS[name]
    return BKTParameters(**{**asdict(params), name: min(hi, max(lo, value))})


def fit(data: Sequence[Sequence_], rounds: int = 4, steps: int = 21) -> BKTParameters:
    """Maximum likelihood by coordinate search over bounded 1-D grids (deterministic)."""
    params = BKTParameters(0.3, 0.1, 0.2, 0.1)
    best = log_loss(pairs(params, data))
    for _ in range(rounds):
        for name, (lo, hi) in BOUNDS.items():
            for k in range(steps):
                candidate = _with(params, name, lo + (hi - lo) * k / (steps - 1))
                if candidate.guess + candidate.slip >= 1:  # keep the model identifiable
                    continue
                loss = log_loss(pairs(candidate, data))
                if loss < best - 1e-12:
                    params, best = candidate, loss
    return params


def sensitivity(params: BKTParameters, data: Sequence[Sequence_], delta: float = 0.05) -> dict:
    base = log_loss(pairs(params, data))
    out = {}
    for name in BOUNDS:
        current = getattr(params, name)
        out[name] = {
            f"{sign}{delta}": round(
                log_loss(pairs(_with(params, name, current + s * delta), data)) - base, 5
            )
            for sign, s in (("+", 1), ("-", -1))
        }
    return out


def segments(params: BKTParameters, data: Sequence[Sequence_]) -> dict:
    groups: dict[str, list[Sequence_]] = defaultdict(list)
    for s in data:
        groups[f"{s.subject_id}/class-{s.class_level}"].append(s)
    return {
        k: {kk: v for kk, v in metrics(params, g).items() if kk != "calibration"}
        for k, g in sorted(groups.items())
    }


def split(data: Sequence[Sequence_], seed: int, holdout: float = 0.3):
    learners = sorted({s.learner for s in data})
    random.Random(seed).shuffle(learners)
    test = set(learners[: max(1, int(len(learners) * holdout))])
    return [s for s in data if s.learner not in test], [s for s in data if s.learner in test]


def simulate(
    true: BKTParameters, learners: int, kcs: int, length: int, seed: int
) -> list[Sequence_]:
    rng = random.Random(seed)
    out = []
    for n in range(learners):
        for k in range(kcs):
            known, outcomes = rng.random() < true.initial_knowledge, []
            for _ in range(length):
                p = (1 - true.slip) if known else true.guess
                outcomes.append(rng.random() < p)
                if not known and rng.random() < true.learning:
                    known = True
            out.append(Sequence_(f"L{n}", f"KC{k}", tuple(outcomes), "synthetic", 7 + k % 3))
    return out


def report(kind: str, payload: dict) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"bkt_{kind}_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def run_simulation(learners: int, seed: int) -> dict:
    true = BKTParameters(0.25, 0.12, 0.2, 0.08)
    data = simulate(true, learners, kcs=3, length=12, seed=seed)
    train, test = split(data, seed)
    fitted = fit(train)
    provisional = BKTParameters(0.2, 0.1, 0.2, 0.1)
    return {
        "kind": "SYNTHETIC engineering check (not evidence for production parameters)",
        "seed": seed,
        "true_parameters": asdict(true),
        "fitted_parameters": {k: round(v, 4) for k, v in asdict(fitted).items()},
        "parameter_error": {
            k: round(abs(getattr(fitted, k) - getattr(true, k)), 4) for k in BOUNDS
        },
        "held_out": {
            "true": metrics(true, test),
            "fitted": metrics(fitted, test),
            "provisional_runtime_v1": metrics(provisional, test),
        },
        "sensitivity_fitted": sensitivity(fitted, test),
        "segments_fitted": segments(fitted, test),
    }


def load_real() -> list[Sequence_]:
    """Eligible single-KC scored attempts in time order (read-only engine)."""
    from sqlalchemy import func, select
    from sqlalchemy.orm import Session

    from app.db.models import (
        Attempt,
        CurriculumItem,
        CurriculumVersion,
        KcCurriculumMap,
        KnowledgeComponent,
        QuestionKc,
    )
    from app.db.session import create_db_engine
    from app.services.mastery import HIGH_HINT_TIER

    with Session(create_db_engine(read_only=True)) as db:
        single = (
            select(QuestionKc.question_id)
            .group_by(QuestionKc.question_id)
            .having(func.count() == 1)
        )
        rows = db.execute(
            select(
                Attempt.learner_id,
                QuestionKc.kc_id,
                Attempt.scored_correct,
                Attempt.hint_tier,
                KnowledgeComponent.subject_id,
            )
            .join(QuestionKc, QuestionKc.question_id == Attempt.question_id)
            .join(KnowledgeComponent, KnowledgeComponent.kc_id == QuestionKc.kc_id)
            .where(Attempt.question_id.in_(single), Attempt.scored_correct.is_not(None))
            .order_by(Attempt.learner_id, QuestionKc.kc_id, Attempt.attempted_at)
        ).all()
        levels = dict(
            db.execute(
                select(KcCurriculumMap.kc_id, func.min(CurriculumVersion.class_level))
                .join(CurriculumItem, CurriculumItem.item_id == KcCurriculumMap.item_id)
                .join(
                    CurriculumVersion,
                    CurriculumVersion.curriculum_version_id == CurriculumItem.curriculum_version_id,
                )
                .group_by(KcCurriculumMap.kc_id)
            ).all()
        )
    grouped: dict[tuple, list[bool]] = defaultdict(list)
    subject = {}
    for learner, kc, correct, hint, subj in rows:
        grouped[(str(learner), kc)].append(bool(correct) and (hint or 0) < HIGH_HINT_TIER)
        subject[kc] = subj or "unknown"
    return [
        Sequence_(lr, kc, tuple(o), subject[kc], levels.get(kc)) for (lr, kc), o in grouped.items()
    ]


def run_real(min_events: int, min_learners: int = 30, seed: int = 7) -> dict:
    data = load_real()
    events = sum(len(s.outcomes) for s in data)
    learners = len({s.learner for s in data})
    base = {
        "kind": "real attempts (read-only)",
        "events": events,
        "learners": learners,
        "kcs": len({s.kc_id for s in data}),
        "min_events": min_events,
        "min_learners": min_learners,
    }
    if events < min_events or learners < min_learners:
        return {
            **base,
            "status": "insufficient_data",
            "note": "Too little consented response data to fit or validate parameters; the "
            "runtime configuration stays provisional and uncalibrated.",
        }
    train, test = split(data, seed)
    fitted = fit(train)
    provisional = BKTParameters(0.2, 0.1, 0.2, 0.1)
    return {
        **base,
        "status": "fitted_for_review",
        "fitted_parameters": {k: round(v, 4) for k, v in asdict(fitted).items()},
        "held_out": {
            "fitted": metrics(fitted, test),
            "provisional_runtime_v1": metrics(provisional, test),
        },
        "sensitivity_fitted": sensitivity(fitted, test),
        "segments_fitted": segments(fitted, test),
        "note": "A proposal only: needs review and a new time-versioned configuration row.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.bkt_calibration")
    parser.add_argument("mode", choices=("simulate", "real"))
    parser.add_argument("--learners", type=int, default=300)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--min-events", type=int, default=2000)
    args = parser.parse_args(argv)
    result = (
        run_simulation(args.learners, args.seed)
        if args.mode == "simulate"
        else run_real(args.min_events)
    )
    path = report(args.mode, result)
    summary = {
        k: v
        for k, v in result.items()
        if k not in ("held_out", "segments_fitted", "sensitivity_fitted")
    }
    if "held_out" in result:
        summary["held_out"] = {
            k: {m: v[m] for m in ("events", "log_loss", "brier", "auc")}
            for k, v in result["held_out"].items()
        }
    print(json.dumps(summary, indent=2))
    print(f"report: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
