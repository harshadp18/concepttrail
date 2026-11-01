# ruff: noqa: E501  (report tables are prose; long lines are intentional)
"""Synthetic BKT calibration study: parameter recovery, held-out prediction, robustness.

    python -m evaluation.bkt_synthetic            # full study (a few minutes)
    python -m evaluation.bkt_synthetic --quick    # reduced grid for smoke runs and tests

Everything is SYNTHETIC (`evaluation.synthetic_learners`): it tests whether the calibration
machinery recovers known parameters and how BKT predictions behave, not what real learners do.
Calibration and held-out data always come from different seeds (disjoint simulated learners);
generating parameters are never given to the fitter. The fitted parameter sets are written as an
EXPERIMENTAL configuration (`evaluation/configs/bkt_synthetic_calibration_v1.json`); the runtime
configuration `bkt-provisional-v1` is not read, changed or replaced.

Fitting maximises the BKT likelihood with the runtime equations (`app.services.bkt_service`,
vectorised here and checked against the scalar code) under the standard identifiability
constraints guess < 0.5 and slip < 0.5 (Baker, Corbett & Aleven 2008): without them "knowing the
skill makes errors more likely" solutions fit equally well.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from app.services.bkt_service import BKTParameters, observe, transition
from evaluation.synthetic_learners import KC_TYPES, Dataset, KcTruth, Mismatch, generate

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".local/evaluation/reports"
DATA_OUT = ROOT / ".local/evaluation/synthetic"
CONFIG_OUT = ROOT / "evaluation/configs/bkt_synthetic_calibration_v1.json"
NAMES = ("p_l0", "p_t", "p_g", "p_s")
BOUNDS = {"p_l0": (0.01, 0.95), "p_t": (0.005, 0.6), "p_g": (0.01, 0.49), "p_s": (0.01, 0.49)}
MASTERY = 0.95
PROVISIONAL = np.array([0.2, 0.1, 0.2, 0.1])
CAL_SEED, TEST_SEED = 1000, 2000  # calibration and held-out seeds never overlap
EPS = 1e-9

# --- the BKT forward pass (vectorised runtime equations) ----------------------------------------------


def forward(params: np.ndarray, ds: Dataset) -> tuple[np.ndarray, np.ndarray]:
    """P(correct) before each opportunity and P(known) before each opportunity."""
    l0, t, g, s = params
    n, steps = ds.outcomes.shape
    known = np.full(n, l0)
    p_correct = np.zeros((n, steps))
    p_known = np.zeros((n, steps))
    for k in range(steps):
        p_known[:, k] = known
        pc = known * (1 - s) + (1 - known) * g
        p_correct[:, k] = pc
        y = ds.outcomes[:, k] == 1
        post = np.where(
            y, known * (1 - s) / np.maximum(pc, EPS), known * s / np.maximum(1 - pc, EPS)
        )
        nxt = post + (1 - post) * t
        known = np.where(ds.mask[:, k], nxt, known)
    return p_correct, p_known


def nll(params: np.ndarray, ds: Dataset) -> float:
    pc, _ = forward(params, ds)
    y = ds.outcomes == 1
    ll = np.where(y, np.log(np.clip(pc, EPS, 1)), np.log(np.clip(1 - pc, EPS, 1)))
    return float(-(ll * ds.mask).sum() / ds.mask.sum())


def scalar_agreement(params: np.ndarray, ds: Dataset, learners: int = 25) -> float:
    """Max |vectorised - runtime scalar| P(known) over a sample (must be ~0)."""
    p = BKTParameters.from_mapping(dict(zip(NAMES, map(float, params), strict=True)))
    _, vec = forward(params, ds)
    worst = 0.0
    for i in range(min(learners, ds.outcomes.shape[0])):
        known = p.initial_knowledge
        for k in range(int(ds.mask[i].sum())):
            worst = max(worst, abs(known - vec[i, k]))
            known = transition(observe(known, bool(ds.outcomes[i, k]), p), p)
    return worst


# --- fitting ------------------------------------------------------------------------------------------


def fit(ds: Dataset) -> np.ndarray:
    """Coarse grid, then coordinate-wise golden-section refinement (deterministic)."""
    grids = [np.linspace(*BOUNDS[n], num) for n, num in zip(NAMES, (7, 7, 5, 5), strict=True)]
    best, best_loss = None, np.inf
    for l0 in grids[0]:
        for t in grids[1]:
            for g in grids[2]:
                for s in grids[3]:
                    cand = np.array([l0, t, g, s])
                    loss = nll(cand, ds)
                    if loss < best_loss:
                        best, best_loss = cand, loss
    params = best.copy()
    phi = (np.sqrt(5) - 1) / 2
    for _ in range(6):
        for j, name in enumerate(NAMES):
            lo, hi = BOUNDS[name]
            width = (hi - lo) / 4
            a, b = max(lo, params[j] - width), min(hi, params[j] + width)

            def f(x: float, j: int = j) -> float:
                trial = params.copy()
                trial[j] = x
                return nll(trial, ds)

            c, d = b - phi * (b - a), a + phi * (b - a)
            fc, fd = f(c), f(d)
            for _ in range(30):
                if fc < fd:
                    b, d, fd = d, c, fc
                    c = b - phi * (b - a)
                    fc = f(c)
                else:
                    a, c, fc = c, d, fd
                    d = a + phi * (b - a)
                    fd = f(d)
            x = (a + b) / 2
            if f(x) <= nll(params, ds):
                params[j] = x
    return params


# --- held-out metrics ---------------------------------------------------------------------------------


def auc(p: np.ndarray, y: np.ndarray) -> float | None:
    pos, neg = y.sum(), (~y).sum()
    if pos == 0 or neg == 0:
        return None
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty(len(p))
    sorted_p = p[order]
    i = 0
    while i < len(p):
        j = i
        while j < len(p) and sorted_p[j] == sorted_p[i]:
            j += 1
        ranks[order[i:j]] = (i + j + 1) / 2
        i = j
    return float((ranks[y].sum() - pos * (pos + 1) / 2) / (pos * neg))


def scores(pc: np.ndarray, ds: Dataset, p_known: np.ndarray | None = None) -> dict:
    m = ds.mask
    p, y = pc[m], ds.outcomes[m] == 1
    bins = []
    for b in range(10):
        lo, hi = b / 10, (b + 1) / 10
        sel = (p >= lo) & ((p < hi) | (b == 9))
        if sel.sum():
            bins.append(
                {
                    "bin": f"{lo:.1f}-{hi:.1f}",
                    "n": int(sel.sum()),
                    "mean_predicted": round(float(p[sel].mean()), 4),
                    "observed": round(float(y[sel].mean()), 4),
                }
            )
    ece = sum(b["n"] * abs(b["mean_predicted"] - b["observed"]) for b in bins) / max(1, len(p))
    out = {
        "events": int(m.sum()),
        "log_loss": round(
            float(
                -np.mean(np.where(y, np.log(np.clip(p, EPS, 1)), np.log(np.clip(1 - p, EPS, 1))))
            ),
            5,
        ),
        "brier": round(float(np.mean((p - y) ** 2)), 5),
        "expected_calibration_error": round(ece, 5),
        "accuracy_at_0_5": round(float(np.mean((p >= 0.5) == y)), 4),
        "auc": None if (a := auc(p, y)) is None else round(a, 4),
        "calibration_bins": bins,
    }
    if p_known is not None:
        truth = ds.known_before[m] == 1
        est = p_known[m] >= MASTERY
        out["false_mastery_rate"] = round(float((est & ~truth).sum() / max(1, est.sum())), 4)
        out["missed_mastery_rate"] = round(float((~est & truth).sum() / max(1, truth.sum())), 4)
        out["mastery_declared_share"] = round(float(est.mean()), 4)
    return out


def baselines(train: Dataset, test: Dataset, fitted: np.ndarray, truth: np.ndarray | None) -> dict:
    base_rate = train.outcomes[train.mask].mean()
    out = {"global_mean (non-adaptive)": scores(np.full(test.outcomes.shape, base_rate), test)}
    # Learner running proportion correct with a Beta prior centred on the training mean.
    a, b = 2 * base_rate, 2 * (1 - base_rate)
    seen = np.cumsum(test.mask, axis=1) - test.mask
    right = np.cumsum(test.outcomes * test.mask, axis=1) - test.outcomes * test.mask
    out["learner_running_mean (non-adaptive)"] = scores((right + a) / (seen + a + b), test)
    for name, params in (
        ("provisional_runtime_v1", PROVISIONAL),
        ("bkt_fitted", fitted),
        *((("bkt_oracle_true_parameters", truth),) if truth is not None else ()),
    ):
        pc, pk = forward(params, test)
        out[name] = scores(pc, test, pk)
    return out


def bootstrap(ds: Dataset, reps: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    n = ds.outcomes.shape[0]
    fits = []
    for _ in range(reps):
        idx = rng.integers(0, n, n)
        sub = Dataset(ds.kc, ds.outcomes[idx], ds.known_before[idx], ds.mask[idx], [], ds.meta)
        fits.append(fit(sub))
    arr = np.array(fits)
    return {
        name: [
            round(float(np.percentile(arr[:, j], 2.5)), 4),
            round(float(np.percentile(arr[:, j], 97.5)), 4),
        ]
        for j, name in enumerate(NAMES)
    } | {
        "corr_p_l0_p_t": round(float(np.corrcoef(arr[:, 0], arr[:, 1])[0, 1]), 3),
        "corr_p_g_p_s": round(float(np.corrcoef(arr[:, 2], arr[:, 3])[0, 1]), 3),
        "corr_p_l0_p_g": round(float(np.corrcoef(arr[:, 0], arr[:, 2])[0, 1]), 3),
        "reps": reps,
    }


def truth_vec(kc: KcTruth) -> np.ndarray:
    return np.array([kc.p_l0, kc.p_t, kc.p_g, kc.p_s])


def rounded(v: np.ndarray) -> dict:
    return {n: round(float(x), 4) for n, x in zip(NAMES, v, strict=True)}


# --- experiments ----------------------------------------------------------------------------------------


def recovery(learners: int, length: int, seeds: int, reps: int) -> dict:
    """E1: each KC type, several independent calibration seeds, a disjoint held-out set."""
    out = {}
    for k, kc in enumerate(KC_TYPES):
        fits, held = [], None
        for s in range(seeds):
            train = generate(kc, learners, length, CAL_SEED + 100 * k + s)
            fits.append(fit(train))
            if s == 0:
                test = generate(kc, learners, length, TEST_SEED + 100 * k)
                held = baselines(train, test, fits[0], truth_vec(kc))
                agreement = scalar_agreement(fits[0], test)
                boot = bootstrap(train, reps, 7 + k)
        arr = np.array(fits)
        out[kc.name] = {
            "truth": rounded(truth_vec(kc)),
            "fitted_seed0": rounded(arr[0]),
            "mean_abs_error_over_seeds": rounded(np.abs(arr - truth_vec(kc)).mean(axis=0)),
            "sd_over_seeds": rounded(arr.std(axis=0)),
            "bootstrap_95ci_seed0": boot,
            "truth_inside_bootstrap_ci": {
                n: bool(boot[n][0] <= truth_vec(kc)[j] <= boot[n][1]) for j, n in enumerate(NAMES)
            },
            "held_out": held,
            "vectorised_vs_runtime_max_abs_diff": float(agreement),
        }
    return out


def size_curve(learner_grid: list[int], length_grid: list[int], seeds: int) -> list[dict]:
    """E2: recovery error against learner count and sequence length (typical KC)."""
    kc = KC_TYPES[0]
    rows = []
    for n in learner_grid:
        for steps in length_grid:
            errs = np.array(
                [
                    np.abs(fit(generate(kc, n, steps, CAL_SEED + 7000 + s)) - truth_vec(kc))
                    for s in range(seeds)
                ]
            )
            rows.append(
                {
                    "learners": n,
                    "length": steps,
                    "events": n * steps,
                    "mean_abs_error": rounded(errs.mean(axis=0)),
                    "max_param_mean_abs_error": round(float(errs.mean(axis=0).max()), 4),
                }
            )
    return rows


def sparse(learners: int, length: int) -> dict:
    """E3: variable-length and truncated histories (typical KC)."""
    kc = KC_TYPES[0]
    out = {}
    for name, kwargs in (
        ("complete", {}),
        ("variable_2_to_L", {"min_length": 2}),
        ("variable_and_30pct_truncated", {"min_length": 2, "truncate_prob": 0.3}),
    ):
        train = generate(kc, learners, length, CAL_SEED + 9000, **kwargs)
        test = generate(kc, learners, length, TEST_SEED + 9000, **kwargs)
        fitted = fit(train)
        pc, pk = forward(fitted, test)
        out[name] = {
            "events": train.events,
            "fitted": rounded(fitted),
            "abs_error": rounded(np.abs(fitted - truth_vec(kc))),
            "held_out": {k: v for k, v in scores(pc, test, pk).items() if k != "calibration_bins"},
        }
    return out


MISMATCHES = {
    "forgetting_0.05": ("homogeneous", Mismatch(forget=0.05)),
    "learner_heterogeneity": ("mixed", Mismatch(learner_sd=0.8)),
    "item_difficulty_variation": ("homogeneous", Mismatch(item_sd=0.8)),
    "irregular_practice": ("homogeneous", Mismatch(forget=0.02, burst_gap=0.1)),
    "all_combined": ("mixed", Mismatch(forget=0.05, learner_sd=0.8, item_sd=0.8, burst_gap=0.1)),
}


def mismatch(learners: int, length: int) -> dict:
    """E4: data that does NOT follow BKT; compare fitted BKT with baselines on held-out data."""
    kc = KC_TYPES[0]
    out = {}
    for name, (population, mm) in MISMATCHES.items():
        train = generate(kc, learners, length, CAL_SEED + 8000, population, mm)
        test = generate(kc, learners, length, TEST_SEED + 8000, population, mm)
        fitted = fit(train)
        held = baselines(train, test, fitted, None)
        out[name] = {
            "population": population,
            "mismatch": asdict(mm),
            "fitted": rounded(fitted),
            "base_kc_parameters": rounded(truth_vec(kc)),
            "held_out": {
                k: {m: v[m] for m in v if m != "calibration_bins"} for k, v in held.items()
            },
        }
    return out


def shift(learners: int, length: int) -> dict:
    """E5: calibrate on one population, evaluate on another (distribution shift)."""
    kc = KC_TYPES[0]
    train = generate(kc, learners, length, CAL_SEED + 6000, "homogeneous")
    test = generate(kc, learners, length, TEST_SEED + 6000, "mixed", Mismatch(learner_sd=0.8))
    fitted = fit(train)
    refit = fit(generate(kc, learners, length, CAL_SEED + 6001, "mixed", Mismatch(learner_sd=0.8)))
    a, b = forward(fitted, test), forward(refit, test)
    return {
        "calibrated_on": "homogeneous",
        "evaluated_on": "mixed+heterogeneous",
        "fitted_on_wrong_population": {
            k: v for k, v in scores(a[0], test, a[1]).items() if k != "calibration_bins"
        },
        "fitted_on_matching_population": {
            k: v for k, v in scores(b[0], test, b[1]).items() if k != "calibration_bins"
        },
    }


def run(quick: bool) -> dict:
    learners, length = (200, 12) if quick else (400, 15)
    seeds, reps = (2, 5) if quick else (5, 30)
    started = datetime.now(UTC)
    report = {
        "kind": "SYNTHETIC calibration study (not real learners; not evidence for production parameters)",
        "label": "synthetic_calibration",
        "design": {
            "reference_size": {
                "learners_per_kc": learners,
                "opportunities_per_learner": length,
                "why": "chosen from the size curve (E2): the smallest grid point where "
                "every parameter's mean error is near its plateau; see size_curve",
            },
            "calibration_seed_base": CAL_SEED,
            "held_out_seed_base": TEST_SEED,
            "seeds_per_kc_type": seeds,
            "bootstrap_reps": reps,
            "constraints": "guess < 0.5, slip < 0.5 (identifiability)",
            "mastery_threshold": MASTERY,
        },
        "recovery": recovery(learners, length, seeds, reps),
        "size_curve": size_curve(
            [50, 100, 200, 400] if quick else [50, 100, 200, 400, 800],
            [5, 15] if quick else [5, 10, 15, 25],
            2 if quick else 4,
        ),
        "sparse": sparse(learners, length),
        "mismatch": mismatch(learners, length),
        "distribution_shift": shift(learners, length),
    }
    report["runtime_seconds"] = round((datetime.now(UTC) - started).total_seconds(), 1)
    deterministic = {k: v for k, v in report.items() if k != "runtime_seconds"}
    report["metrics_sha256"] = hashlib.sha256(
        json.dumps(deterministic, sort_keys=True).encode()
    ).hexdigest()
    return report


def experimental_config(report: dict) -> dict:
    return {
        "config_id": "bkt-synthetic-calibration-v1",
        "status": "EXPERIMENTAL - synthetic only, never for runtime use",
        "label": "synthetic_calibration",
        "note": "Parameters fitted on SYNTHETIC learners generated from made-up KC types. They show "
        "the calibration pipeline recovers known values; they say nothing about real CBSE "
        "skills. The runtime configuration remains bkt-provisional-v1 (provisional, "
        "uncalibrated) until real, consented learner data is evaluated.",
        "generator": "evaluation.synthetic_learners (homogeneous population)",
        "data": report["design"],
        "parameters_by_synthetic_kc_type": {
            name: {
                "fitted": r["fitted_seed0"],
                "bootstrap_95ci": {n: r["bootstrap_95ci_seed0"][n] for n in NAMES},
                "generating_truth": r["truth"],
            }
            for name, r in report["recovery"].items()
        },
        "source_report_sha256": report["metrics_sha256"],
    }


def markdown(report: dict) -> str:
    lines = [
        "# Synthetic BKT calibration study",
        "",
        f"**{report['kind']}.** Label `{report['label']}`. Fingerprint `{report['metrics_sha256'][:16]}`.",
        "",
        f"Reference data per KC type: {report['design']['reference_size']['learners_per_kc']} learners x "
        f"{report['design']['reference_size']['opportunities_per_learner']} opportunities; "
        f"{report['design']['seeds_per_kc_type']} calibration seeds; held-out learners from separate seeds; "
        f"{report['design']['bootstrap_reps']} bootstrap refits. Constraint: {report['design']['constraints']}.",
        "",
        "## Parameter recovery (E1)",
        "",
        "| KC type | truth (l0, t, g, s) | fitted seed 0 | mean abs error over seeds | truth inside bootstrap 95% CI |",
        "|---|---|---|---|---|",
    ]
    for name, r in report["recovery"].items():
        t = r["truth"]
        f = r["fitted_seed0"]
        e = r["mean_abs_error_over_seeds"]
        inside = sum(r["truth_inside_bootstrap_ci"].values())
        lines.append(
            f"| {name} | {t['p_l0']}, {t['p_t']}, {t['p_g']}, {t['p_s']} | {f['p_l0']}, {f['p_t']}, {f['p_g']}, {f['p_s']} | "
            f"{e['p_l0']}, {e['p_t']}, {e['p_g']}, {e['p_s']} | {inside}/4 |"
        )
    lines += [
        "",
        "## Held-out prediction (E1, seed 0)",
        "",
        "| KC type | model | log loss | Brier | ECE | AUC | false mastery | missed mastery |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, r in report["recovery"].items():
        for model, s in r["held_out"].items():
            lines.append(
                f"| {name} | {model} | {s['log_loss']} | {s['brier']} | {s['expected_calibration_error']} | {s['auc']} | "
                f"{s.get('false_mastery_rate', 'n/a')} | {s.get('missed_mastery_rate', 'n/a')} |"
            )
    lines += [
        "",
        "## Sample size (E2, typical KC)",
        "",
        "| learners | length | events | max mean abs error | per parameter |",
        "|---|---|---|---|---|",
    ]
    for row in report["size_curve"]:
        lines.append(
            f"| {row['learners']} | {row['length']} | {row['events']} | {row['max_param_mean_abs_error']} | {row['mean_abs_error']} |"
        )
    lines += ["", "## Sparse and incomplete histories (E3)", ""]
    for name, r in report["sparse"].items():
        lines.append(
            f"- {name}: events {r['events']}, abs error {r['abs_error']}, held-out log loss {r['held_out']['log_loss']}, false mastery {r['held_out']['false_mastery_rate']}"
        )
    lines += [
        "",
        "## Model mismatch (E4): data that does not follow BKT",
        "",
        "| scenario | model | log loss | Brier | ECE |",
        "|---|---|---|---|---|",
    ]
    for name, r in report["mismatch"].items():
        for model, s in r["held_out"].items():
            lines.append(
                f"| {name} | {model} | {s['log_loss']} | {s['brier']} | {s['expected_calibration_error']} |"
            )
    d = report["distribution_shift"]
    lines += [
        "",
        "## Distribution shift (E5)",
        "",
        f"- calibrated on homogeneous, evaluated on heterogeneous: log loss {d['fitted_on_wrong_population']['log_loss']}, "
        f"false mastery {d['fitted_on_wrong_population']['false_mastery_rate']}",
        f"- calibrated on matching population: log loss {d['fitted_on_matching_population']['log_loss']}, "
        f"false mastery {d['fitted_on_matching_population']['false_mastery_rate']}",
        "",
        "## Limitations",
        "",
        "- Synthetic learners follow the generator's assumptions; recovery here does not show BKT fits real CBSE learners.",
        "- One skill per sequence; no multi-skill items, no hint effects, no time effects beyond the mismatch scenarios.",
        "- The runtime configuration is unchanged and remains provisional until real, consented data is evaluated.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.bkt_synthetic")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--write-config", action="store_true", help="write the experimental config")
    parser.add_argument(
        "--dump-data", action="store_true", help="write synthetic sequences (JSONL)"
    )
    args = parser.parse_args(argv)
    report = run(args.quick)
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (OUT / f"bkt_synthetic_{stamp}.json").write_text(json.dumps(report, indent=2) + "\n")
    (OUT / f"bkt_synthetic_{stamp}.md").write_text(markdown(report))
    if args.write_config:
        CONFIG_OUT.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_OUT.write_text(json.dumps(experimental_config(report), indent=2) + "\n")
    if args.dump_data:
        DATA_OUT.mkdir(parents=True, exist_ok=True)
        for k, kc in enumerate(KC_TYPES):
            ds = generate(kc, 400, 15, CAL_SEED + 100 * k)
            with (DATA_OUT / f"bkt_calibration_{kc.name}_seed{CAL_SEED + 100 * k}.jsonl").open(
                "w"
            ) as fh:
                fh.writelines(json.dumps(r) + "\n" for r in ds.records())
    print(markdown(report))
    print(f"report: {(OUT / f'bkt_synthetic_{stamp}.md').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
