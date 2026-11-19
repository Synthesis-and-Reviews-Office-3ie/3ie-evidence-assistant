"""Number parsing and grounding for table estimate extraction (roadmap N6)."""

import pytest

from src.extraction.table_estimates import (count_stars, merge_reads, parse_interval, parse_number,
                                           table_units, to_estimate)


@pytest.mark.parametrize("text, value", [
    ("4,408", 4408.0),          # thousands separator (Burchi 2018, MWK)
    ("17,595***", 17595.0),
    ("1,234,567", 1234567.0),
    ("0,84", 0.84),             # decimal comma (Spanish tables)
    ("0,175", 0.175),           # leading zero: decimal, not 175
    ("1.234,5", 1234.5),
    ("-0.0577**", -0.0577),
    ("−0.18", -0.18),           # Unicode minus
    ("(1,369)", 1369.0),
    ("[0.12]", 0.12),
    ("633.63", 633.63),
    ("", None),
    ("n.s.", None),
])
def test_parse_number(text, value):
    assert parse_number(text) == value


def test_stars_and_intervals():
    assert count_stars("0.21***") == 3 and count_stars("0.21") == 0
    assert parse_interval("[0.05, 0.31]") == (0.05, 0.31)


TABLE = "| Outcome | Impact |\n|---|---|\n| Savings (MWK) | 4,408*** |\n|  | (1,369) |"


def test_grounded_estimate_parses_cells():
    e = to_estimate({"outcome": "Savings (MWK)", "estimate_cell": "4,408***", "se_cell": "(1,369)", "se_kind": "se"},
                    "Table 1", 11, TABLE)
    assert (e.effect_size, e.standard_error, e.stars, e.grounded) == (4408.0, 1369.0, 3, True)


def test_cell_not_in_table_is_not_grounded():
    e = to_estimate({"outcome": "Savings", "estimate_cell": "5,100***", "se_cell": ""}, "Table 1", 11, TABLE)
    assert e.grounded is False and e.notes


def test_table_units_carry_page_caption_and_context():
    items = [{"type": "text", "text": "Notes: standard errors in parentheses."},
             {"type": "table", "text": TABLE, "page_idx": "11", "table_caption": "['Table 1. Impacts']"},
             {"type": "text", "text": "*** p<0.01"}]
    (u,) = table_units(items)
    assert u["page"] == 12 and u["caption"] == "Table 1. Impacts" and "p<0.01" in u["context"]


def test_rows_for_keeps_grounded_numbers_and_cleans_values():
    from src.extraction.store_estimates import estimate_text, rows_for

    base = {"grounded": True, "effect_size": 0.2, "standard_error": float("inf"), "p_value": 3.0, "stars": 2,
            "sample_size": 1200.0, "ci_low": None, "ci_high": None, "table_label": "Table 2", "outcome": "Income\x00",
            "row_label": "Income", "column_label": "(1)", "arm": "", "subgroup": "Women", "estimate_cell": "0.20**",
            "se_cell": "(0.08)", "page": 7}
    out = {"estimates": [base, {**base, "grounded": False}, {**base, "effect_size": None}]}
    rows = rows_for("p", {"id": "d", "filename": "doc"}, out, "m")
    assert len(rows) == 1
    r = rows[0]
    assert r["standard_error"] is None and r["p_value"] is None and r["p_text"] == "**"
    assert r["sample_size"] == 1200 and isinstance(r["sample_size"], int)
    assert r["outcome_name"] == "Income" and r["treatment_arm"] is None
    assert r["literal_text"] == "0.20** (0.08)"
    assert estimate_text(r) == "Income | subgroup: Women"


def _row(outcome, estimate, se=None, arm=""):
    return to_estimate({"outcome": outcome, "estimate_cell": str(estimate), "se_cell": f"({se})" if se else ""},
                       "t", 1, f"| {outcome} | {estimate} |", arm)


def test_a_wide_table_read_two_ways_merges_into_one_row_per_estimate():
    rows = [_row("Income", 107, arm="Half transfer"), _row("Income", 107, se=148), _row("Income", 206)]
    merged = merge_reads(rows)
    assert len(merged) == 2
    assert merged[0].standard_error == 148 and merged[0].arm == "Half transfer"
    assert [r.effect_size for r in merged] == [107.0, 206.0]


def test_distinct_outcomes_are_not_merged():
    merged = merge_reads([_row("Income", 107), _row("Consumption", 107)])
    assert len(merged) == 2


TABLE_WITH_CONTROL = """| Outcome | Treatment | Control mean (SD) |
| --- | --- | --- |
| Income | 155.43*** (121.73) | 2,540.00 (612.5) |
| Consumption | 141.17*** (66.81) | 5,379.00 (733.1) |"""


def test_control_statistics_are_read_only_when_their_cells_are_in_the_table():
    raw = {"outcome": "Income", "estimate_cell": "155.43*** (121.73)", "se_cell": "(121.73)",
           "control_mean_cell": "2,540.00 (612.5)", "control_sd_cell": "2,540.00 (612.5)",
           "n_treatment_cell": "716", "n_control_cell": "948"}
    e = to_estimate(raw, "Table 1", 3, TABLE_WITH_CONTROL + "\n| Obs | 716 | 948 |")
    assert e.control_mean == 2540.0 and e.control_sd == 612.5
    assert e.n_treatment == 716 and e.n_control == 948


def test_a_control_statistic_that_is_not_in_the_table_is_not_taken():
    raw = {"outcome": "Income", "estimate_cell": "155.43*** (121.73)", "se_cell": "(121.73)",
           "control_mean_cell": "9,999.00", "control_sd_cell": "123.4", "n_treatment_cell": "1",
           "n_control_cell": "2"}
    e = to_estimate(raw, "Table 1", 3, TABLE_WITH_CONTROL)
    assert e.control_mean is None and e.control_sd is None
    assert e.n_treatment is None and e.n_control is None


PARTIAL_TABLE = """| Outcome | Coef |
| --- | --- |
| A | 0.1*** |
| B | 0.2*** |
| C | 0.3 |
| D | 0.4 |
| E | 0.5 |"""


def _fake_chat(monkeypatch, replies):
    import src.extraction.table_estimates as module

    calls = []

    async def fake(client, model, prompt):
        calls.append(prompt)
        reply = replies[min(len(calls) - 1, len(replies) - 1)]
        return reply if isinstance(reply, str) else __import__("json").dumps(reply)

    monkeypatch.setattr(module, "_chat", fake)
    return calls


def test_a_table_that_returns_fewer_rows_is_asked_again(monkeypatch):
    import asyncio

    import src.extraction.table_estimates as module

    partial = {"results_table": True, "estimates": [{"outcome": "A", "estimate_cell": "0.1***"}]}
    full = {"results_table": True, "estimates": [
        {"outcome": name, "estimate_cell": value} for name, value in
        (("A", "0.1***"), ("B", "0.2***"), ("C", "0.3"), ("D", "0.4"), ("E", "0.5"))]}
    calls = _fake_chat(monkeypatch, [partial, full])
    out = asyncio.run(module.extract_document([{"type": "table", "page_idx": 0, "text": PARTIAL_TABLE}], "m", "k"))
    assert len(calls) == 2 and "COMPLETENESS" in calls[1]
    assert len(out["estimates"]) == 5


def test_a_complete_table_is_not_asked_again(monkeypatch):
    import asyncio

    import src.extraction.table_estimates as module

    full = {"results_table": True, "estimates": [
        {"outcome": name, "estimate_cell": value} for name, value in
        (("A", "0.1***"), ("B", "0.2***"), ("C", "0.3"), ("D", "0.4"), ("E", "0.5"))]}
    calls = _fake_chat(monkeypatch, [full])
    asyncio.run(module.extract_document([{"type": "table", "page_idx": 0, "text": PARTIAL_TABLE}], "m", "k"))
    assert len(calls) == 1


def test_a_table_the_model_calls_prose_is_read_as_results_when_the_structure_says_so(monkeypatch):
    import asyncio

    import src.extraction.table_estimates as module

    refusal = {"results_table": False, "estimates": []}
    full = {"results_table": True, "estimates": [
        {"outcome": name, "estimate_cell": value} for name, value in
        (("A", "0.1***"), ("B", "0.2***"), ("C", "0.3"), ("D", "0.4"), ("E", "0.5"))]}
    calls = _fake_chat(monkeypatch, [refusal, full])
    out = asyncio.run(module.extract_document([{"type": "table", "page_idx": 0, "text": PARTIAL_TABLE}], "m", "k"))
    assert len(calls) == 2 and "reports estimated effects" in calls[1]
    assert len(out["estimates"]) == 5


def test_a_table_that_skips_one_cell_is_asked_again(monkeypatch):
    import asyncio

    import src.extraction.table_estimates as module

    table = "| Outcome | Coef |\n| --- | --- |\n| A | 0.1*** |\n| B | -0.10 (0.065) |\n| C | 0.3 |\n| D | 0.4 |\n| E | 0.5 |"
    partial = {"results_table": True, "estimates": [
        {"outcome": name, "estimate_cell": value} for name, value in
        (("A", "0.1***"), ("C", "0.3"), ("D", "0.4"), ("E", "0.5"))]}
    full = {"results_table": True, "estimates": [
        {"outcome": name, "estimate_cell": value} for name, value in
        (("A", "0.1***"), ("B", "-0.10 (0.065)"), ("C", "0.3"), ("D", "0.4"), ("E", "0.5"))]}
    calls = _fake_chat(monkeypatch, [partial, full])
    out = asyncio.run(module.extract_document([{"type": "table", "page_idx": 0, "text": table}], "m", "k"))
    assert len(calls) == 2
    assert any(e["outcome"] == "B" for e in out["estimates"])


def test_the_hint_tells_the_model_that_rows_are_subgroups():
    import src.extraction.table_estimates as module

    table = ("| Subgroup | Farm work | Chores |\n| --- | --- | --- |\n"
             "| Gender of child (boy = 1) | 4.206*** | 1.436*** |\n"
             "| Gender of household head | 1.285** | 0.921 |")
    hint = module._structure_hint(module._table_analysis({"text": table, "caption": "", "context": "",
                                                          "index": 0, "page": 1, "arm_hint": ""})[1], table)
    assert "rows are subgroups" in hint


def test_a_column_count_becomes_that_arm_count():
    text = "| Outcome | Half cost |\n| --- | --- |\n| Income | 0.11*** |\n| Observations | 948 |"
    treated = to_estimate({"outcome": "Income", "estimate_cell": "0.11***"}, "t", 3, text,
                          arm_hint="Half cost", n_hint=948)
    assert treated.n_treatment == 948 and treated.n_control is None
    control = to_estimate({"outcome": "Income", "estimate_cell": "0.11***"}, "t", 3, text,
                          arm_hint="Control", n_hint=725)
    assert control.n_control == 725 and control.n_treatment is None


def test_the_two_arm_counts_are_paired_within_an_outcome():
    import src.extraction.table_estimates as module

    treated = module.to_estimate({"outcome": "Income", "arm": "Half cost", "estimate_cell": "0.11***"},
                                 "t", 3, "| Income | 0.11*** |", arm_hint="Half cost")
    treated.n_treatment = 948
    control = module.to_estimate({"outcome": "Income", "arm": "Control", "estimate_cell": "-0.02**"},
                                 "t", 3, "| Income | -0.02** |", arm_hint="Control")
    control.n_control = 725
    module.pair_arm_counts([treated, control])
    assert treated.n_control == 725 and control.n_treatment == 948


def test_a_control_sd_is_joined_by_outcome_within_the_document():
    import src.extraction.table_estimates as module

    effect = module.to_estimate({"outcome": "Income", "estimate_cell": "0.11***", "se_cell": "(0.04)"},
                                "t", 3, "| Income | 0.11*** (0.04) |")
    descriptive = module.to_estimate({"outcome": "income", "estimate_cell": "2,540.00 (612.5)",
                                      "control_sd_cell": "2,540.00 (612.5)"},
                                     "t", 5, "| Income | 2,540.00 (612.5) |")
    other = module.to_estimate({"outcome": "Consumption", "estimate_cell": "276 (109)",
                                "control_sd_cell": "276 (109)"}, "t", 5, "| Consumption | 276 (109) |")
    module.attach_document_statistics([effect, descriptive, other])
    assert effect.control_sd == 612.5
    assert other.control_sd == 109.0


def test_a_zero_standard_error_is_not_stored():
    e = to_estimate({"outcome": "Income", "estimate_cell": "0.11***", "se_cell": "(0.00)"}, "t", 3,
                    "| Income | 0.11*** (0.00) |")
    assert e.standard_error is None


def test_an_interval_that_excludes_its_own_estimate_is_dropped():
    e = to_estimate({"outcome": "Income", "estimate_cell": "2.07", "se_cell": "[2.47, 28.0]",
                     "se_kind": "ci"}, "t", 3, "| Income | 2.07 [2.47, 28.0] |")
    assert e.ci_low is None and e.ci_high is None and e.standard_error is None


def test_a_p_value_that_contradicts_the_stars_is_dropped():
    e = to_estimate({"outcome": "Income", "estimate_cell": "0.11***", "p_cell": "0.04"}, "t", 3,
                    "| Income | 0.11*** (0.04) |")
    assert e.p_value is None
    ok = to_estimate({"outcome": "Income", "estimate_cell": "0.11**", "p_cell": "0.03"}, "t", 3,
                     "| Income | 0.11** (0.03) |")
    assert ok.p_value == 0.03


def test_a_printed_t_statistic_gives_the_standard_error():
    e = to_estimate({"outcome": "Income", "estimate_cell": "0.52***", "se_cell": "4.0", "se_kind": "t"},
                    "t", 3, "| Income | 0.52*** | 4.0 |")
    assert abs(e.standard_error - 0.13) < 1e-9
    assert e.t_stat == 4.0
    zero = to_estimate({"outcome": "Income", "estimate_cell": "0.00", "se_cell": "4.0", "se_kind": "t"},
                       "t", 3, "| Income | 0.00 | 4.0 |")
    assert zero.standard_error is None


def test_a_level_sentence_is_not_a_prose_effect():
    from src.extraction.prose_estimates import states_an_effect

    assert states_an_effect("The probability of owning poultry increases by about 40 percentage points")
    assert states_an_effect("the treatment effect is estimated as 2.7 percentage points")
    assert not states_an_effect("88% of female respondents in households who received a transfer use a VESA")
    assert not states_an_effect("64% of households who received a poultry package reported income from sales")


def test_the_same_row_read_two_ways_is_one_row():
    def row(outcome, value):
        return module_row(outcome, value)

    merged = module_merge([row("(1) Indicator if Household Owns Sheep", 0.076),
                           row("Indicator if Household Owns Sheep", 0.076)])
    assert len(merged) == 1


def module_row(outcome, value):
    import src.extraction.table_estimates as module

    return module.to_estimate({"outcome": outcome, "estimate_cell": f"{value}***"},
                              "t", 35, "| x | 0.076*** |")


def module_merge(rows):
    import src.extraction.table_estimates as module

    return module.merge_reads(rows)


def test_a_label_broken_at_a_hyphen_merges_with_its_whole_form():
    broken = module_row("Livelihoods diversifica- tion", 0.39)
    whole = module_row("Livelihoods diversification", 0.39)
    assert len(module_merge([broken, whole])) == 1


def test_a_row_that_names_the_arm_overrides_the_column_heading():
    e = to_estimate({"outcome": "Bridging social capital", "arm": "Bridging social capital",
                     "estimate_cell": "-0.01 (0.05)"}, "t", 6,
                    "| | Bridging social capital |\n| --- | --- |\n| Treatment | -0.01 (0.05) |",
                    arm_row="Treatment")
    assert e.arm == "Treatment" and e.outcome == "Bridging social capital"


def test_the_printed_cell_is_the_authority_for_the_value():
    table = "| Outcome | Treatment |\n| --- | --- |\n| Income | -0,20** |"
    dropped = to_estimate({"outcome": "Income", "estimate_cell": "0,20**", "row_number": 1,
                           "column_number": 2}, "t", 42, table)
    assert dropped.effect_size == -0.2 and dropped.cell_row == 0 and dropped.cell_column == 1


def test_a_cell_holding_two_numbers_gives_the_one_reported():
    table = "| Outcome | Treatment |\n| --- | --- |\n| Income | -0.027 (0.075) 0.010 (0.07) |"
    second = to_estimate({"outcome": "Income", "estimate_cell": "0.010", "row_number": 1,
                          "column_number": 2}, "t", 39, table)
    assert second.effect_size == 0.01
    first = to_estimate({"outcome": "Income", "estimate_cell": "-0.027", "row_number": 1,
                         "column_number": 2}, "t", 39, table)
    assert first.effect_size == -0.027


def test_the_parameter_is_the_number_beside_the_addressed_coefficient():
    table = "| Outcome | Treatment |\n| --- | --- |\n| Income | (0.706) 1.109 |"
    second = to_estimate({"outcome": "Income", "estimate_cell": "1.109", "se_cell": "(0.706)",
                          "row_number": 1, "column_number": 2}, "t", 14, table)
    # The coefficient comes from the printed cell. Its parameter has no neighbour of its own in a cell that
    # holds two estimates, so the standard error from the model is kept rather than guessed; that residual is
    # measured, about 2 percent of parameters.
    assert second.effect_size == 1.109 and second.standard_error is None

    table2 = "| Outcome | Treatment |\n| --- | --- |\n| Income | 0.076 (0.156) 0.410** |"
    pair = to_estimate({"outcome": "Income", "estimate_cell": "0.076", "se_cell": "(0.999)",
                        "row_number": 1, "column_number": 2}, "t", 20, table2)
    assert pair.effect_size == 0.076 and pair.standard_error == 0.156
    alone = to_estimate({"outcome": "Income", "estimate_cell": "0.410", "se_cell": "(0.076)",
                         "row_number": 1, "column_number": 2}, "t", 20, table2)
    # The cell holds two coefficients and this one has no error beside it, so the model error is dropped.
    assert alone.effect_size == 0.41 and alone.standard_error is None


def test_an_error_printed_before_a_coefficient_is_not_its_own():
    table = "| Outcome | Treatment |\n| --- | --- |\n| Income | (0.706) 1.109 |"
    e = to_estimate({"outcome": "Income", "estimate_cell": "1.109", "se_cell": "(0.706)",
                     "row_number": 1, "column_number": 2}, "t", 14, table)
    assert e.effect_size == 1.109 and e.standard_error is None


def test_value_matching_is_at_printed_precision():
    from src.extraction.table_estimates import _holds

    assert _holds(0.008, "[0.912] 0.008 (0.045)")
    assert not _holds(0.008, "-0.006 (0.058)")
    assert _holds(0.085, "0.0850***")
    assert not _holds(0.085, "0.09***")
    assert _holds(0.16, "0,16")            # decimal comma
    assert _holds(4408, "4,408***")        # thousands separator
    assert not _holds(6, "6.4")            # a whole number is not a nearby decimal


def test_a_repeated_small_number_is_addressed_by_precision():
    from src.extraction.table_estimates import locate_by_value

    table = ("| Outcome | Coef |\n| --- | --- |\n"
             "| A | -0.006 (0.058) |\n"
             "| B | [0.912] 0.008 (0.045) |")
    assert locate_by_value(table, 0.008) == (1, 1)


def test_a_repeated_exact_number_is_addressed_by_its_row_label():
    from src.extraction.table_estimates import locate_by_value

    table = ("| Outcome | Coef |\n| --- | --- |\n"
             "| Ingreso mensual per capita | 0.16 |\n"
             "| Ingreso mensual del participante | 0.16 |")
    assert locate_by_value(table, 0.16) == (None, None)
    assert locate_by_value(table, 0.16, row_label="Ingreso mensual per capita") == (0, 1)
    assert locate_by_value(table, 0.16, row_label="Ingreso mensual del participante") == (1, 1)
    # A label that names neither row cannot create an address.
    assert locate_by_value(table, 0.16, row_label="Something else") == (None, None)
