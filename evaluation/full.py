# ruff: noqa: E501  (report text is prose)
"""One command for the whole evaluation, with evidence kept in separate categories.

    python -m evaluation.full                 # full synthetic studies (several minutes)
    python -m evaluation.full --quick         # reduced synthetic grids
    python -m evaluation.full --with-llm      # + live explanation suite (local model; demo mode)

Runs, in order: the core report (`evaluation.run`), the synthetic BKT calibration study
(`evaluation.bkt_synthetic`), the synthetic policy simulation (`evaluation.policy_simulation`),
the synthetic retrieval regression (`evaluation.retrieval_regression`, needs the local embedder),
optionally the explanation suite, and summarises the AI content review
(`data_pipeline/content_review/patch_v1.json`). Writes `.local/evaluation/reports/full_<stamp>.{json,md}`.

Categories (never merged): A software correctness; B1 AI-assisted review; B2 synthetic results;
B3 human review; B4 real learner evidence; B5 blocked or insufficient evidence.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
import types
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".local/evaluation/reports"


def content_review_summary() -> dict:
    from data_pipeline.content_review.patch import PATCH

    patch = json.loads(PATCH.read_text(encoding="utf-8"))
    ops = collections.Counter(o["op"] for o in patch["operations"])
    verdicts = collections.Counter(v["verdict"] for v in patch["verdicts"].values())
    issues = collections.Counter(
        o["issue"]
        for o in patch["operations"]
        if o["op"] in ("update_question", "withdraw_question")
    )
    return {
        "reviewer": patch["reviewer"],
        "review_type": patch["review_type"],
        "questions_reviewed": len(patch["verdicts"]),
        "verdicts": dict(verdicts),
        "operations": dict(ops),
        "issues": dict(issues.most_common()),
        "escalations": len(patch["escalations"]),
        "patch_sha256": patch["sha256"],
        "applied_to_persistent_database": False,
        "statement": patch["statement"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.full")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--with-llm", action="store_true")
    args = parser.parse_args(argv)
    from evaluation import bkt_synthetic, policy_simulation, run

    started = datetime.now(UTC)
    core = run.build(
        types.SimpleNamespace(live_retrieval=True, explanation_outputs=None, review_packet=None)
    )
    bkt = bkt_synthetic.run(args.quick)
    policy = policy_simulation.run(args.quick)
    try:
        from sqlalchemy.orm import Session

        from app.db.session import create_db_engine
        from evaluation import retrieval_regression

        with Session(create_db_engine(read_only=True)) as session:
            retrieval = retrieval_regression.run(session)
    except Exception as exc:  # noqa: BLE001  (embedder unavailable is a reportable state)
        retrieval = {"status": "not_measured", "reason": type(exc).__name__}
    explanations = None
    if args.with_llm:
        from evaluation import explanation_suite

        explanations = {k: v for k, v in explanation_suite.run().items() if k != "records"}
    review = content_review_summary()
    m = core["metrics"]
    sw = m["software_correctness"]
    report = {
        "generated_at": started.isoformat(),
        "quick": args.quick,
        "A_software_correctness": {
            "scoring": {"passed": sw["scoring"]["passed"], "cases": sw["scoring"]["cases"]},
            "adaptive_policy": {
                k: sw["adaptive"]["adaptive.policy_conformance"][k] for k in ("passed", "cases")
            },
            "bkt_known_answers": {
                k: sw["bkt"]["bkt.known_answers"][k] for k in ("passed", "vectors")
            },
            "retrieval_scope_leakage": m["quality_measurements"]["retrieval"][
                "retrieval.filter_leakage"
            ],
            "index_integrity_chunks": m["quality_measurements"]["retrieval"][
                "retrieval.index_integrity"
            ]["chunks"],
            "tests": "run `python -m pytest` (see docs/COMPLETION_AUDIT.md for the last totals)",
        },
        "B1_ai_assisted_review": review,
        "B2_synthetic": {
            "bkt_calibration": {
                "label": bkt["label"],
                "fingerprint": bkt["metrics_sha256"],
                "recovery": {
                    k: {
                        "truth": v["truth"],
                        "fitted": v["fitted_seed0"],
                        "mean_abs_error": v["mean_abs_error_over_seeds"],
                    }
                    for k, v in bkt["recovery"].items()
                },
            },
            "policy_simulation": {
                "fingerprint": policy["metrics_sha256"],
                "where_conceptrail_does_worse": policy["where_conceptrail_does_worse"],
                "base_final_mastery": {
                    p: v["final_mastery"]
                    for p, v in policy["conditions"]["base"]["policies"].items()
                },
            },
            "retrieval_regression": {k: v for k, v in retrieval.items() if k != "probe_details"},
            "explanation_regression": explanations or {"status": "not_run", "how": "--with-llm"},
        },
        "B3_human_review": m["quality_measurements"]["human_review"],
        "B4_real_learner_evidence": sw["bkt"]["bkt.real_prediction"],
        "B5_blocked_or_insufficient": [
            mid
            for mid, meta in core["catalog"].items()
            if meta["automation"] in ("blocked", "human_required")
        ],
        "core_metrics_sha256": core["metrics_sha256"],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    (OUT / f"full_{stamp}.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n"
    )
    lines = [
        "# ConceptTrail full evaluation",
        "",
        f"Generated {report['generated_at']} (quick={args.quick}). Core fingerprint `{core['metrics_sha256'][:16]}`.",
        "",
        "## A. Software correctness (ground truth: written specifications)",
        "",
        f"- Scoring {report['A_software_correctness']['scoring']['passed']}/{report['A_software_correctness']['scoring']['cases']}; adaptive policy {report['A_software_correctness']['adaptive_policy']['passed']}/{report['A_software_correctness']['adaptive_policy']['cases']}; BKT known answers {report['A_software_correctness']['bkt_known_answers']['passed']}/{report['A_software_correctness']['bkt_known_answers']['vectors']}",
        f"- Retrieval scope leakage: {report['A_software_correctness']['retrieval_scope_leakage']}",
        "",
        "## B1. AI-assisted content review (an AI reviewing AI content; NOT human review)",
        "",
        f"- {review['questions_reviewed']} questions reviewed; verdicts {review['verdicts']}; operations {review['operations']}; escalated for humans: {review['escalations']}",
        f"- Applied to the persistent database: {review['applied_to_persistent_database']} (verified on a disposable restored copy)",
        "",
        "## B2. Synthetic results (evidence about code and simulators, not learners)",
        "",
    ]
    for k, v in report["B2_synthetic"]["bkt_calibration"]["recovery"].items():
        lines.append(
            f"- BKT {k}: truth {v['truth']} fitted {v['fitted']} mean abs error {v['mean_abs_error']}"
        )
    lines.append(
        f"- Policy simulation, base condition final mastery: { {p: v['mean'] for p, v in report['B2_synthetic']['policy_simulation']['base_final_mastery'].items()} }"
    )
    lines += [
        f"- Policy simulation, where ConceptTrail does worse: {x}"
        for x in report["B2_synthetic"]["policy_simulation"]["where_conceptrail_does_worse"]
    ]
    rr = report["B2_synthetic"]["retrieval_regression"]
    if "chapter_hit" in rr:
        lines.append(
            f"- Retrieval regression hit@5 (no filter, all): {rr['chapter_hit']['no_filter']['all']['hit_at_5']}; abstention probes below floor: {rr['abstention_probes']}"
        )
    lines.append(f"- Explanation regression: {report['B2_synthetic']['explanation_regression']}")
    lines += [
        "",
        "## B3. Human review",
        "",
        f"- {report['B3_human_review']}",
        "",
        "## B4. Real learner evidence",
        "",
        f"- {report['B4_real_learner_evidence']}",
        "",
        "## B5. Blocked or needing independent humans",
        "",
        *[f"- {x}" for x in report["B5_blocked_or_insufficient"]],
        "",
    ]
    (OUT / f"full_{stamp}.md").write_text("\n".join(lines))
    print("\n".join(lines))
    print(f"report: {(OUT / f'full_{stamp}.md').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
