"""Standardised effect sizes for pooling (src/extraction/effect_sizes.py)."""

import math

from src.extraction.effect_sizes import d_from_coefficient, hedges_correction, standardise


def test_d_from_a_coefficient_and_its_sd():
    out = d_from_coefficient(0.5, 0.1, 1.0)
    assert out["d"] == 0.5
    assert math.isclose(out["var_d"], 0.01)


def test_hedges_correction_is_close_to_one_for_large_samples():
    assert math.isclose(hedges_correction(100, 100), 1 - 3 / 791)


def test_standardise_produces_g_and_its_error():
    out = standardise({"effect_size": 0.5, "standard_error": 0.1, "control_sd": 1.0,
                       "n_treatment": 100, "n_control": 100})
    j = 1 - 3 / 791
    assert math.isclose(out["d"], 0.5)
    assert math.isclose(out["yi"], j * 0.5)
    assert math.isclose(out["vi"], (j ** 2) * 0.01)
    assert math.isclose(out["se_g"], math.sqrt(out["vi"]))
    assert "formula_used" in out


def test_missing_sd_or_sample_size_returns_nothing():
    assert standardise({"effect_size": 0.5, "standard_error": 0.1}) is None
    assert standardise({"effect_size": 0.5, "control_sd": 1.0}) is None
    assert standardise({"effect_size": 0.5, "standard_error": 0.1, "control_sd": 1.0,
                        "n_treatment": 100}) is None
