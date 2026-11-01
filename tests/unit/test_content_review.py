"""AI content-review patch: integrity, honesty of labels, original additions, safe application."""

from __future__ import annotations

import collections
import copy
import itertools
import json

import pytest
import sympy as sp
from live_db_fixtures import live_engine, pg_fixture  # noqa: F401  (fixtures)

from data_pipeline.content_review import patch as patch_mod
from data_pipeline.content_review import records

# The review records (AI-drafted, textbook-derived content) are private and Git-ignored; a public
# checkout does not have them (docs/PUBLICATION_AND_REPRODUCIBILITY.md).
if not (records.available() and patch_mod.PATCH.exists()):
    pytest.skip("private content-review records are not in this checkout", allow_module_level=True)

ADDITIONS = records.additions()
OUTCOME_KCS = records.outcome_kcs()
OUTCOME_QUESTIONS = records.outcome_questions()
PATCH = json.loads(patch_mod.PATCH.read_text(encoding="utf-8"))
STICKS = {"1": 2, "7": 3, "4": 4, "2": 5, "3": 5, "5": 5, "0": 6, "6": 6, "9": 6, "8": 7}


def test_patch_is_ai_review_only_and_every_change_has_evidence() -> None:
    assert PATCH["review_type"] == "ai_reviewed" and "not a human reviewer" in PATCH["reviewer"]
    assert "Not an independent human" in PATCH["statement"]
    text = json.dumps(PATCH).lower()
    assert '"human_reviewed": true' not in text
    assert '"review_status": "approved"' not in text and '"review_status": "published"' not in text
    for op in PATCH["operations"]:
        assert op.get("evidence"), op
        if op["op"] == "update_question":
            assert op["before"] != op["after"]
    verdicts = collections.Counter(v["verdict"] for v in PATCH["verdicts"].values())
    assert sum(verdicts.values()) == 460  # every existing question received a verdict
    assert set(verdicts) == {"no_defect_found", "repaired", "withdrawn", "escalated"}
    assert all(e.get("evidence") for e in PATCH["escalations"])


def test_single_answer_repairs_keep_exactly_one_key() -> None:
    for op in PATCH["operations"]:
        if op["op"] != "update_question":
            continue
        correct = sum(o["is_correct"] for o in op["after"]["options"].values())
        assert correct >= 1, op["question_id"]
        if op["after"]["expected_answer"] and "value" in op["after"]["expected_answer"]:
            value = op["after"]["expected_answer"]["value"]
            true_option = [
                o for o in op["after"]["options"].values() if o["text"].strip().casefold() == "true"
            ]
            if true_option:
                assert true_option[0]["is_correct"] is value, op["question_id"]


def test_additions_are_original_single_answer_explained_and_balanced() -> None:
    positions, tf = collections.Counter(), collections.Counter()
    for a in ADDITIONS:
        s = a["question"]
        assert s["item_type"] in ("single_choice", "true_false")
        correct = [o for o in s["options"] if o["correct"]]
        assert len(correct) == 1, s["question_id"]
        assert len({o["text"] for o in s["options"]}) == len(s["options"])
        assert all(len(o["why"]) >= 10 for o in s["options"])
        assert "page" not in s["stem"].lower() and "according to the text" not in s["stem"].lower()
        if s["item_type"] == "single_choice":
            positions[correct[0]["key"]] += 1
        else:
            tf[correct[0]["text"]] += 1
            assert s["expected_answer"]["value"] is (correct[0]["text"] == "True")
    assert min(positions.values()) >= 5 and max(positions.values()) <= 12, positions
    assert tf["True"] >= 3 and tf["False"] >= 3, tf
    adds = [op for op in PATCH["operations"] if op["op"] == "add_question"]
    assert len(adds) == len(ADDITIONS) + len(OUTCOME_QUESTIONS)


def test_outcome_kcs_quote_the_verified_catalogue_and_stay_unverified() -> None:
    import json as _json

    from data_pipeline.content_review.records import CATALOGUE

    catalogue = {
        o["objective"] for o in _json.loads(CATALOGUE.read_text(encoding="utf-8"))["outcomes"]
    }
    for kc in OUTCOME_KCS:
        assert kc["outcome"]["objective"] in catalogue  # verbatim official outcome
        assert kc["description"].startswith(kc["outcome"]["objective"])
        assert "cbseacademic.nic.in" in kc["outcome"]["source_url"]
    per_kc = collections.Counter(a["question"]["kc_id"] for a in OUTCOME_QUESTIONS)
    assert set(per_kc) == {k["kc_id"] for k in OUTCOME_KCS} and min(per_kc.values()) >= 3
    for a in OUTCOME_QUESTIONS:
        assert len([o for o in a["question"]["options"] if o["correct"]]) == 1


def _spec(qid: str) -> dict:
    return next(a["question"] for a in ADDITIONS if a["question"]["question_id"] == qid)


def _key(qid: str) -> str:
    return next(o["text"] for o in _spec(qid)["options"] if o["correct"])


def parse(text: str):
    from sympy.parsing.sympy_parser import (
        implicit_multiplication_application,
        parse_expr,
        standard_transformations,
    )

    return parse_expr(
        text.strip("$").replace("^", "**"),
        transformations=(*standard_transformations, implicit_multiplication_application),
    )


def _max_number(sticks: int) -> int:
    best = -1
    for length in range(1, 5):
        for digits in itertools.product(STICKS, repeat=length):
            if sum(STICKS[d] for d in digits) == sticks and (length == 1 or digits[0] != "0"):
                best = max(best, int("".join(digits)))
    return best


def test_maths_additions_keys_rederived_independently() -> None:
    x = sp.symbols("x")
    assert _key("Q-MAT-C07-cr1-001") == str(_max_number(6))
    assert int(_key("Q-MAT-C07-cr1-002")) == sum(STICKS[d] for d in "2026")
    assert _max_number(7) == 711 and _spec("Q-MAT-C07-cr1-003")["expected_answer"]["value"] is True
    assert sp.expand((x - 5) ** 2) == parse(_key("Q-MAT-C09-cr1-001"))
    assert (x**2 - 3 * x + 2).subs(x, 2) == 0 and _key("Q-MAT-C10-cr1-001").startswith("0")
    assert sp.solve(3 * x - 6, x) == [int(_key("Q-MAT-C10-cr1-002"))]
    assert (2 * x**2 - 8).subs(x, 4) != 0 and _spec("Q-MAT-C10-cr1-003")["expected_answer"][
        "value"
    ] is False
    unit = int(_key("Q-MAT-C08-cr1-001").replace(",", "")) % 10
    assert unit not in {n * n % 10 for n in range(10)}
    for option in _spec("Q-MAT-C08-cr1-001")["options"]:
        if not option["correct"]:
            value = int(option["text"].replace(",", ""))
            assert sp.sqrt(value).is_integer  # every distractor really is a perfect square


@pytest.mark.live_db
def test_apply_is_transactional_idempotent_and_refuses_drift(pg) -> None:
    first = patch_mod.apply(pg, PATCH)
    if first["already_applied"] == 0:
        assert first["updated"] == 44 and first["withdrawn"] == 30
        assert first["added"] == len(ADDITIONS) + len(OUTCOME_QUESTIONS) and first["kcs_added"] == 6
        assert first["edges_removed"] == 21 and first["kcs_updated"] == 7
    again = patch_mod.apply(pg, PATCH)
    assert again["updated"] == again["withdrawn"] == again["added"] == again["edges_removed"] == 0
    from app.db.models import Question

    q = pg.get(Question, "Q-MAT-C06-0965f386705f")
    assert q.review_status == "demo_release" and q.verification["human_reviewed"] is False
    assert q.verification["ai_review"]["type"] == "ai_reviewed"
    drifted = copy.deepcopy(PATCH)
    op = next(o for o in drifted["operations"] if o["op"] == "update_question")
    op["after"]["stem"] += " (changed elsewhere)"
    with pytest.raises(patch_mod.PatchConflict):
        patch_mod.apply(pg, drifted)
