"""D4 and D11 pilot tooling. The sheets below are SYNTHETIC test input, not reviewer results."""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

import pytest

from data_pipeline.kc_graph import pilots

MATRIX = (Path(__file__).parents[2] / "docs/PHASE_5_DECISION_MATRIX.md").read_text(encoding="utf-8")


def test_items_match_appendix_a_exactly() -> None:
    part = MATRIX.split("## Appendix A", 1)[1].split("## Appendix B", 1)[0]
    rows = re.findall(r"^\| (\d+) \| (\w+) \| (.+?) \| (\w+) \|$", part, re.M)
    assert [(int(n), s, k, t) for n, s, k, t in rows] == list(pilots.TAXONOMY_ITEMS)


def test_reviewer_form_hides_the_key() -> None:
    form = pilots.reviewer_form()
    rows = list(csv.DictReader(io.StringIO(form)))
    assert len(rows) == 30 and all(r["assigned_type"] == "" for r in rows)
    assert [r["skill"] for r in rows] == [skill for _, _, skill, _ in pilots.TAXONOMY_ITEMS]
    assert not {key for *_, key in pilots.TAXONOMY_ITEMS} & {v for r in rows for v in r.values()}
    assert "provisional" not in form.lower()


def sheet(code: str, answers: dict[int, str]) -> list[dict[str, str]]:
    out = []
    for n, s, skill, key in pilots.TAXONOMY_ITEMS:
        a = answers.get(n, key)
        out.append(
            {
                "skill_no": str(n),
                "subject": s,
                "skill": skill,
                "reviewer_code": code,
                "assigned_type": "" if a == "none" else a,
                "confidence": "3",
                "none_fits": "yes" if a == "none" else "no",
                "none_fits_explanation": "x" if a == "none" else "",
                "note": "",
                "minutes": "1",
            }
        )
    return out


def test_no_scores_without_two_complete_independent_sheets() -> None:
    assert pilots.score_taxonomy(None, None)["status"] == "pending_human_assessment"
    a = sheet("RV-002", {})
    assert pilots.score_taxonomy(a, a)["status"] == "invalid_sheets"  # same reviewer
    assert pilots.score_taxonomy(a[:29], sheet("RV-003", {}))["status"] == "invalid_sheets"
    result = pilots.score_taxonomy(a, sheet("RV-003", {}), register_codes={"RV-002"})
    assert result["status"] == "invalid_sheets"


def test_metrics_from_synthetic_sheets() -> None:
    a = sheet("RV-002", {})
    b = sheet("RV-003", {6: "vocabulary", 24: "none"})
    result = pilots.score_taxonomy(a, b)
    assert result["status"] == "scored" and "not frozen" in result["d4"]
    assert result["percent_agreement"]["overall"] == round(28 / 30, 4)
    assert result["percent_agreement"]["english"] == round(5 / 6, 4)
    assert result["disagreements"] == [6, 24] and result["adjudication_pending"] == [6, 24]
    assert result["confusion"]["concept|vocabulary"] == 1
    assert result["none_fits_rate"]["science"] == round(1 / 12, 4)
    adjudication = [
        {"skill_no": "6", "adjudicator_code": "RV-004", "final_type": "fact", "note": "neither"}
    ]
    assert pilots.score_taxonomy(a, b, adjudication)["ambiguous"] == [6]


def test_kappa_and_wilson_reference_values() -> None:
    assert pilots.cohen_kappa(list("aabb"), list("aabb")) == 1.0
    assert pilots.cohen_kappa(list("ab"), list("ba")) == -1.0
    assert pilots.cohen_kappa(list("aaaa"), list("aaaa")) is None
    assert pilots.wilson(10, 20) == (0.2993, 0.7007)  # about +/-0.2 around one half
    assert pilots.wilson(50, 100) == (0.4038, 0.5962)
    assert pilots.wilson(0, 0) is None


def test_sampling_is_a_census_up_to_100_and_seeded_otherwise() -> None:
    small = [(f"E{i}", "mathematics") for i in range(40)]
    assert pilots.stratified_sample(small, seed=1)["design"] == "census"
    big = [(f"E{s}{i}", s) for s in pilots.SUBJECTS for i in range(40)]
    one, two = pilots.stratified_sample(big, seed=7), pilots.stratified_sample(big, seed=7)
    assert one == two and len(one["edges"]) == 100 and one["seed"] == 7


def test_evidence_pilot_scoring() -> None:
    assert pilots.score_evidence([])["status"] == "pending_human_review"
    rows = []
    for i, (cls_a, cls_b) in enumerate([("a", "a"), ("b", "b"), ("a", "b"), ("c", "c")]):
        for code, cls in (("RV-002", cls_a), ("RV-003", cls_b)):
            rows.append(
                {
                    "edge_key": f"E{i}",
                    "subject": "science",
                    "stratum": "science",
                    "reviewer_code": code,
                    "class": cls,
                    "evidence_tokens": "t" if cls == "a" else "",
                    "supports": "yes",
                    "decision": "approved" if cls != "c" else "rejected",
                    "minutes": "8",
                    "disagreed": "",
                    "adjudicated_class": "b" if i == 2 else "",
                }
            )
    result = pilots.score_evidence(rows)
    assert result["status"] == "scored" and result["edges"] == 4
    overall = result["expert_only_share_among_real"]["overall"]
    assert overall["n"] == 3 and overall["expert_only"] == 2
    assert result["minutes_per_review"]["mean"] == 8.0 and len(result["limitations"]) == 7
    with pytest.raises(KeyError):
        pilots.score_evidence([{"subject": "x"}])
    assert pilots.score_evidence(rows[:1])["status"] == "invalid_sheets"
