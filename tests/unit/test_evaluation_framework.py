"""The evaluation framework: statistics, catalogue rules, report honesty, review pipeline.

These tests check the MEASURING INSTRUMENTS. A passing run says the instruments behave as
specified; it says nothing about the educational quality of any content.
"""

from __future__ import annotations

import csv
import json
import types
from pathlib import Path

import pytest
from live_db_fixtures import live_engine, pg_fixture  # noqa: F401  (fixtures)

from evaluation import bank_metrics, citations, review, run
from evaluation.catalog import BY_ID, CATALOG
from evaluation.stats import cohen_kappa, rate, recall_at_k, reciprocal_rank, wilson

# --- statistics ---


def test_wilson_interval_known_values() -> None:
    low, high = wilson(50, 100)  # type: ignore[misc]
    assert (low, high) == (0.4038, 0.5962)
    assert wilson(0, 0) is None
    assert wilson(10, 10)[1] == 1.0  # type: ignore[index]


def test_small_cells_are_insufficient_data_not_rates() -> None:
    assert rate(3, 9) == {"status": "insufficient_data", "n": 9, "min_n": 10}
    measured = rate(3, 10)
    assert measured["status"] == "measured" and measured["rate"] == 0.3 and measured["ci95"]


def test_kappa_and_ranking_metrics() -> None:
    assert cohen_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == 1.0
    assert cohen_kappa(["a", "a", "b", "b"], ["a", "b", "a", "b"]) == 0.0
    assert cohen_kappa(["a", "a"], ["a", "a"]) is None  # chance agreement is total: undefined
    assert recall_at_k(["x", "y", "z"], {"y", "q"}, 2) == 0.5
    assert reciprocal_rank(["x", "y", "z"], {"z"}) == pytest.approx(1 / 3)
    assert reciprocal_rank(["x"], set()) is None


def test_chi_square_flags_a_skewed_key_position() -> None:
    assert bank_metrics.chi_square_uniform_p([25, 25, 25, 25]) == 1.0
    assert bank_metrics.chi_square_uniform_p([46, 131, 47, 22]) < 0.001


# --- catalogue rules ---


def test_catalogue_never_lets_automation_stand_in_for_human_quality() -> None:
    kinds = {m.kind for m in CATALOG}
    assert kinds <= {
        "software_correctness",
        "automated_property",
        "proxy",
        "human_quality",
        "outcome",
        "ai_review",
        "synthetic",
    }
    for m in CATALOG:
        if m.kind in ("ai_review", "synthetic"):
            assert "human" not in m.name.lower(), m.id  # never presented as human evidence
        if m.kind == "human_quality":
            assert m.automation == "human_required", m.id
        if m.kind == "outcome":
            assert m.automation == "blocked" and m.blocker, m.id
        if m.automation != "automated":
            assert m.blocker, f"{m.id} needs a stated blocker"
    for suite in ("scoring", "questions", "retrieval", "explanation", "bkt", "adaptive"):
        assert any(m.suite == suite for m in CATALOG), suite


# --- benchmark data ---


def test_benchmark_files_are_sealed_and_not_generated_content() -> None:
    check = run.manifest_check()
    assert check["unchanged_since_seal"], check
    for name in ("scoring_cases.jsonl", "adaptive_cases.jsonl", "bkt_known_answers.jsonl"):
        for case in run.read_jsonl(run.BENCH / name):
            assert case["label_provenance"] in {
                "engineer_constructed_from_scoring_rules",
                "engineer_constructed_from_written_policy",
                "hand_derivable_exact_rational_arithmetic_from_bkt_equations",
            }
    suites = json.loads(run.MANIFEST.read_text())["suites"]
    for name in (
        "retrieval",
        "explanation",
        "question_review",
        "bkt_sequences",
        "learning_outcome",
    ):
        assert suites[name]["status"] in {"no_cases", "no_reviews", "no_real_data"}


def test_software_suites_pass_and_can_fail(monkeypatch) -> None:
    scoring = run.scoring_suite()
    assert scoring["passed"] == scoring["cases"] >= 30 and not scoring["failures"]
    assert {"single_choice", "multiple_select", "true_false", "numeric"} <= set(
        scoring["by_item_type"]
    )
    adaptive = run.adaptive_suite()["adaptive.policy_conformance"]
    assert adaptive["passed"] == adaptive["cases"] and not adaptive["failures"]
    # the instrument must be able to fail: a scorer that always says "correct" is caught
    bad = types.SimpleNamespace(status="correct", reason=None)
    monkeypatch.setattr(run, "evaluate_answer", lambda *_a, **_k: bad)
    assert run.scoring_suite()["failures"]


def test_bkt_known_answers_use_independent_arithmetic() -> None:
    vectors = run.read_jsonl(run.BENCH / "bkt_known_answers.jsonl")
    assert len(vectors) >= 4
    out = run.bkt_suite(None)
    assert out["bkt.known_answers"]["passed"] == len(vectors)
    assert out["bkt.real_prediction"]["status"] == "not_measured"  # no data source given
    assert "accuracy" not in json.dumps(out["bkt.real_prediction"]).lower().replace(
        "no accuracy", ""
    )


# --- the report never invents a quality number ---


@pytest.mark.live_db
def test_report_is_honest_and_reproducible(tmp_path) -> None:
    args = types.SimpleNamespace(live_retrieval=False, explanation_outputs=None, review_packet=None)
    first, second = run.build(args), run.build(args)
    assert first["metrics_sha256"] == second["metrics_sha256"]  # deterministic section only
    quality = first["metrics"]["quality_measurements"]
    assert quality["human_review"]["status"] == "not_measured"
    assert quality["explanations"]["status"] == "not_measured"
    assert quality["retrieval"]["retrieval.recall_mrr"]["status"] == "blocked"
    assert (
        quality["questions"]["questions.review_status"]["with_recorded_human_review"]["count"] == 0
    )
    flat = json.dumps(first["metrics"]).lower()
    assert '"accuracy"' not in flat and '"recall_at_5"' not in flat and '"mrr' not in flat
    text = run.render(first)
    for metric in CATALOG:
        if metric.automation == "human_required":
            assert metric.id in text, metric.id  # every human-only metric is listed as not measured
    assert "not_measured" in text and "blocked" in text
    assert BY_ID["bkt.real_prediction"].blocker in text


@pytest.mark.live_db
def test_question_rows_cover_the_required_breakdowns(pg) -> None:
    rows = bank_metrics.question_rows(pg)
    report = bank_metrics.question_bank_report(rows)
    cell = report["questions.structure"]["servable_by_deterministic_rules"]
    assert set(cell) == {"overall", "class_level", "subject_id", "chapter", "language", "item_type"}


# --- citation checks ---


def test_citation_checks_catch_invented_labels_and_uncited_answers() -> None:
    evidence = [
        {
            "label": "E1",
            "source_id": "S",
            "pdf_page_index": 3,
            "text": "A fraction names equal parts of a whole object.",
        }
    ]
    good = {
        "case_id": "c1",
        "evidence": evidence,
        "answer": {
            "explanation": "A fraction names equal parts of a whole object (E1).",
            "evidence_labels": [],
        },
    }
    assert citations.check_record(good)["all_cited_labels_were_supplied"] is True
    invented = {
        **good,
        "answer": {"explanation": "Something else entirely (E7).", "evidence_labels": []},
    }
    result = citations.check_record(invented)
    assert result["invented_labels"] == ["E7"] and not result["all_cited_labels_were_supplied"]
    uncited = {**good, "answer": {"explanation": "A confident answer with no citation at all."}}
    assert citations.check_record(uncited)["answered_without_any_citation"] is True
    assert (
        citations.check_record({**uncited, "abstained": True})["answered_without_any_citation"]
        is False
    )
    off_topic = {
        **good,
        "answer": {
            "explanation": "Volcanoes erupt molten rock through cracks (E1).",
            "evidence_labels": ["E1"],
        },
    }
    assert citations.check_record(off_topic)["sentences_below_overlap_floor"] == 1


# --- human review pipeline ---


def synthetic_packet(tmp_path: Path, reviewers: dict[str, list[tuple[str, str, str]]]) -> Path:
    keys = {
        f"Q{i}": {
            "item_type": "single_choice",
            "stored_key": "B",
            "class_level": 7 + i % 2,
            "subject_id": "science",
            "language": "en",
            "chapter": "CH1",
        }
        for i in range(24)
    }
    (tmp_path / "completed").mkdir()
    (tmp_path / "key_sealed.json").write_text(json.dumps(keys))
    for reviewer, rows in reviewers.items():
        with (tmp_path / "completed" / f"{reviewer}.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["item_id", *review.REVIEWER_COLUMNS])
            writer.writeheader()
            for item, answer, decision in rows:
                writer.writerow(
                    {
                        "item_id": item,
                        "reviewer_id": reviewer,
                        "blind_answer": answer,
                        "ambiguous": "no",
                        "kc_alignment": "3",
                        "age_language_fit": "3",
                        "distractor_quality": "2",
                        "explanation_correct": "yes",
                        "passage_dependent": "no",
                        "decision": decision,
                    }
                )
    return tmp_path


def test_review_report_without_reviews_is_not_measured(tmp_path) -> None:
    packet = synthetic_packet(tmp_path, {})
    assert review.report(packet)["status"] == "not_measured"


def test_review_report_rates_cells_and_flags_small_strata(tmp_path) -> None:
    rows = [(f"Q{i}", "B" if i != 3 else "C", "accept" if i != 3 else "reject") for i in range(24)]
    packet = synthetic_packet(tmp_path, {"rev-a": rows})
    out = review.report(packet)
    key = out["blind_answer_agrees_with_stored_key"]
    assert key["overall"]["count"] == 23 and key["overall"]["n"] == 24
    assert key["class_level"]["7"]["status"] == "measured"  # 12 items
    assert out["decision_reject"]["overall"]["count"] == 1
    assert out["inter_rater"]["kappa_decision"] == "insufficient_data"  # one reviewer only
    small = review.report(
        synthetic_packet(tmp_path / "s", {"rev-a": rows[:6]})
        if (tmp_path / "s").mkdir() is None
        else tmp_path
    )
    assert small["blind_answer_agrees_with_stored_key"]["overall"]["status"] == "insufficient_data"


def test_review_ingest_rejects_malformed_rows_and_measures_agreement(tmp_path) -> None:
    ra = [(f"Q{i}", "B", "accept") for i in range(24)]
    rb = [(f"Q{i}", "B" if i % 4 else "A", "accept" if i % 4 else "revise") for i in range(24)]
    packet = synthetic_packet(tmp_path, {"rev-a": ra, "rev-b": rb})
    out = review.report(packet)
    assert out["inter_rater"]["items_with_two_reviewers"] == 24
    assert isinstance(out["inter_rater"]["kappa_decision"], float)
    bad = tmp_path / "completed" / "rev-c.csv"
    bad.write_text(
        "item_id,reviewer_id,blind_answer,ambiguous,kc_alignment,age_language_fit,"
        "distractor_quality,explanation_correct,passage_dependent,decision,comments\n"
        "Q1,rev-c,B,maybe,3,3,3,yes,no,accept,\n"
    )
    assert any("ambiguous must be yes/no" in e for e in review.report(packet)["errors"])


def test_stratified_sample_is_deterministic_and_spread() -> None:
    rows = [
        {"question_id": f"Q{c}{s}{t}{n}", "class_level": c, "subject_id": s, "item_type": t}
        for c in (6, 7)
        for s in ("a", "b")
        for t in ("single_choice", "true_false")
        for n in range(5)
    ]
    first, again = (
        review.stratified_sample(rows, 8, seed=3),
        review.stratified_sample(rows, 8, seed=3),
    )
    assert first == again and len(first) == 8
    assert len({(r["class_level"], r["subject_id"], r["item_type"]) for r in first}) == 8
    assert review.normalise_answer("multiple_select", "c; a") == "A;C"
    assert review.normalise_answer("true_false", " true ") == "True"


# --- human-labelled retrieval scorer ---


def retrieval_case(n: int, provenance: str, answerable: bool = True) -> dict:
    return {
        "case_id": f"r{n}",
        "class_level": 7,
        "subject_id": "science",
        "language": "en",
        "label_provenance": provenance,
        "answerable": answerable,
        "relevant_pages": [
            {"source_id": "S", "pdf_page_index": 3, "grade": 3},
            {"source_id": "S", "pdf_page_index": 9, "grade": 1},
        ]
        if answerable
        else [],
    }


def test_retrieval_scorer_ignores_non_human_labels_and_scores_the_rest() -> None:
    ai = [retrieval_case(i, "ai_generated_unverified") for i in range(30)]
    assert run.retrieval_human_metrics(ai, lambda _c: [])["status"] == "not_measured"
    human = [retrieval_case(i, "human_reviewed_single") for i in range(12)]
    human += [retrieval_case(100 + i, "human_reviewed_single", answerable=False) for i in range(10)]

    def rank(case):
        if not case["answerable"]:
            return []
        return [("S", 9), ("S", 3)]  # grade-1 page first, the relevant page second

    out = run.retrieval_human_metrics(human + ai, rank)
    assert out["ignored_non_human_cases"] == 30 and out["answerable_cases"] == 12
    assert out["recall_at_5"]["overall"]["mean"] == 1.0  # the grade-3 page is in the top 5
    assert out["mrr_at_10"]["overall"]["mean"] == 0.5  # ... at rank 2; grade-1 page not relevant
    assert out["unanswerable_returns_nothing"]["count"] == 10
    few = run.retrieval_human_metrics(human[:4], rank)
    assert few["recall_at_5"]["overall"]["status"] == "insufficient_data"


def test_benchmark_readme_documents_every_catalogue_metric() -> None:
    text = (run.BENCH.parent / "README.md").read_text(encoding="utf-8")
    for metric in CATALOG:
        assert f"`{metric.id}`" in text, metric.id
