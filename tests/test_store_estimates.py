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


def test_the_effect_role_flag_is_written_and_defaults_to_true():
    estimate = _row({"outcome": "Income", "estimate_cell": "155.43*** (121.73)", "se_cell": "(121.73)"})
    row = rows_for("p", DOC, {"estimates": [estimate]}, "m")[0]
    assert row["keep_effect"] is True and row["row_role"] is None and row["column_role"] is None


def test_a_non_effect_role_is_carried_to_the_row():
    estimate = _row({"outcome": "Income", "estimate_cell": "155.43*** (121.73)", "se_cell": "(121.73)"})
    estimate["row_role"], estimate["column_role"], estimate["keep_effect"] = \
        "outcome", "control_or_covariate", False
    row = rows_for("p", DOC, {"estimates": [estimate]}, "m")[0]
    assert row["keep_effect"] is False
    assert row["row_role"] == "outcome" and row["column_role"] == "control_or_covariate"


def test_rows_from_different_readers_are_given_the_same_keys():
    from src.extraction.store_estimates import unify_keys

    rows = unify_keys([{"outcome_name": "Income", "effect_size": 1.0},
                       {"outcome_name": "Income", "effect_size": 1.0, "treatment_arm": "Half"}])
    assert set(rows[0]) == set(rows[1])
    assert rows[0]["row_key"] and rows[0]["row_key"] != rows[1]["row_key"]


def test_the_same_estimate_gets_the_same_key_whatever_the_reader():
    from src.extraction.store_estimates import unify_keys

    first = unify_keys([{"outcome_name": " Income ", "effect_size": 155.43, "page": 3}])[0]
    second = unify_keys([{"outcome_name": "income", "effect_size": 155.4300000001, "page": 3}])[0]
    assert first["row_key"] == second["row_key"]


def test_a_value_the_new_run_missed_is_carried_forward():
    from src.extraction.store_estimates import carried_forward

    new = [{"page": 3, "effect_size": 155.43, "outcome_name": "Income"},
           {"page": 3, "effect_size": 107.0, "outcome_name": "Income per capita"}]
    stored = [{"page": 3, "effect_size": 155.43, "outcome_name": "Total income"},
              {"page": 3, "effect_size": 107.0, "outcome_name": "Income per capita"},
              {"page": 3, "effect_size": 76.5, "outcome_name": "Consumption"},
              {"page": 9, "effect_size": 107.0, "outcome_name": "Income per capita"}]
    kept = carried_forward(new, stored)
    assert [row["effect_size"] for row in kept] == [76.5, 107.0]
    assert [row["page"] for row in kept] == [3, 9]


def test_a_label_change_alone_does_not_carry_a_row():
    from src.extraction.store_estimates import carried_forward

    assert carried_forward([{"page": 3, "effect_size": 155.43}],
                           [{"page": 3, "effect_size": 155.43, "outcome_name": "something else"}]) == []


def test_a_duplicate_identity_in_one_run_is_written_once():
    from src.extraction.store_estimates import unify_keys

    rows = unify_keys([{"outcome_name": "Income", "effect_size": 1.0, "page": 3},
                       {"outcome_name": "Income ", "effect_size": 1.0, "page": 3}])
    assert len(rows) == 1


def test_the_uncertainty_fields_travel_with_the_row():
    from src.extraction.table_estimates import to_estimate

    def row(raw, text):
        return asdict(to_estimate(raw, "t", 3, text))

    ci = row({"outcome": "Income", "estimate_cell": "0.52***", "se_cell": "[0.44, 0.60]", "se_kind": "ci"},
             "| Income | 0.52*** [0.44, 0.60] |")
    stored = rows_for("p", DOC, {"estimates": [ci]}, "m")[0]
    assert stored["ci_low"] == 0.44 and stored["ci_high"] == 0.60 and stored["se_kind"] == "ci"

    tstat = row({"outcome": "Income", "estimate_cell": "0.52***", "se_cell": "4.0", "se_kind": "t"},
                "| Income | 0.52*** | 4.0 |")
    stored = rows_for("p", DOC, {"estimates": [tstat]}, "m")[0]
    assert stored["t_stat"] == 4.0 and stored["se_kind"] == "t"


def test_a_row_whose_total_is_smaller_than_its_arms_loses_the_arms():
    estimate = _row({"outcome": "Income", "estimate_cell": "155.43*** (121.73)",
                     "se_cell": "(121.73)"})
    estimate.update({"n_treatment": 700, "n_control": 900, "sample_size": 400})
    row = rows_for("p", DOC, {"estimates": [estimate]}, "m")[0]
    assert row["n_treatment"] is None and row["n_control"] is None
    assert "sample size is smaller than the arms" in (row["quality_flags"] or "")


def test_a_consistent_row_carries_no_flags():
    estimate = _row({"outcome": "Income", "estimate_cell": "155.43*** (121.73)",
                     "se_cell": "(121.73)"})
    estimate.update({"n_treatment": 700, "n_control": 900, "sample_size": 1600})
    assert rows_for("p", DOC, {"estimates": [estimate]}, "m")[0]["quality_flags"] is None
