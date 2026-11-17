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
