"""Adaptive-policy evaluation on SYNTHETIC learners (engineering evidence only).

    python -m evaluation.adaptive_policy_sim [--learners 200] [--seed 11]

Each simulated learner has a hidden true state per KC on a synthetic prerequisite graph; a KC can
only be learned once its prerequisites are truly known; answers follow the BKT generative model.
The runtime policy (`app.services.adaptive.recommend`) chooses each step from BKT estimates using
the provisional runtime parameters. For a grid of thresholds the report gives: steps until every
target KC is truly known (or the step budget), the share of recommendations on KCs the learner
already truly knows (over-practice), the share of remediation steps, how often a KC was declared
mastered while not truly known, and the outcome of the edge cases (empty history, no questions,
all mastered, no released graph). Results describe this simulator, not real classrooms; the
thresholds stay provisional until validated with real, consented learning data.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from app.services import adaptive, graph_runtime
from app.services.bkt_service import BKTParameters, observe, transition
from app.services.prerequisite_graph import EdgeRecord, KcRecord, PrerequisiteGraph, validate_graph

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".local/evaluation"
RUNTIME = BKTParameters(0.2, 0.1, 0.2, 0.1)  # provisional runtime configuration
TRUE = BKTParameters(0.15, 0.15, 0.2, 0.08)  # simulator ground truth (differs on purpose)
SCOPE = adaptive.LearnerScope(class_level=7)
# F -> A -> {B, C}; B -> D. F is a lower-class foundation, the rest are class 7 targets.
NODES = {
    "F": ((6,), "foundation"),
    "A": ((7,), "target"),
    "B": ((7,), "target"),
    "C": ((7,), "target"),
    "D": ((7,), "target"),
}
EDGES = [("F", "A"), ("A", "B"), ("A", "C"), ("B", "D")]


def graph() -> graph_runtime.ReleasedGraph:
    kcs = [
        KcRecord(
            kc_id=k,
            stable_key=f"sim.{k.lower()}",
            subject_id="mathematics",
            name=k,
            review_status="approved",
            class_levels=c,
            scope=s,
        )
        for k, (c, s) in NODES.items()
    ]
    edges = [
        EdgeRecord(
            prerequisite_kc_id=a,
            dependent_kc_id=b,
            reason="simulated",
            evidence_refs=("sim",),
            review_status="approved",
        )
        for a, b in EDGES
    ]
    report = validate_graph(kcs, edges)
    assert report.ok
    return graph_runtime.ReleasedGraph(
        PrerequisiteGraph(kcs, report), 1, "0" * 64, {k.kc_id: k.model_dump() for k in kcs}
    )


QUESTIONS = {k: [adaptive.QuestionView(f"Q-{k}-{d}", d) for d in (1, 2, 3, 4, 5)] for k in NODES}
PREREQS = {k: [a for a, b in EDGES if b == k] for k in NODES}
TARGETS = [k for k, (_, s) in NODES.items() if s == "target"]


def run_learner(rng: random.Random, thresholds: adaptive.Thresholds, budget: int) -> dict:
    g = graph()
    known = {k: rng.random() < TRUE.initial_knowledge for k in NODES}
    known = {k: v and all(known[p] for p in PREREQS[k]) for k, v in known.items()}
    estimate: dict[str, adaptive.MasteryView] = {}
    attempted: set[str] = set()
    steps = over = remediation = 0
    false_mastery = set()
    for steps in range(1, budget + 1):  # noqa: B007
        rec = adaptive.recommend(g, SCOPE, estimate, QUESTIONS, attempted, thresholds)
        if isinstance(rec, adaptive.InsufficientData):
            steps -= 1
            break
        kc = rec.kc_id
        over += known[kc]
        remediation += rec.category == "remediate_prerequisite"
        correct = rng.random() < ((1 - TRUE.slip) if known[kc] else TRUE.guess)
        prior = estimate[kc].probability if kc in estimate else RUNTIME.initial_knowledge
        count = estimate[kc].evidence_count if kc in estimate else 0
        estimate[kc] = adaptive.MasteryView(
            transition(observe(prior, correct, RUNTIME), RUNTIME), count + 1
        )
        attempted.add(rec.question_id)
        if not known[kc] and all(known[p] for p in PREREQS[kc]) and rng.random() < TRUE.learning:
            known[kc] = True
        if all(known[k] for k in TARGETS):
            break
    for k, view in estimate.items():
        if (
            view.probability is not None
            and view.probability >= thresholds.mastery_target
            and not known[k]
        ):
            false_mastery.add(k)
    return {
        "steps": steps,
        "all_known": all(known[k] for k in TARGETS),
        "over": over,
        "remediation": remediation,
        "false_mastery": len(false_mastery),
    }


def evaluate(thresholds: adaptive.Thresholds, learners: int, seed: int, budget: int = 120) -> dict:
    rng = random.Random(seed)
    runs = [run_learner(rng, thresholds, budget) for _ in range(learners)]
    total = sum(r["steps"] for r in runs) or 1
    done = [r["steps"] for r in runs if r["all_known"]]
    return {
        "thresholds": {
            "mastery_target": thresholds.mastery_target,
            "prerequisite_ready": thresholds.prerequisite_ready,
        },
        "learners": learners,
        "reached_all_targets": round(len(done) / learners, 3),
        "mean_steps_when_reached": round(sum(done) / len(done), 1) if done else None,
        "over_practice_share": round(sum(r["over"] for r in runs) / total, 3),
        "remediation_share": round(sum(r["remediation"] for r in runs) / total, 3),
        "false_mastery_per_learner": round(sum(r["false_mastery"] for r in runs) / learners, 3),
    }


def edge_cases() -> dict:
    g = graph()
    full = {k: adaptive.MasteryView(0.99, 10) for k in NODES}
    return {
        "empty_history": adaptive.explain_recommendation(
            adaptive.recommend(g, SCOPE, {}, QUESTIONS, set())
        ),
        "no_questions": adaptive.explain_recommendation(
            adaptive.recommend(g, SCOPE, {}, {}, set())
        ),
        "all_mastered": adaptive.explain_recommendation(
            adaptive.recommend(g, SCOPE, full, QUESTIONS, set())
        ),
        "no_released_graph": adaptive.explain_recommendation(
            adaptive.recommend(
                graph_runtime.GraphUnavailable("graph_not_released"), SCOPE, {}, QUESTIONS, set()
            )
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.adaptive_policy_sim")
    parser.add_argument("--learners", type=int, default=200)
    parser.add_argument("--seed", type=int, default=11)
    args = parser.parse_args(argv)
    grid = [adaptive.Thresholds(m, p) for m in (0.85, 0.90, 0.95) for p in (0.6, 0.7, 0.8)]
    result = {
        "kind": "SYNTHETIC policy simulation (not evidence about real learners)",
        "runtime_bkt": asdict(RUNTIME),
        "simulator_truth": asdict(TRUE),
        "seed": args.seed,
        "grid": [evaluate(t, args.learners, args.seed) for t in grid],
        "edge_cases": edge_cases(),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"adaptive_policy_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for row in result["grid"]:
        print(json.dumps(row))
    print(
        json.dumps(
            {
                k: (v["status"], v.get("reason") or v.get("category"), v.get("kc_id"))
                for k, v in result["edge_cases"].items()
            }
        )
    )
    print(f"report: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
