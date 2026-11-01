"""BKT calibration and adaptive-policy evaluation tools (synthetic, deterministic, fast)."""

from __future__ import annotations

from app.services.bkt_service import BKTParameters
from evaluation import adaptive_policy_sim as sim
from evaluation import bkt_calibration as cal


def test_metrics_on_known_values() -> None:
    scored = [(0.9, True), (0.8, True), (0.3, False), (0.6, False)]
    assert round(cal.brier(scored), 4) == round((0.01 + 0.04 + 0.09 + 0.36) / 4, 4)
    assert cal.auc(scored) == 1.0
    assert cal.auc([(0.5, True), (0.5, False)]) == 0.5
    assert cal.auc([(0.5, True)]) is None
    table = cal.calibration(scored, bins=2)
    assert [row["n"] for row in table] == [1, 3]


def test_fitting_recovers_known_parameters_on_synthetic_data() -> None:
    true = BKTParameters(0.25, 0.12, 0.2, 0.08)
    data = cal.simulate(true, learners=120, kcs=3, length=12, seed=3)
    fitted = cal.fit(data, rounds=3, steps=15)
    for name in cal.BOUNDS:
        assert abs(getattr(fitted, name) - getattr(true, name)) < 0.08, name
    assert cal.log_loss(cal.pairs(fitted, data)) <= cal.log_loss(
        cal.pairs(BKTParameters(0.5, 0.3, 0.3, 0.3), data)
    )


def test_real_mode_refuses_to_fit_without_enough_data(monkeypatch) -> None:
    monkeypatch.setattr(cal, "load_real", lambda: [cal.Sequence_("L1", "K", (True, False))])
    out = cal.run_real(min_events=2000)
    assert out["status"] == "insufficient_data" and "fitted_parameters" not in out


def test_policy_edge_cases_are_controlled_outcomes() -> None:
    cases = sim.edge_cases()
    assert cases["empty_history"]["category"] == "remediate_prerequisite"
    assert cases["no_questions"]["reason"] == "no_recommendable_content"
    assert cases["all_mastered"]["reason"] == "all_scoped_kcs_mastered"
    assert cases["no_released_graph"]["reason"] == "graph_not_released"


def test_policy_simulation_is_deterministic() -> None:
    t = sim.adaptive.Thresholds(0.95, 0.7)
    assert sim.evaluate(t, 20, seed=5) == sim.evaluate(t, 20, seed=5)


def test_vectorised_bkt_matches_runtime_equations_and_recovers_parameters() -> None:
    import numpy as np

    from evaluation import bkt_synthetic as bs
    from evaluation.synthetic_learners import KC_TYPES, generate

    kc = KC_TYPES[0]
    ds = generate(kc, 150, 12, seed=11)
    assert bs.scalar_agreement(bs.truth_vec(kc), ds) < 1e-12  # same maths as the runtime
    fitted = bs.fit(ds)
    assert np.max(np.abs(fitted - bs.truth_vec(kc))) < 0.12
    assert fitted[2] < 0.5 and fitted[3] < 0.5  # identifiability constraints hold


def test_synthetic_learners_are_reproducible_and_marked() -> None:
    from evaluation.synthetic_learners import KC_TYPES, Mismatch, generate

    a = generate(KC_TYPES[1], 20, 8, seed=3, population="mixed", mismatch=Mismatch(forget=0.05))
    b = generate(KC_TYPES[1], 20, 8, seed=3, population="mixed", mismatch=Mismatch(forget=0.05))
    assert (a.outcomes == b.outcomes).all() and a.profiles == b.profiles
    record = a.records()[0]
    assert record["synthetic"] is True and record["mark"] == "SYNTHETIC-NOT-REAL-LEARNERS"
    truncated = generate(KC_TYPES[0], 50, 10, seed=4, min_length=2, truncate_prob=0.5)
    assert truncated.events < 50 * 10


def test_policy_simulation_is_deterministic_and_conditions_bite() -> None:
    from evaluation import policy_simulation as ps

    base = ps.CONDITIONS[0]
    assert ps.simulate(base, "conceptrail", 100, 0) == ps.simulate(base, "conceptrail", 100, 0)
    truth = ps.true_edges(100)
    assert ps.corrupt(truth, 100) != truth  # the wrong-graph condition really is wrong
    for policy in ps.POLICIES:
        result = ps.simulate(base, policy, 100, 1)
        assert 0.0 <= result["final_mastery"] <= 1.0


def test_explanation_arithmetic_checker() -> None:
    from evaluation.explanation_suite import arithmetic_errors

    assert arithmetic_errors("So 4 + 6 = 10 and 3 x 4 = 12.") == []
    assert arithmetic_errors("Hence 7 - 2 = 4.") == ["7.0 - 2.0 = 4.0"]
