"""Table-type and non-outcome rules, ported from TVET (src/extraction/table_rules.py)."""

from src.extraction.table_rules import (
    DESCRIPTIVE,
    RESULTS,
    UNKNOWN,
    classify_table,
    is_descriptive_column,
    is_non_outcome_label,
    is_pipe_table,
    looks_garbled,
    reclassify_pipe_tables,
)


def test_pipe_table_text_is_told_from_prose():
    assert is_pipe_table("# Table 1: Effects\n| Group | Coef |\n| --- | --- |\n| GUP | 0.05 |")
    assert not is_pipe_table("The programme raised consumption by 0.05 standard deviations.")
    assert not is_pipe_table("| only one row |")


def test_a_pipe_table_typed_as_text_is_reclassified():
    content = [{"type": "text", "page_idx": 17, "text": "Table 2\n| a | b |\n| --- | --- |\n| 1 | 2 |"},
               {"type": "text", "page_idx": 18, "text": "Ordinary paragraph."},
               {"type": "table", "page_idx": 9, "text": "| a | b |\n| --- | --- |\n| 1 | 2 |"}]
    out = reclassify_pipe_tables(content)
    assert [item["type"] for item in out] == ["table", "text", "table"]
    assert out[0]["page_idx"] == 17 and content[0]["type"] == "text"
    assert out[0]["reclassified"] is True and "reclassified" not in out[2]


def test_a_repaired_transcription_is_left_as_text():
    content = [{"type": "text", "page_idx": 5, "text": "Table 1\n| a | b |\n| --- | --- |\n| 1 | 2 |",
                "repaired": True}]
    assert reclassify_pipe_tables(content)[0]["type"] == "text"


def test_balance_and_summary_tables_are_descriptive():
    assert classify_table("Table 1: Balance table, baseline characteristics")[0] == DESCRIPTIVE
    assert classify_table("Summary statistics of the sample")[0] == DESCRIPTIVE
    assert classify_table("Attrition and sample characteristics")[0] == DESCRIPTIVE
    assert classify_table("Table 3. Propensity score matching, covariates")[0] == DESCRIPTIVE


def test_a_matching_results_table_is_results_not_balance():
    assert classify_table("Table 1. Double-difference propensity score matching results")[0] == RESULTS


def test_a_baseline_column_does_not_make_a_results_table_descriptive():
    kind, reason = classify_table(
        "Table 1. Difference-in-difference estimate of programme impact",
        "", "Outcome | Baseline mean | Follow-up | Difference")
    assert kind == RESULTS
    assert "impact" in reason


def test_impact_and_regression_tables_are_results():
    assert classify_table("Table 4: Impacts of the programme on consumption")[0] == RESULTS
    assert classify_table("Table 2. Regression results, treatment effect")[0] == RESULTS
    assert classify_table("Estimation results: ITT and ATT")[0] == RESULTS


def test_a_descriptive_cue_wins_over_a_results_cue():
    kind, reason = classify_table("Baseline characteristics and impacts")
    assert kind == DESCRIPTIVE
    assert "baseline" in reason


def test_missing_context_is_unknown():
    assert classify_table("")[0] == UNKNOWN


def test_non_outcome_row_labels():
    for label in ("Observations", "Number of observations", "R-squared", "Adjusted R2",
                  "Constant", "Controls", "Fixed effects", "F-statistic", "N", "SD", "Clusters"):
        assert is_non_outcome_label(label), label
    for label in ("Total consumption", "Age of household head", "Probability of employment",
                  "Average effect of T1", "Mean impact on consumption"):
        assert not is_non_outcome_label(label), label


def test_descriptive_columns():
    assert is_descriptive_column("Control mean")
    assert is_descriptive_column("Standard deviation")
    assert is_descriptive_column("SD")
    assert not is_descriptive_column("Coefficient")
    assert not is_descriptive_column("Standard error")


def test_garbled_table_text_is_detected():
    assert looks_garbled("| ????? ?? ???????a114 ????a116a115 ?? ??a80? ???a |", min_chars=10)
    assert not looks_garbled("| Outcome | Coefficient | Standard error |\n| --- | --- | --- |")


def test_a_units_note_in_parentheses_does_not_make_a_row_a_non_outcome():
    assert is_non_outcome_label("Per capita income (BDT constant price)") is False
    assert is_non_outcome_label("Consumption (mean per adult equivalent)") is False
    assert is_non_outcome_label("Constant") is True
    assert is_non_outcome_label("Mean in pure control") is True
    assert is_non_outcome_label("Prob > F") is True


def test_an_outcome_that_begins_with_average_is_not_a_summary_row():
    assert is_non_outcome_label("Average price") is False
    assert is_non_outcome_label("Average price (animals sold)") is False
    assert is_non_outcome_label("Average") is True
    assert is_non_outcome_label("Mean in pure control") is True
    assert is_non_outcome_label("Average treatment effect") is False


def test_regression_terms_keep_only_the_programme():
    from src.extraction.table_rules import is_programme_term

    assert is_programme_term("SUP × Post")
    assert is_programme_term("Treatment")
    assert is_programme_term("TUP")
    assert not is_programme_term("SUP 2002")
    assert not is_programme_term("Year 2005")
    assert not is_programme_term("Cohort 3")
    assert not is_programme_term("House damaged")
    assert not is_programme_term("Religious group")


def test_before_after_and_balance_tables_are_recognised():
    from src.extraction.table_rules import is_balance_table, is_before_after_table

    assert is_before_after_table(["", "Baseline", "Endline"])
    assert not is_before_after_table(["", "Baseline", "Impact"])
    assert is_balance_table("Table 2: Sample", ["", "(1)", "(2)", "(3) Raw Differences"])
    assert not is_balance_table("Table 2: Baseline characteristics and impacts", ["", "Baseline", "Impact"])


def test_p_value_header_and_regression_table():
    from src.extraction.table_rules import is_p_value_header, is_regression_table

    assert is_p_value_header("P")
    assert is_p_value_header("2006 P")
    assert is_p_value_header("p-value")
    assert not is_p_value_header("Predicted")
    assert is_regression_table("Table 6: Determinants of income", ["", "Model 1", "Model 2"])
