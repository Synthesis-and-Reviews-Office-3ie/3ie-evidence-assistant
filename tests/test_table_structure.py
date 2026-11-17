"""Table structure interpretation: roles, notes, consistency, and multi-page stitching."""

from src.extraction.table_structure import (carry_merged_labels, 
    ESTIMATE, LAYOUT_ROWS, SE,
    estimate_columns, interpret_table, parse_conventions, parse_markdown_table,
    split_estimate_columns, stitch_units,
)

WIDE_TABLE = """| Outcome | Year8*Treatment | Year8*Control | Pooled |
| --- | --- | --- | --- |
| Cash savings (BDT) | 278*** (3.40) | -10 (-0.00) | 1664*** (10.57) |
| Outstanding loan (BDT) | -153** (-2.23) | 196*** (5.67) | 1532*** (10.45) |"""

TABLE_SE = """| Coefficient | SE | p-value |
| --- | --- | --- |
| 0.52 | 0.12 | 0.001 |
| 0.31 | 0.10 | 0.010 |"""

TABLE_CI = """| Coef | 95% CI lower | 95% CI upper |
| --- | --- | --- |
| 0.52 | 0.29 | 0.75 |
| 0.31 | 0.11 | 0.51 |"""


def test_header_roles_for_a_plain_results_table():
    result = interpret_table(TABLE_SE)
    assert result.estimate == 0
    assert result.se == 1
    assert result.p == 2
    assert result.confidence >= 0.6


def test_outcomes_in_columns_with_combined_cells():
    table = """| | (1) Consumption | (2) Food security |
| --- | --- | --- |
| T1: Grp LH | 311** (119) | 0.20*** (0.05) |
| T2: Ind LH | [0.01] 342*** | [<0.01] 0.26*** |"""
    result = interpret_table(table)
    assert result.estimate is not None


def test_treatment_row_with_a_parenthesised_se_row():
    table = """| | Bridging | Linking |
| --- | --- | --- |
| Treatment | -0.01 | 0.45*** |
| | (0.05) | (0.05) |
| Control mean | 2.26 | 1.10 |"""
    result = interpret_table(table)
    assert result.layout == LAYOUT_ROWS
    assert result.row_roles.get(ESTIMATE) == 0
    assert result.row_roles.get(SE) == 1


def test_method_blocks_are_detected():
    table = """| | No adjustment - coef. | No adjustment - s.e. | Matching - coef. | Matching - s.e. |
| --- | --- | --- | --- | --- |
| Africare | -0.67 | 0.33 | -0.59 | 0.53 |
| Age | -0.06 | 0.01 | -0.05 | 0.01 |"""
    result = interpret_table(table)
    assert result.stat_blocks == ["No adjustment", "Matching"]


def test_outcome_columns_with_arms_and_se_rows():
    table = """| | Tot | Food |
| --- | --- | --- |
| TUP*2014 | -0.10 | 0.01 |
| | (0.09) | (0.04) |
| TUP*2015 | 0.03 | 0.05 |
| | (0.09) | (0.04) |"""
    result = interpret_table(table)
    assert result.outcome_columns == ["Tot", "Food"]


def test_statistics_in_rows_with_outcomes_in_columns():
    table = """| | (1) | (2) |
| --- | --- | --- |
| Coefficient | 0.52 | 0.31 |
| Standard error | 0.12 | 0.10 |
| Observations | 400 | 400 |"""
    result = interpret_table(table)
    assert result.layout == LAYOUT_ROWS
    assert result.row_roles.get(ESTIMATE) == 0
    assert result.row_roles.get(SE) == 1


def test_spanish_headers_are_read():
    table = """| Efecto | Error estándar | Valor p |
| --- | --- | --- |
| 0.52 | 0.12 | 0.001 |"""
    result = interpret_table(table)
    assert result.estimate == 0
    assert result.se == 1
    assert result.p == 2


def test_header_abbreviations_are_expanded():
    table = """| ATT | s.e. | Obs |
| --- | --- | --- |
| 0.52 | 0.12 | 400 |
| 0.41 | 0.10 | 400 |"""
    result = interpret_table(table)
    assert result.estimate == 0
    assert result.se == 1
    assert any(c.role == "n" for c in result.roles)


def test_confidence_interval_columns():
    result = interpret_table(TABLE_CI)
    assert result.estimate == 0
    assert result.ci_low == 1
    assert result.ci_high == 2


def test_notes_set_the_conventions_and_star_map():
    conventions, stars = parse_conventions(
        "Standard errors in parentheses. *** p<0.01, ** p<0.05, * p<0.1. Clustered at village level.")
    assert conventions["se_in_parens"] and conventions["clustered"]
    assert stars == {3: 0.01, 2: 0.05, 1: 0.1}


def test_combined_estimate_and_se_cell_is_flagged():
    table = """| Estimate |
| --- |
| 0.52*** (0.12) |
| 0.31** (0.10) |"""
    result = interpret_table(table, notes="Standard errors in parentheses")
    assert result.estimate == 0
    assert result.combined is True


def test_consistency_finds_an_unlabelled_se_column():
    table = """| Coef | A | B |
| --- | --- | --- |
| 0.50 | 0.10 | 5.00 |
| 0.60 | 0.20 | 3.00 |
| 0.40 | 0.05 | 8.00 |"""
    result = interpret_table(table)
    roles = {c.index: c.role for c in result.roles}
    assert roles[0] == ESTIMATE
    assert roles[1] == SE  # estimate / 0.1 is a whole ratio, estimate / 5 is not


def test_unknown_table_warns_rather_than_guessing():
    table = """| Region | Note |
| --- | --- |
| North | high |
| South | low |"""
    result = interpret_table(table)
    assert result.estimate is None
    assert any("no estimate" in w for w in result.warnings)


def test_separator_rows_are_not_body_rows():
    grid = parse_markdown_table(TABLE_SE)
    assert len(grid.body) == 2
    assert grid.headers[-1][0].lower().startswith("coefficient")


def test_continuation_on_the_next_page_is_stitched():
    units = [
        {"page": 3, "caption": "Table 4. Impacts on consumption",
         "text": "| Outcome | Coef | SE |\n| --- | --- | --- |\n| Food | 0.52 | 0.12 |"},
        {"page": 4, "caption": "Table 4. Impacts on consumption (continued)",
         "text": "| Outcome | Coef | SE |\n| --- | --- | --- |\n| Assets | 0.31 | 0.10 |"},
    ]
    merged = stitch_units(units)
    assert len(merged) == 1
    assert merged[0]["page"] == 3
    assert merged[0]["page_end"] == 4
    assert "Food" in merged[0]["text"] and "Assets" in merged[0]["text"]


def test_a_new_table_on_the_next_page_is_not_stitched():
    units = [
        {"page": 3, "caption": "Table 4", "text": "| A | B |\n| --- | --- |\n| 1 | 2 |"},
        {"page": 4, "caption": "Table 5", "text": "| X | Y |\n| --- | --- |\n| 3 | 4 |"},
    ]
    assert len(stitch_units(units)) == 2


def test_a_wide_table_becomes_one_view_per_estimate_column():
    split = split_estimate_columns(WIDE_TABLE)
    assert [entry["header"] for entry in split] == ["Year8*Treatment", "Year8*Control", "Pooled"]
    first = split[0]["text"].splitlines()
    assert first[0] == "| Outcome | Year8*Treatment |"
    assert "| Cash savings (BDT) | 278*** (3.40) |" in first
    assert "1664" not in split[0]["text"]


def test_the_standard_error_column_is_not_a_view():
    table = """| Outcome | Coef | SE |
| --- | --- | --- |
| Income | 0.52*** | (0.12) |
| Assets | 0.31*** | (0.10) |"""
    assert estimate_columns(parse_markdown_table(table)) == [1]
    assert split_estimate_columns(table) == []


def test_a_table_with_one_estimate_column_is_read_whole():
    assert split_estimate_columns(TABLE_SE) == []


CONTINUATION_TABLE = """| Cash savings (BDT) | 278*** (3.40) | -10 (-0.00) | 1664*** (10.57) |
| --- | --- | --- | --- |
| Outstanding loan (BDT) | -153** (-2.23) | 196*** (5.67) | 1532*** (10.45) |"""

GROUPED_TABLE = """| | (1) | (2) | (3) |
| --- | --- | --- | --- |
| | Panel regression results (equation 1) | Panel regression results (equation 1) | Cross-sectional results |
| Cash savings (BDT) | 278*** (3.40) | 1664*** (10.57) | -10 (-0.00) |"""


def test_a_continuation_table_names_its_columns_by_position():
    split = split_estimate_columns(CONTINUATION_TABLE)
    assert [entry["header"] for entry in split] == ["column 1", "column 2", "column 3"]
    assert "278*** (3.40)" in split[0]["text"]
    assert "1664" not in split[0]["text"]


def test_a_grouped_header_keeps_the_group_number():
    split = split_estimate_columns(GROUPED_TABLE)
    assert split[0]["header"] != split[1]["header"]
    assert split[0]["header"].startswith("(1)") and split[1]["header"].startswith("(2)")
    assert "1664" in split[1]["text"] and "1664" not in split[0]["text"]


def test_a_column_labelled_as_a_statistic_is_not_a_view():
    table = """| Outcome | Coef | t-stat | p |
| --- | --- | --- | --- |
| Income | 0.52*** | 4.31 | 0.001 |
| Assets | 0.31*** | 3.02 | 0.010 |"""
    assert estimate_columns(parse_markdown_table(table)) == [1]


def test_a_column_of_unstarred_estimates_with_t_statistics_is_a_view():
    table = """| Outcome | (1) | (2) |
| --- | --- | --- |
| Income | 936* (1.67) | -398 (-0.82) |
| Consumption | 0.66*** (5.11) | 0.03 (0.20) |"""
    assert estimate_columns(parse_markdown_table(table)) == [1, 2]
    split = split_estimate_columns(table)
    assert len(split) == 2 and "-398" in split[1]["text"]


def test_a_bound_header_that_mentions_sd_is_still_a_view():
    table = """| Outcome | Lower Bounds - (2) - 0.25 SD | (3) - 0.1 SD |
| --- | --- | --- |
| Income | 220.27*** (58.19) | -29.08 (342.90) |"""
    assert estimate_columns(parse_markdown_table(table)) == [1, 2]


def test_stars_in_the_next_column_still_make_a_view():
    table = """| Outcome | Estimate | | Estimate | |
| --- | --- | --- | --- | --- |
| Cereals | 71.6 | ** | 83.2 | * |
| Tubers | 2.7 | | 3.2 | |"""
    columns = estimate_columns(parse_markdown_table(table))
    assert columns == [1, 3]
    split = split_estimate_columns(table)
    assert len(split) == 2
    assert "71.6 **" in split[0]["text"] or "71.6**" in split[0]["text"]


MERGED = """| Outcome | Coef |
| --- | --- |
| Cash savings | 0.11*** |
|  | 0.12*** |
|  | (0.03) |"""


def test_a_merged_label_is_carried_onto_the_rows_it_covers():
    out = carry_merged_labels(MERGED)
    lines = out.splitlines()
    assert lines[2] == "| Cash savings | 0.11*** |"
    assert lines[3] == "| Cash savings | 0.12*** |"
    assert lines[4] == "|  | (0.03) |"


def test_a_table_without_merged_labels_is_unchanged():
    table = "| Outcome | Coef |\n| --- | --- |\n| A | 0.1*** |\n| B | 0.2*** |"
    assert carry_merged_labels(table) == table


def test_the_split_uses_the_carried_label():
    split = split_estimate_columns(carry_merged_labels(MERGED))
    assert split == []
    filled = carry_merged_labels("| Outcome | (1) | (2) |\n| --- | --- | --- |\n| Savings | 0.1*** | 0.2*** |\n|  | 0.3*** | 0.4*** |")
    views = split_estimate_columns(filled)
    assert len(views) == 2 and "Savings" in views[0]["text"] and views[0]["text"].count("Savings") == 2
