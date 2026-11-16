"""Stored rows: the standardised columns are written from the inputs the row carries."""

from dataclasses import asdict

import pytest

from src.extraction.store_estimates import rows_for
from src.extraction.table_estimates import to_estimate

TABLE = ("| Outcome | Treatment | Control mean (SD) |\n| --- | --- | --- |\n"
         "| Income | 155.43*** (121.73) | 2,540.00 (612.5) |\n| Obs | 716 | 948 |")
DOC = {"id": 1, "filename": "paper.pdf"}


def _row(raw, text=TABLE):
    return asdict(to_estimate(raw, "Table 1", 3, text))


def test_standardised_columns_are_written_when_the_inputs_exist():
    estimate = _row({"outcome": "Income", "estimate_cell": "155.43*** (121.73)", "se_cell": "(121.73)",
                     "control_mean_cell": "2,540.00 (612.5)", "control_sd_cell": "2,540.00 (612.5)",
                     "n_treatment_cell": "716", "n_control_cell": "948"})
    row = rows_for("p", DOC, {"estimates": [estimate]}, "m")[0]
    assert row["control_sd"] == 612.5 and row["n_treatment"] == 716 and row["n_control"] == 948
    assert row["effect_size_d"] == pytest.approx(155.43 / 612.5)
    assert row["se_g"] == pytest.approx(row["var_g"] ** 0.5)
    assert row["hedges_g"] is not None and row["var_g"] > 0


def test_standardised_columns_stay_null_when_the_inputs_are_missing():
    estimate = _row({"outcome": "Income", "estimate_cell": "155.43", "se_cell": "(121.73)"},
                    "| Income | 155.43 (121.73) |")
    row = rows_for("p", DOC, {"estimates": [estimate]}, "m")[0]
    assert row["effect_size_d"] is None and row["hedges_g"] is None and row["var_g"] is None
    assert row["se_g"] is None


def test_rows_from_different_readers_are_given_the_same_keys():
    from src.extraction.store_estimates import unify_keys

    rows = unify_keys([{"a": 1, "b": 2}, {"a": 3}])
    assert rows == [{"a": 1, "b": 2}, {"a": 3, "b": None}]
