# ruff: noqa: E501  (report tables are prose; long lines are intentional)
"""Synthetic learning-outcome simulation of the adaptive policy against baselines.

    python -m evaluation.policy_simulation            # full study
    python -m evaluation.policy_simulation --quick    # small smoke run

SYNTHETIC ONLY. Simulated learners on a simulated prerequisite graph answer simulated questions;
the study checks that the recommender (`app.services.adaptive.recommend`, unchanged) behaves
coherently, and where it does worse than simple baselines. It is not evidence that real students
learn more with ConceptTrail.

World. 12 KCs: 4 class-6 foundations, 8 class-7 targets, a layered prerequisite DAG. A learner's
chance to learn a KC is cut to 15% of normal while any TRUE prerequisite is unknown, so ignoring
prerequisites is costly. Learners differ in ability (initial knowledge and learning rate), guessing,
carelessness and (in some conditions) forgetting. Five questions per KC with difficulty 1-5 shift
guess and slip. Every policy sees the same simulated learners and response noise (common random
numbers), and only what a real system would see: answers, the policy's own graph and labels.

Policies. random (any KC, any question); fixed_difficulty (any KC, always difficulty-3 items);
non_adaptive_sequence (curriculum order, equal practice per KC); prerequisite_first (topological
order, move on after 3 correct in a row); conceptrail (the runtime recommender with BKT estimates
from the runtime update equations and the provisional runtime parameters).

Conditions include ones designed to hurt an adaptive policy: noisy answers, a wrong prerequisite
graph given to the policy, miscalibrated BKT, wrong difficulty labels, a small practice budget,
forgetting, and a slower held-out population than the development one.

Seeds. Development seeds (0-4) were used while building the simulator; reported numbers use the
held-out seeds (100+). Intervals are 95% normal intervals over simulated learners.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.services import adaptive, graph_runtime
from app.services.bkt_service import BKTParameters, observe, transition
from app.services.prerequisite_graph import EdgeRecord, KcRecord, PrerequisiteGraph, validate_graph

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".local/evaluation/reports"
RUNTIME = BKTParameters(0.2, 0.1, 0.2, 0.1)
FOUNDATIONS = [f"K{i}" for i in range(4)]
TARGETS = [f"K{i}" for i in range(4, 12)]
KCS = FOUNDATIONS + TARGETS
SCOPE = adaptive.LearnerScope(class_level=7)
GATE = 0.15
POLICIES = (
    "random",
    "fixed_difficulty",
    "non_adaptive_sequence",
    "prerequisite_first",
    "conceptrail",
)


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def logit(p: float) -> float:
    return math.log(p / (1 - p))


@dataclass(frozen=True)
class Condition:
    name: str
    budget: int = 80
    guess: float = 0.2
    slip: float = 0.08
    forget: float = 0.0
    ability_mean: float = 0.0
    learn_scale: float = 1.0
    wrong_graph: bool = False
    wrong_labels: bool = False
    policy_bkt: BKTParameters = RUNTIME
    description: str = ""


CONDITIONS = (
    Condition(
        "base", description="BKT-like learners, correct graph and labels, provisional runtime BKT"
    ),
    Condition(
        "noisy_answers", guess=0.33, slip=0.2, description="frequent guessing and careless slips"
    ),
    Condition(
        "wrong_graph",
        wrong_graph=True,
        description="policy graph: 40% of true edges dropped, spurious edges added",
    ),
    Condition(
        "miscalibrated_bkt",
        policy_bkt=BKTParameters(0.5, 0.35, 0.05, 0.02),
        description="policy BKT believes learners start high, learn fast, rarely guess",
    ),
    Condition(
        "wrong_difficulty_labels", wrong_labels=True, description="difficulty labels shuffled"
    ),
    Condition("sparse_budget", budget=25, description="only 25 practice opportunities"),
    Condition("forgetting", forget=0.04, description="known skills are lost at 4% per opportunity"),
    Condition(
        "heldout_slower_population",
        ability_mean=-0.7,
        learn_scale=0.6,
        description="lower ability, slower learners than the development population",
    ),
)


# --- world -------------------------------------------------------------------------------------------


def true_edges(seed: int) -> list[tuple[str, str]]:
    """Layered DAG: foundations -> layer 1 targets -> layer 2 targets."""
    rng = random.Random(seed)
    layer1, layer2 = TARGETS[:4], TARGETS[4:]
    edges = set()
    for k in layer1:
        for p in rng.sample(FOUNDATIONS, 1 + (rng.random() < 0.5)):
            edges.add((p, k))
    for k in layer2:
        for p in rng.sample(layer1, 1 + (rng.random() < 0.5)):
            edges.add((p, k))
    return sorted(edges)


def corrupt(edges: list[tuple[str, str]], seed: int) -> list[tuple[str, str]]:
    rng = random.Random(seed + 999)
    kept = [e for e in edges if rng.random() > 0.4]
    order = {k: i for i, k in enumerate(KCS)}
    candidates = [(a, b) for a in KCS for b in KCS if order[a] < order[b] and (a, b) not in edges]
    return sorted(set(kept) | set(rng.sample(candidates, 4)))


def released(edges: list[tuple[str, str]]) -> graph_runtime.ReleasedGraph:
    kcs = [
        KcRecord(
            kc_id=k,
            stable_key=f"sim.{k.lower()}",
            subject_id="mathematics",
            name=k,
            review_status="approved",
            class_levels=(6,) if k in FOUNDATIONS else (7,),
            scope="foundation" if k in FOUNDATIONS else "target",
        )
        for k in KCS
    ]
    recs = [
        EdgeRecord(
            prerequisite_kc_id=a,
            dependent_kc_id=b,
            reason="simulated",
            evidence_refs=("sim",),
            review_status="approved",
        )
        for a, b in edges
    ]
    report = validate_graph(kcs, recs)
    assert report.ok, report.codes("error")
    return graph_runtime.ReleasedGraph(
        PrerequisiteGraph(kcs, report), 1, "0" * 64, {k.kc_id: k.model_dump() for k in kcs}
    )


@dataclass
class Learner:
    known: dict[str, bool]
    p_t: dict[str, float]
    guess: float
    slip: float


def make_learner(cond: Condition, seed: int, idx: int, prereqs: dict[str, list[str]]) -> Learner:
    rng = random.Random(f"learner|{seed}|{idx}|{cond.ability_mean}|{cond.learn_scale}")
    ability = rng.gauss(cond.ability_mean, 1.0)
    depth = {k: 0 if k in FOUNDATIONS else (1 if k in TARGETS[:4] else 2) for k in KCS}
    known, p_t = {}, {}
    for k in KCS:
        known[k] = rng.random() < sigmoid(logit(0.45) + ability - 1.0 * depth[k])
        p_t[k] = min(0.9, cond.learn_scale * sigmoid(logit(0.18) + 0.5 * ability))
    for k in KCS:  # cannot start knowing a skill whose prerequisites are unknown
        known[k] = known[k] and all(known[p] for p in prereqs[k])
    g = sigmoid(logit(cond.guess) + rng.gauss(0, 0.3))
    s = sigmoid(logit(cond.slip) + rng.gauss(0, 0.3))
    return Learner(known, p_t, g, s)


def respond(lr: Learner, kc: str, difficulty: int, rng: random.Random) -> bool:
    g = sigmoid(logit(lr.guess) - 0.3 * (difficulty - 3))
    s = sigmoid(logit(lr.slip) + 0.3 * (difficulty - 3))
    return rng.random() < ((1 - s) if lr.known[kc] else g)


def learn(
    lr: Learner, kc: str, prereqs: dict[str, list[str]], cond: Condition, rng: random.Random
) -> None:
    if not lr.known[kc]:
        rate = lr.p_t[kc] * (1.0 if all(lr.known[p] for p in prereqs[kc]) else GATE)
        lr.known[kc] = rng.random() < rate
    for other in KCS:
        if lr.known[other] and rng.random() < cond.forget:
            lr.known[other] = False


# --- policies ----------------------------------------------------------------------------------------


class Policy:
    def __init__(
        self,
        name: str,
        graph,
        labels: dict[str, list[int]],
        cond: Condition,
        rng: random.Random,
        thresholds: adaptive.Thresholds = adaptive.DEFAULT_THRESHOLDS,
    ):
        self.name, self.graph, self.labels, self.cond, self.rng = name, graph, labels, cond, rng
        self.thresholds = thresholds
        self.estimate: dict[str, adaptive.MasteryView] = {}
        self.attempted: set[str] = set()
        self.order = [k for layer in graph.graph.layers() for k in sorted(layer)]
        self.streak: dict[str, int] = {}
        self.declared: set[str] = set()
        self.cursor = 0

    def question(self, kc: str, target: float) -> tuple[str, int]:
        """(question_id, TRUE difficulty) choosing by the policy's (possibly wrong) labels."""
        items = list(range(5))
        if self.name == "fixed_difficulty":
            choice = min(items, key=lambda i: abs(self.labels[kc][i] - 3))
        elif self.name in ("random",):
            choice = self.rng.choice(items)
        else:
            fresh = [i for i in items if f"{kc}-{i}" not in self.attempted] or items
            choice = min(fresh, key=lambda i: (abs(self.labels[kc][i] - target), i))
        return f"{kc}-{choice}", choice + 1  # true difficulty is index + 1

    def next(self) -> tuple[str, str, int] | None:
        if self.name in ("random", "fixed_difficulty"):
            kc = self.rng.choice(KCS)
            return (kc, *self.question(kc, 3))
        if self.name == "non_adaptive_sequence":
            per = max(1, self.cond.budget // len(KCS))
            kc = self.order[min(len(self.order) - 1, self.cursor // per)]
            self.cursor += 1
            return (kc, *self.question(kc, 3))
        if self.name == "prerequisite_first":
            remaining = [k for k in self.order if k not in self.declared]
            if not remaining:
                return None
            kc = remaining[0]
            return (kc, *self.question(kc, 1 + min(4, self.streak.get(kc, 0))))
        questions = {
            k: [adaptive.QuestionView(f"{k}-{i}", self.labels[k][i]) for i in range(5)] for k in KCS
        }
        rec = adaptive.recommend(
            self.graph, SCOPE, self.estimate, questions, self.attempted, self.thresholds
        )
        if isinstance(rec, adaptive.InsufficientData):
            return None
        index = int(rec.question_id.rsplit("-", 1)[1])
        return rec.kc_id, rec.question_id, index + 1

    def update(self, kc: str, qid: str, correct: bool) -> None:
        self.attempted.add(qid)
        p = self.cond.policy_bkt
        prior = self.estimate[kc].probability if kc in self.estimate else p.initial_knowledge
        count = self.estimate[kc].evidence_count if kc in self.estimate else 0
        self.estimate[kc] = adaptive.MasteryView(
            transition(observe(prior, correct, p), p), count + 1
        )
        self.streak[kc] = self.streak.get(kc, 0) + 1 if correct else 0
        if self.name == "prerequisite_first" and self.streak[kc] >= 3:
            self.declared.add(kc)
        if (
            self.name == "conceptrail"
            and self.estimate[kc].probability >= self.thresholds.mastery_target
        ):
            self.declared.add(kc)


def simulate(cond: Condition, policy_name: str, seed: int, idx: int, thresholds=None) -> dict:
    truth = true_edges(seed)
    prereqs = {k: [a for a, b in truth if b == k] for k in KCS}
    graph = released(corrupt(truth, seed) if cond.wrong_graph else truth)
    label_rng = random.Random(f"labels|{seed}")
    labels = {
        k: (label_rng.sample([1, 2, 3, 4, 5], 5) if cond.wrong_labels else [1, 2, 3, 4, 5])
        for k in KCS
    }
    lr = make_learner(cond, seed, idx, prereqs)
    start_known = sum(lr.known[k] for k in TARGETS)
    response_rng = random.Random(f"responses|{seed}|{idx}")  # same noise stream for every policy
    policy = Policy(
        policy_name,
        graph,
        labels,
        cond,
        random.Random(f"policy|{seed}|{idx}"),
        thresholds or adaptive.DEFAULT_THRESHOLDS,
    )
    on_known = neglect = steps = 0
    reached = None
    practised = set()
    for step in range(1, cond.budget + 1):
        move = policy.next()
        if move is None:
            break
        kc, qid, difficulty = move
        steps = step
        practised.add(kc)
        on_known += lr.known[kc]
        neglect += any(not lr.known[p] for p in prereqs[kc])
        correct = respond(lr, kc, difficulty, response_rng)
        policy.update(kc, qid, correct)
        learn(lr, kc, prereqs, cond, response_rng)
        if reached is None and all(lr.known[k] for k in TARGETS):
            reached = step
    end_known = sum(lr.known[k] for k in TARGETS)
    false_mastery = sum(1 for k in policy.declared if not lr.known[k])
    return {
        "gain": (end_known - start_known) / len(TARGETS),
        "final_mastery": end_known / len(TARGETS),
        "reached_all": reached is not None,
        "steps_to_all": reached if reached is not None else cond.budget + 1,
        "practice_on_known": on_known / max(1, steps),
        "prerequisite_neglect": neglect / max(1, steps),
        "coverage": len(practised & set(TARGETS)) / len(TARGETS),
        "false_mastery": false_mastery,
        "declared": len(policy.declared),
        "stopped_early": steps < cond.budget,
    }


def summary(values: list[float]) -> dict:
    n = len(values)
    mean = sum(values) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / max(1, n - 1))
    half = 1.96 * sd / math.sqrt(n)
    return {"mean": round(mean, 4), "ci95": [round(mean - half, 4), round(mean + half, 4)], "n": n}


METRICS = (
    "gain",
    "final_mastery",
    "reached_all",
    "steps_to_all",
    "practice_on_known",
    "prerequisite_neglect",
    "coverage",
    "false_mastery",
)


def evaluate(
    cond: Condition, policy: str, seeds: list[int], learners: int, thresholds=None
) -> dict:
    runs = [simulate(cond, policy, s, i, thresholds) for s in seeds for i in range(learners)]
    out = {m: summary([float(r[m]) for r in runs]) for m in METRICS}
    out["per_seed_final_mastery"] = [
        round(
            sum(r["final_mastery"] for r in runs[j * learners : (j + 1) * learners]) / learners, 4
        )
        for j in range(len(seeds))
    ]
    return out


def run(quick: bool) -> dict:
    seeds = [100, 101] if quick else [100, 101, 102, 103, 104]
    learners = 20 if quick else 60
    conditions = CONDITIONS[:3] if quick else CONDITIONS
    started = datetime.now(UTC)
    results = {
        c.name: {
            "description": c.description,
            "budget": c.budget,
            "policies": {p: evaluate(c, p, seeds, learners) for p in POLICIES},
        }
        for c in conditions
    }
    base = CONDITIONS[0]
    sensitivity = {
        f"target_{t.mastery_target}_ready_{t.prerequisite_ready}": evaluate(
            base, "conceptrail", seeds[:2], learners, t
        )
        for t in (
            adaptive.Thresholds(0.85, 0.7),
            adaptive.Thresholds(0.95, 0.6),
            adaptive.Thresholds(0.95, 0.8),
            adaptive.Thresholds(0.98, 0.7),
        )
    }
    findings = []
    for name, r in results.items():
        ct = r["policies"]["conceptrail"]["final_mastery"]["mean"]
        best_name, best = max(
            ((p, v["final_mastery"]["mean"]) for p, v in r["policies"].items()), key=lambda x: x[1]
        )
        if best_name != "conceptrail" and best - ct > 0.02:
            findings.append(
                f"{name}: {best_name} reaches higher final mastery ({best:.3f}) than conceptrail ({ct:.3f})"
            )
    report = {
        "kind": "SYNTHETIC policy simulation (not evidence about real learners)",
        "design": {
            "kcs": len(KCS),
            "targets": len(TARGETS),
            "prerequisite_gate": GATE,
            "heldout_seeds": seeds,
            "learners_per_seed": learners,
            "runtime_bkt": asdict(RUNTIME),
            "policies": list(POLICIES),
            "thresholds": asdict(adaptive.DEFAULT_THRESHOLDS),
        },
        "conditions": results,
        "threshold_sensitivity_base": sensitivity,
        "where_conceptrail_does_worse": findings,
    }
    report["metrics_sha256"] = hashlib.sha256(
        json.dumps(report, sort_keys=True).encode()
    ).hexdigest()
    report["runtime_seconds"] = round((datetime.now(UTC) - started).total_seconds(), 1)
    return report


def markdown(report: dict) -> str:
    d = report["design"]
    lines = [
        "# Synthetic adaptive-policy simulation",
        "",
        f"**{report['kind']}.** Fingerprint `{report['metrics_sha256'][:16]}`. {d['kcs']} KCs ({d['targets']} targets), "
        f"held-out seeds {d['heldout_seeds']} x {d['learners_per_seed']} learners per condition and policy; "
        f"policy BKT {d['runtime_bkt']}, thresholds {d['thresholds']}.",
        "",
    ]
    for name, r in report["conditions"].items():
        lines += [
            f"## {name} (budget {r['budget']}): {r['description']}",
            "",
            "| policy | final mastery | gain | reached all | steps to all | practice on known | prerequisite neglect | coverage | false mastery |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for p, v in r["policies"].items():

            def f(m: str, v: dict = v) -> str:
                return f"{v[m]['mean']} [{v[m]['ci95'][0]}, {v[m]['ci95'][1]}]"

            lines.append(
                f"| {p} | {f('final_mastery')} | {f('gain')} | {f('reached_all')} | {f('steps_to_all')} | "
                f"{f('practice_on_known')} | {f('prerequisite_neglect')} | {f('coverage')} | {f('false_mastery')} |"
            )
        lines.append("")
    lines += [
        "## Threshold sensitivity (base condition, conceptrail)",
        "",
        "| thresholds | final mastery | false mastery | practice on known |",
        "|---|---|---|---|",
    ]
    for k, v in report["threshold_sensitivity_base"].items():
        lines.append(
            f"| {k} | {v['final_mastery']['mean']} | {v['false_mastery']['mean']} | {v['practice_on_known']['mean']} |"
        )
    lines += ["", "## Where ConceptTrail does worse than a baseline", ""]
    lines += [f"- {x}" for x in report["where_conceptrail_does_worse"]] or [
        "- none beyond 0.02 final mastery"
    ]
    lines += [
        "",
        "## Limitations",
        "",
        "- Simulated learners follow the simulator's rules (prerequisite gating, BKT-like answers); real learners do not.",
        "- Final mastery is the simulator's hidden state, not a test score; no real learning gain is claimed.",
        "- One subject, one class, 12 KCs; no time, motivation or hint effects.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.policy_simulation")
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args(argv)
    report = run(args.quick)
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (OUT / f"policy_simulation_{stamp}.json").write_text(json.dumps(report, indent=2) + "\n")
    (OUT / f"policy_simulation_{stamp}.md").write_text(markdown(report))
    print(markdown(report))
    print(f"report: {(OUT / f'policy_simulation_{stamp}.md').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
