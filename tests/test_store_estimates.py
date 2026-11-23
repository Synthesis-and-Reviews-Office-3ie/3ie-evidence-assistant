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


def test_a_vision_row_without_the_flag_keeps_open_rather_than_null():
    from src.extraction.store_estimates import unify_keys

    table_row = _row({"outcome": "Income", "estimate_cell": "155.43*** (121.73)", "se_cell": "(121.73)"})
    table_row["keep_effect"] = False
    vision_row = {"source": "tables_v1", "page": 9, "outcome_name": "Consumption",
                  "effect_size": 1.5, "row_key": None}  # vision/prose rows carry no role flag
    unified = unify_keys([table_row, vision_row])
    assert all(r["keep_effect"] is True or r["keep_effect"] is False for r in unified)
    assert [r["keep_effect"] for r in unified if r["outcome_name"] == "Consumption"] == [True]


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


def test_two_rounds_with_equal_labels_and_values_do_not_collide_when_addressed():
    from src.extraction.store_estimates import unify_keys

    # Asadullah 2016 Table 2, "Unemployed" men, 1.2 in 2005 and 1.2 in 2008. The round has left the label,
    # so the label key is the same; the cell address keeps the two apart.
    a = {"outcome_name": "Unemployed", "treatment_arm": "Men", "effect_size": 1.2, "page": 12,
         "table_index": 2, "cell_row": 4, "cell_column": 3, "effect_type": "main", "time_point": "2005"}
    b = dict(a, cell_row=5, time_point="2008")
    rows = unify_keys([a, b])
    assert len(rows) == 2 and rows[0]["row_key"] != rows[1]["row_key"]


def test_two_specifications_with_equal_values_do_not_collide_when_addressed():
    from src.extraction.store_estimates import unify_keys

    # Misha 2019 Table 4, formal loans, -0.098 in D4 and D5.
    a = {"outcome_name": "Formal loans", "effect_size": -0.098, "page": 30, "table_index": 4,
         "cell_row": 6, "cell_column": 4, "specification": "D4", "effect_type": "main"}
    b = dict(a, cell_column=5, specification="D5")
    rows = unify_keys([a, b])
    assert len(rows) == 2 and rows[0]["row_key"] != rows[1]["row_key"]


def test_a_row_without_an_address_still_uses_the_label_key():
    from src.extraction.identity import row_key

    assert row_key("tables_v1", 3, " Income ", None, None, 155.43) == \
        row_key("tables_v1", 3, "income", "", "", 155.4300000001)
    assert row_key("tables_v1", 3, "Income", None, None, 1.2) != \
        row_key("tables_v1", 3, "Income", None, None, 1.2, table_index=2, cell_row=4, cell_column=3)


def test_a_run_that_loses_many_rows_is_flagged_not_patched():
    from src.extraction.store_estimates import shrink_flag

    # No carry-forward: a run keeps exactly what it read. A big drop is flagged for review instead.
    assert shrink_flag(5, 10)                 # half the rows: flag
    assert shrink_flag(0, 40)                 # none: flag
    assert not shrink_flag(8, 10)             # a small drop is normal churn
    assert not shrink_flag(0, 0)              # a new document is not a shrink


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


def test_the_structured_label_columns_are_written():
    estimate = _row({"outcome": "Income", "estimate_cell": "155.43*** (121.73)", "se_cell": "(121.73)"})
    estimate.update({"time_point": "2005", "population": "other poor women",
                     "effect_type": "percent change vs control mean", "specification": "D4",
                     "estimand": "ITT", "quantile": "q50"})
    row = rows_for("p", DOC, {"estimates": [estimate]}, "m")[0]
    assert row["time_point"] == "2005" and row["population"] == "other poor women"
    assert row["effect_type"] == "percent change vs control mean"
    assert row["specification"] == "D4" and row["estimand"] == "ITT" and row["quantile"] == "q50"


def test_effect_type_defaults_to_main():
    estimate = _row({"outcome": "Income", "estimate_cell": "155.43*** (121.73)", "se_cell": "(121.73)"})
    estimate.pop("effect_type", None)
    assert rows_for("p", DOC, {"estimates": [estimate]}, "m")[0]["effect_type"] == "main"


def test_a_run_that_stores_nothing_does_not_empty_a_document():
    # Insert-first, then delete by id: an empty run must skip the replacement entirely.
    from src.extraction.store_estimates import should_skip_replace

    assert should_skip_replace([]) is True
    assert should_skip_replace([{"row_key": "a"}]) is False


def test_only_rows_the_new_run_did_not_reproduce_are_deleted():
    from src.extraction.store_estimates import stale_row_ids

    previous = [{"id": "1", "row_key": "a"}, {"id": "2", "row_key": "b"}, {"id": "3", "row_key": "c"}]
    assert stale_row_ids(previous, {"a", "b"}) == ["3"]
    assert stale_row_ids(previous, {"a", "b", "c"}) == []
    # Unchanged rows are kept (upserted), never deleted: the document is not emptied.
