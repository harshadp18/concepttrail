import pytest

from app.services.bkt_service import BKTParameters, update_mastery


def test_parameters_parse_canonical_keys():
    params = BKTParameters.from_mapping({"p_l0": 0.30, "p_t": 0.15, "p_g": 0.20, "p_s": 0.10})
    assert params.initial_knowledge == 0.30
    assert params.learning == 0.15


def test_correct_observation_increases_mastery_for_standard_parameters():
    params = BKTParameters(0.30, 0.15, 0.20, 0.10)
    assert update_mastery(0.30, True, params) == pytest.approx(0.7097560975609757)


def test_incorrect_observation_applies_slip_guess_bayes_update():
    params = BKTParameters(0.30, 0.15, 0.20, 0.10)
    result = update_mastery(0.30, False, params)
    assert result == pytest.approx(0.19322033898305085)


def test_configuration_rejects_invalid_probability():
    with pytest.raises(ValueError):
        BKTParameters.from_mapping({"p_l0": 1.2, "p_t": 0.15, "p_g": 0.20, "p_s": 0.10})


def test_configuration_requires_explicit_versioned_parameters():
    with pytest.raises(ValueError):
        BKTParameters.from_mapping({})
