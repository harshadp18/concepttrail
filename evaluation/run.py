# ruff: noqa: E501  (report text is prose; long lines are intentional)
"""Reproducible evaluation report.

    python -m evaluation.run                              # offline, read-only
    python -m evaluation.run --live-retrieval             # + scope-leakage probe (local embedder)
    python -m evaluation.run --explanation-outputs FILE   # + citation checks on captured answers
    python -m evaluation.run --review-packet DIR          # + results of completed human reviews
    python -m evaluation.run --seal                       # refresh benchmark file hashes

The report separates SOFTWARE CORRECTNESS (the code matches its written specification; ground
truth is the spec) from QUALITY MEASUREMENTS (is the educational content good; ground truth must
be independent human judgement). Every catalogue metric appears with an explicit status:
`measured`, `proxy` (a computable stand-in, not an accuracy), `insufficient_data`, `not_measured`
or `blocked`. Passing tests is never reported as educational accuracy. Benchmark data lives in
`evaluation/benchmarks/` and is never produced from the content it evaluates. Output goes to
`.local/evaluation/reports/` (git-ignored) as JSON plus Markdown; `metrics_sha256` fingerprints the
deterministic part so two runs on the same inputs can be compared.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.services import adaptive, graph_runtime
from app.services.bkt_service import BKTParameters, update_mastery
from app.services.evaluation import Option, QuestionKey, evaluate_answer
from app.services.prerequisite_graph import EdgeRecord, KcRecord, PrerequisiteGraph, validate_graph
from evaluation import bank_metrics, bkt_calibration, citations, review
from evaluation.catalog import BY_ID, CATALOG
from evaluation.stats import MIN_STRATUM, rate, recall_at_k, reciprocal_rank

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "evaluation/benchmarks/v1"
MANIFEST = BENCH / "manifest.json"
OUT = ROOT / ".local/evaluation/reports"
EMBED_LOG = ROOT / "data_pipeline/data/logs/embedding_eval"


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- benchmark files -------------------------------------------------------------------------


def benchmark_files() -> list[Path]:
    return sorted(p for p in BENCH.rglob("*") if p.is_file() and p.name != "manifest.json")


def seal() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["files"] = {str(p.relative_to(BENCH)): sha256(p) for p in benchmark_files()}
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def manifest_check() -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    current = {str(p.relative_to(BENCH)): sha256(p) for p in benchmark_files()}
    sealed = manifest.get("files", {})
    changed = sorted(k for k in current if sealed.get(k) != current[k])
    missing = sorted(k for k in sealed if k not in current)
    return {
        "dataset_version": manifest["dataset_version"],
        "files": len(current),
        "unchanged_since_seal": not changed and not missing,
        "changed_or_unsealed": changed,
        "missing": missing,
        "suites": manifest["suites"],
    }


# --- software-correctness suites (ground truth = the written specification) -----------------------


def scoring_suite() -> dict:
    cases = read_jsonl(BENCH / "scoring_cases.jsonl")
    failures, by_type = [], {}
    for case in cases:
        q = case["question"]
        key = QuestionKey(
            question_id=case["case_id"],
            version=1,
            item_type=q["item_type"],
            options=tuple(Option(o["key"], o["is_correct"]) for o in q["options"]),
            expected_answer=q["expected_answer"],
        )
        got = evaluate_answer(key, case["submitted"])
        want = case["expected"]
        ok = got.status == want["status"] and ("reason" not in want or got.reason == want["reason"])
        cell = by_type.setdefault(case["item_type"], {"cases": 0, "passed": 0})
        cell["cases"] += 1
        cell["passed"] += ok
        if not ok:
            failures.append(
                {"case_id": case["case_id"], "expected": want, "got": [got.status, got.reason]}
            )
    return {
        "kind": "software_correctness",
        "status": "measured",
        "label_provenance": "engineer_constructed_from_scoring_rules",
        "cases": len(cases),
        "passed": len(cases) - len(failures),
        "by_item_type": by_type,
        "failures": failures,
        "interpretation": "The evaluator matches its written rules on these cases. It is not a "
        "claim about the educational correctness of any stored answer key.",
    }


def bkt_suite(session: Session | None) -> dict:
    vectors = read_jsonl(BENCH / "bkt_known_answers.jsonl")
    failures = []
    for v in vectors:
        params = BKTParameters.from_mapping(v["params"])
        mastery, path = params.initial_knowledge, []
        for observed in v["observations"]:
            mastery = update_mastery(mastery, observed, params)
            path.append(mastery)
        if any(abs(a - b) > 1e-9 for a, b in zip(path, v["expected_after_each"], strict=True)):
            failures.append(v["case_id"])
    simulation = bkt_calibration.run_simulation(learners=300, seed=7)
    real = bkt_calibration.run_real(min_events=2000) if session is not None else None
    return {
        "bkt.known_answers": {
            "kind": "software_correctness",
            "status": "measured",
            "label_provenance": "exact_rational_arithmetic_from_bkt_equations",
            "vectors": len(vectors),
            "passed": len(vectors) - len(failures),
            "failures": failures,
        },
        "bkt.fit_pipeline": {
            "kind": "software_correctness",
            "status": "measured",
            "label_provenance": "synthetic_learners_pipeline_check_only",
            "max_abs_parameter_error": max(simulation["parameter_error"].values()),
            "held_out_events": simulation["held_out"]["fitted"]["events"],
            "interpretation": "Fitting recovers known parameters from synthetic data. It is "
            "evidence about the code, not about any real learner or parameter value.",
        },
        "bkt.real_prediction": {
            "kind": "outcome",
            "status": "insufficient_data" if real else "not_measured",
            **(
                {k: real[k] for k in ("events", "learners", "kcs", "min_events", "min_learners")}
                if real
                else {}
            ),
            "runtime_parameters": "provisional and uncalibrated (bkt-provisional-v1)",
            "interpretation": "No accuracy, log-loss or calibration is reported: there is not "
            "enough real longitudinal response data to measure one.",
        },
    }


def graph_from_case(case: dict) -> graph_runtime.ReleasedGraph | graph_runtime.GraphUnavailable:
    if case["graph"] is None:
        return graph_runtime.GraphUnavailable(case["graph_unavailable_reason"])
    kcs = [
        KcRecord(
            kc_id=n["id"],
            stable_key=f"bench.{n['id'].lower()}",
            subject_id="mathematics",
            name=n["id"],
            review_status="approved",
            class_levels=tuple(n["class_levels"]),
            scope=n["scope"],
        )
        for n in case["graph"]["nodes"]
    ]
    edges = [
        EdgeRecord(
            prerequisite_kc_id=a,
            dependent_kc_id=b,
            reason="benchmark",
            evidence_refs=("bench",),
            review_status="approved",
        )
        for a, b in case["graph"]["edges"]
    ]
    report = validate_graph(kcs, edges)
    return graph_runtime.ReleasedGraph(
        PrerequisiteGraph(kcs, report), 1, "0" * 64, {k.kc_id: k.model_dump() for k in kcs}
    )


def adaptive_suite() -> dict:
    cases = read_jsonl(BENCH / "adaptive_cases.jsonl")
    failures = []
    for case in cases:
        scope = adaptive.LearnerScope(
            case["scope"]["class_level"],
            tuple(case["scope"]["subject_ids"]) if case["scope"]["subject_ids"] else None,
        )
        mastery = {k: adaptive.MasteryView(*v) for k, v in case["mastery"].items()}
        questions = {
            k: [adaptive.QuestionView(f"Q-{k}-{d}", d) for d in diffs]
            for k, diffs in case["questions"].items()
        }
        out = adaptive.explain_recommendation(
            adaptive.recommend(
                graph_from_case(case), scope, mastery, questions, set(case["attempted"])
            )
        )
        want = case["expected"]
        if any(out.get(k) != v for k, v in want.items()):
            failures.append(
                {"case_id": case["case_id"], "expected": want, "got": {k: out.get(k) for k in want}}
            )
    return {
        "adaptive.policy_conformance": {
            "kind": "software_correctness",
            "status": "measured",
            "label_provenance": "engineer_constructed_from_written_policy",
            "cases": len(cases),
            "passed": len(cases) - len(failures),
            "failures": failures,
            "interpretation": "The recommender follows the written provisional policy. It does "
            "not show the policy helps anyone learn; thresholds stay provisional.",
        },
        "adaptive.simulation": {
            "kind": "proxy",
            "status": "not_measured",
            "note": "run `python -m evaluation.adaptive_policy_sim` (synthetic)",
        },
        "adaptive.learning_gain": {
            "kind": "outcome",
            "status": "blocked",
            "blocker": BY_ID["adaptive.learning_gain"].blocker,
        },
    }


# --- database-backed suites ------------------------------------------------------------------------


def questions_suite(session: Session) -> dict:
    rows = bank_metrics.question_rows(session)
    report = bank_metrics.question_bank_report(rows)
    report["coverage"] = bank_metrics.kc_coverage_report(session, rows)
    quality = {
        m.id: {
            "kind": m.kind,
            "status": "blocked" if m.automation == "human_required" else "?",
            "blocker": m.blocker,
        }
        for m in CATALOG
        if m.suite == "questions" and m.automation == "human_required"
    }
    report["human_quality_metrics"] = quality
    report["fingerprint"] = hashlib.sha256(
        "|".join(sorted(f"{r['question_id']}:{r['review_status']}" for r in rows)).encode()
    ).hexdigest()
    return report


def embedding_history() -> dict:
    logs = sorted(EMBED_LOG.glob("embedding_eval_*.json")) if EMBED_LOG.exists() else []
    if not logs:
        return {"status": "not_measured"}
    data = json.loads(logs[-1].read_text(encoding="utf-8"))
    chosen = next((m for m in data["models"] if "bge-m3" in m["model_id"]), None)
    return {
        "kind": "proxy",
        "status": "proxy",
        "source_file": logs[-1].name,
        "model_id": chosen["model_id"] if chosen else None,
        "queries": chosen["metrics"]["all"]["n"] if chosen else None,
        "queries_by_language": {
            k: v["n"] for k, v in (chosen["metrics"] if chosen else {}).items() if k != "all"
        },
        "caveat": "Relevance was derived from AI-generated learning objectives and verbatim "
        "term matches, so it is not independent ground truth, and the query set is small. "
        "Recall/MRR values are deliberately not reproduced here as quality figures.",
    }


HUMAN_LABELS = {"human_expert_verified", "human_reviewed_single"}


def retrieval_human_metrics(cases: list[dict], rank) -> dict:
    """Recall@5 / MRR@10 on human-labelled cases; `rank(case)` returns ranked (source, page).

    Cases whose label_provenance is not human are ignored and counted. A page counts as
    relevant at grade >= 2 (answers the query fully or partly). Unanswerable cases are scored
    separately: the good outcome is that nothing clears the retrieval floor.
    """
    usable = [c for c in cases if c.get("label_provenance") in HUMAN_LABELS]
    ignored = len(cases) - len(usable)
    if not usable:
        return {
            "status": "not_measured",
            "ignored_non_human_cases": ignored,
            "reason": "no human-labelled retrieval cases",
        }
    answerable = [c for c in usable if c["answerable"]]
    scored, empty_ok = [], []
    for case in usable:
        ranked = rank(case)
        if case["answerable"]:
            relevant = {
                (r["source_id"], r["pdf_page_index"])
                for r in case["relevant_pages"]
                if r["grade"] >= 2
            }
            scored.append(
                {
                    **case,
                    "recall5": recall_at_k(ranked, relevant, 5),
                    "rr10": reciprocal_rank(ranked, relevant, 10),
                }
            )
        else:
            empty_ok.append({**case, "none_returned": not ranked})

    def mean_cells(items: list[dict], field: str) -> dict:
        out: dict[str, Any] = {}
        for dim in ("class_level", "subject_id", "language"):
            groups: dict[str, list[float]] = {}
            for item in items:
                if item[field] is not None:
                    groups.setdefault(str(item[dim]), []).append(item[field])
            out[dim] = {
                k: (
                    {"status": "measured", "n": len(v), "mean": round(sum(v) / len(v), 4)}
                    if len(v) >= MIN_STRATUM
                    else {"status": "insufficient_data", "n": len(v)}
                )
                for k, v in sorted(groups.items())
            }
        values = [i[field] for i in items if i[field] is not None]
        out["overall"] = (
            {"status": "measured", "n": len(values), "mean": round(sum(values) / len(values), 4)}
            if len(values) >= MIN_STRATUM
            else {"status": "insufficient_data", "n": len(values)}
        )
        return out

    return {
        "status": "measured",
        "ignored_non_human_cases": ignored,
        "answerable_cases": len(answerable),
        "unanswerable_cases": len(empty_ok),
        "recall_at_5": mean_cells(scored, "recall5"),
        "mrr_at_10": mean_cells(scored, "rr10"),
        "unanswerable_returns_nothing": rate(
            sum(c["none_returned"] for c in empty_ok), len(empty_ok)
        ),
    }


def live_ranker(session: Session):
    from app.db.models import EmbeddingChunk
    from app.services.embeddings import OllamaEmbedder
    from app.services.rag import RetrievalFilter, retrieve_evidence

    embedder = OllamaEmbedder("bge-m3")
    model_id = embedder.describe().model_id
    generation = session.scalar(select(func.min(EmbeddingChunk.index_generation)))

    def rank(case: dict) -> list[tuple[str, int]]:
        evidence = retrieve_evidence(
            session,
            embedder.embed([case["query"]])[0],
            embedding_model_id=model_id,
            index_generation=generation,
            filters=RetrievalFilter(class_level=case["class_level"], subject_id=case["subject_id"]),
            mode="internal",
            k=10,
        )
        return [(e.source_id, e.pdf_page_index) for e in evidence]

    return rank


def retrieval_suite(session: Session, live: bool) -> dict:
    out = {
        "retrieval.index_integrity": {
            "kind": "automated_property",
            **bank_metrics.index_integrity_report(session),
        },
        "retrieval.recall_mrr_ai_labels": embedding_history(),
        "retrieval.recall_mrr": {
            "kind": "human_quality",
            "status": "blocked",
            "blocker": BY_ID["retrieval.recall_mrr"].blocker,
        },
    }
    human_cases = BENCH / "retrieval_cases.jsonl"
    if human_cases.exists() and live:
        out["retrieval.recall_mrr"] = {
            "kind": "human_quality",
            **retrieval_human_metrics(read_jsonl(human_cases), live_ranker(session)),
        }
    out["retrieval.filter_leakage"] = (
        live_leakage(session)
        if live
        else {
            "kind": "software_correctness",
            "status": "not_measured",
            "note": "run with --live-retrieval (needs the local embedding model)",
        }
    )
    return out


def live_leakage(session: Session, per_cell: int = 3) -> dict:
    from app.db.models import (
        CurriculumItem,
        CurriculumVersion,
        EmbeddingChunk,
        KnowledgeComponent,
        SourceDocument,
    )
    from app.services.embeddings import EmbeddingError, OllamaEmbedder
    from app.services.rag import RetrievalFilter, retrieve_evidence

    scope = {
        (v.class_level, i.subject_id)
        for i, v in session.execute(
            select(CurriculumItem, CurriculumVersion).join(
                CurriculumVersion,
                CurriculumVersion.curriculum_version_id == CurriculumItem.curriculum_version_id,
            )
        )
        if v.class_level is not None
    }
    kc_names: dict[str, list[str]] = {}
    for kc in session.scalars(select(KnowledgeComponent).order_by(KnowledgeComponent.kc_id)):
        kc_names.setdefault(kc.subject_id, []).append(kc.name)
    try:
        embedder = OllamaEmbedder("bge-m3")
        model_id = embedder.describe().model_id
        generation = session.scalar(select(func.min(EmbeddingChunk.index_generation)))
    except EmbeddingError:
        return {
            "kind": "software_correctness",
            "status": "not_measured",
            "note": "local embedding model unavailable",
        }
    queries = results = leaks = cells = 0
    for level, subject in sorted(scope):
        names = kc_names.get(subject, [])[:per_cell]
        if not names:
            continue
        cells += 1
        for vector in embedder.embed(names):
            queries += 1
            evidence = retrieve_evidence(
                session,
                vector,
                embedding_model_id=model_id,
                index_generation=generation,
                filters=RetrievalFilter(class_level=level, subject_id=subject),
                mode="internal",
                k=8,
                min_score=0.0,
            )
            for e in evidence:
                results += 1
                version = session.scalar(
                    select(CurriculumVersion.class_level).where(
                        CurriculumVersion.curriculum_version_id == e.curriculum_version_id
                    )
                )
                source_subject = session.scalar(
                    select(SourceDocument.subject_id).where(SourceDocument.source_id == e.source_id)
                )
                leaks += not (version == level and source_subject == subject)
    return {
        "kind": "software_correctness",
        "status": "measured",
        "class_subject_cells": cells,
        "queries": queries,
        "results_checked": results,
        "leaks": leaks,
        "mode": "internal (class/subject filters only; student-mode release filters are covered "
        "by the unit tests because no human-approved pages exist yet)",
        "interpretation": "Scope-filter correctness. It says nothing about relevance.",
    }


def explanation_suite(path: Path | None) -> dict:
    blocked = {
        m.id: {"kind": m.kind, "status": "blocked", "blocker": m.blocker}
        for m in CATALOG
        if m.suite == "explanation" and m.automation == "human_required"
    }
    if path is None:
        return {
            "captured_outputs": 0,
            "status": "not_measured",
            "note": "no captured grounded answers were supplied (--explanation-outputs)",
            **blocked,
            "explanation.citation_resolves": {
                "kind": "software_correctness",
                "status": "not_measured",
            },
            "explanation.lexical_support": {"kind": "proxy", "status": "not_measured"},
        }
    records = read_jsonl(path)
    checks = [citations.check_record(r) for r in records]
    answered = [c for c in checks if not c["abstained"]]
    resolved = sum(c["all_cited_labels_were_supplied"] for c in answered)
    return {
        "captured_outputs": len(records),
        "answered": len(answered),
        "abstained": len(checks) - len(answered),
        "explanation.citation_resolves": {
            "kind": "software_correctness",
            "status": "measured",
            "answered_with_all_labels_supplied": rate(resolved, len(answered), 1),
            "answered_without_any_citation": sum(
                c["answered_without_any_citation"] for c in answered
            ),
            "invented_labels": sum(len(c["invented_labels"]) for c in answered),
        },
        "explanation.lexical_support": {
            "kind": "proxy",
            "status": "proxy",
            "sentences_below_overlap_floor": sum(
                c.get("sentences_below_overlap_floor", 0) for c in answered
            ),
            "sentences": sum(c.get("sentences", 0) for c in answered),
            "caveat": "token overlap; a wrong conclusion built from the page's words still scores high",
        },
        **blocked,
    }


# --- assembly -------------------------------------------------------------------------------------


def database_summary(session: Session) -> dict:
    tables = [
        r[0]
        for r in session.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'concepttrail' "
                "AND table_type = 'BASE TABLE' ORDER BY 1"
            )
        )
    ]
    counts = {t: session.scalar(text(f'SELECT count(*) FROM concepttrail."{t}"')) for t in tables}
    return {
        "tables": len(tables),
        "alembic": session.scalar(text("SELECT version_num FROM public.alembic_version")),
        "row_counts": {
            k: counts[k]
            for k in (
                "knowledge_component",
                "kc_edge",
                "questions",
                "question_options",
                "embedding_chunk",
                "attempts",
            )
        },
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    from app.db.session import create_db_engine

    deterministic: dict[str, Any] = {
        "benchmark": manifest_check(),
        "software_correctness": {"scoring": scoring_suite(), "adaptive": adaptive_suite()},
    }
    environment = {
        "python": platform.python_version(),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    with Session(create_db_engine(read_only=True)) as session:
        deterministic["database"] = database_summary(session)
        deterministic["software_correctness"]["bkt"] = bkt_suite(session)
        deterministic["quality_measurements"] = {
            "questions": questions_suite(session),
            "retrieval": retrieval_suite(session, args.live_retrieval),
            "explanations": explanation_suite(args.explanation_outputs),
            "human_review": (
                review.report(args.review_packet)
                if args.review_packet
                else {"status": "not_measured", "reason": "no completed human review supplied"}
            ),
        }
    catalog = {
        m.id: {
            "suite": m.suite,
            "name": m.name,
            "kind": m.kind,
            "automation": m.automation,
            "ground_truth": m.ground_truth,
            "blocker": m.blocker,
        }
        for m in CATALOG
    }
    body = {"report_version": 1, "metrics": deterministic, "catalog": catalog}
    body["metrics_sha256"] = hashlib.sha256(
        json.dumps(deterministic, sort_keys=True, default=str).encode()
    ).hexdigest()
    return {**body, "environment": environment}


def render(report: dict) -> str:
    m = report["metrics"]
    sw, q = m["software_correctness"], m["quality_measurements"]
    qb, ret, hum = q["questions"], q["retrieval"], q["human_review"]
    lines = [
        f"# ConceptTrail evaluation report (dataset {m['benchmark']['dataset_version']})",
        "",
        f"Generated {report['environment']['generated_at']} | metrics fingerprint "
        f"`{report['metrics_sha256'][:16]}` | benchmark files unchanged since seal: "
        f"{m['benchmark']['unchanged_since_seal']}",
        "",
        "**How to read this.** Section 1 checks that the software matches its written specification. "
        "Passing it says nothing about educational quality. Section 2 describes stored content with "
        "automated properties and proxies; none is an accuracy figure. Quality (is a key right, is a "
        "question clear, is an explanation supported) is `not_measured` until independent humans review it.",
        "",
        "## 1. Software correctness (ground truth = the written specification)",
        "",
        "| Check | Result | Provenance of expected values |",
        "|---|---|---|",
    ]
    s = sw["scoring"]
    lines.append(
        f"| Deterministic answer scoring | {s['passed']}/{s['cases']} cases | {s['label_provenance']} |"
    )
    for cell, v in sorted(s["by_item_type"].items()):
        lines.append(f"| - {cell} | {v['passed']}/{v['cases']} | |")
    a = sw["adaptive"]["adaptive.policy_conformance"]
    lines.append(
        f"| Adaptive policy conformance | {a['passed']}/{a['cases']} cases | {a['label_provenance']} |"
    )
    b = sw["bkt"]
    lines.append(
        f"| BKT known-answer vectors | {b['bkt.known_answers']['passed']}/{b['bkt.known_answers']['vectors']} | {b['bkt.known_answers']['label_provenance']} |"
    )
    lines.append(
        f"| BKT fitting recovers synthetic parameters | max abs error {b['bkt.fit_pipeline']['max_abs_parameter_error']} (synthetic) | pipeline check only |"
    )
    lk = ret["retrieval.filter_leakage"]
    lines.append(
        "| Retrieval scope-filter leakage | "
        + (
            f"{lk['leaks']} leaks in {lk['results_checked']} results ({lk['queries']} queries, {lk['class_subject_cells']} class/subject cells)"
            if lk["status"] == "measured"
            else lk["status"]
        )
        + " | scope filters only |"
    )
    lines += ["", "## 2. Stored content: automated properties and proxies (NOT quality)", ""]
    lines.append(
        f"Questions: {qb['questions']} | status {qb['by_status']} | origin {qb['by_origin']}"
    )
    lines.append(f"Types {qb['by_item_type']} | languages {qb['by_language']}")
    rs = qb["questions.review_status"]
    lines.append(
        f"Recorded human reviews: {rs['with_recorded_human_review']['count']}/{rs['with_recorded_human_review']['n']}"
        if rs["with_recorded_human_review"]["status"] == "measured"
        else "Recorded human reviews: n/a"
    )
    kp = qb["questions.key_position_bias"]
    lines.append(
        f"Stored single-choice key positions {kp['single_choice_correct_key_counts']} (uniform chi-square p={kp['uniform_chi_square_p']}; learners see a shuffled order)"
    )

    def pct(cell):
        return (
            f"{cell['rate']:.1%} (n={cell['n']}, 95% CI {cell['ci95'][0]:.1%}-{cell['ci95'][1]:.1%})"
            if cell["status"] == "measured"
            else f"{cell['status']} (n={cell['n']})"
        )

    lines.append(
        f"Correct option is also the longest (single-choice, chance ~25%): {pct(qb['questions.longest_correct_cue']['single_choice']['overall'])}"
    )
    lines.append(
        f"Stem flagged passage-dependent by regex: {pct(qb['questions.passage_dependence']['regex_flagged']['overall'])}"
    )
    lines.append(
        f"Cited source page exists as a stored unit: {pct(qb['questions.source_page_resolvable']['all_refs_resolve_to_a_stored_page']['overall'])} (existence, not support)"
    )
    lines.append(
        f"Options with an explanation: {pct(qb['questions.option_explanations']['options_with_explanation'])}"
    )
    lines.append(
        f"Near-duplicate pairs within a KC: {qb['questions.near_duplicates']['pairs_within_same_kc']}"
    )
    cov = qb["coverage"]
    lines.append(
        f"KC coverage: {cov['knowledge_components']} KCs; questions per KC {cov['questions_per_kc']}; zero-question KCs {cov['kcs_with_zero_questions']}"
    )
    ix = ret["retrieval.index_integrity"]
    lines.append(
        f"Retrieval index: {ix['chunks']} chunks, models {ix['models']}, dimensions {ix['dimensions']}; units without chunks {ix['units_without_chunks']}"
    )
    for name, cell in ix["checks"].items():
        lines.append(f"  - {name}: {pct(cell['overall'])}")
    lines += ["", "## 3. Not measured / blocked", "", "| Metric | Status | Why |", "|---|---|---|"]
    rows = []
    for metric in CATALOG:
        if metric.automation == "human_required" or metric.kind == "outcome":
            status = "blocked" if metric.kind == "outcome" else "not_measured"
            if hum.get("status") == "measured" and metric.suite == "questions":
                status = "pilot_partial (see human review)"
            rows.append(
                f"| {metric.id} | {status} | {metric.blocker or 'needs independent review'} |"
            )
    lines += rows
    lines += [
        "",
        f"Human review: {hum.get('status')}"
        + (f" - {hum.get('reason')}" if hum.get("reason") else ""),
        "",
    ]
    if hum.get("status") == "measured":
        k = hum["blind_answer_agrees_with_stored_key"]["overall"]
        lines.append(
            f"Blind reviewer answer agrees with stored key: {pct(k) if k['status'] == 'measured' else k['status']}"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.run")
    parser.add_argument("--live-retrieval", action="store_true")
    parser.add_argument("--explanation-outputs", type=Path)
    parser.add_argument("--review-packet", type=Path)
    parser.add_argument("--seal", action="store_true")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    if args.seal:
        seal()
        print("sealed", MANIFEST.relative_to(ROOT))
        return 0
    report = build(args)
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (args.out / f"eval_{stamp}.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )
    markdown = render(report)
    (args.out / f"eval_{stamp}.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"report: {args.out / f'eval_{stamp}.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
