"""The bounded second pass: which units it reads, and how its rows merge back."""

import json

from src.extraction.second_pass import MAX_UNITS, mentions, merge_rows, select_units

CONTENT = [
    {"type": "title", "page_idx": 0, "text": "Long-term effects of the targeting the ultra poor program"},
    {"type": "text", "page_idx": 3, "text": "Household expenditure rose, and consumption per adult equivalent was 2.40."},
    {"type": "table", "page_idx": 4, "text": "| Outcome | Coef |\n| --- | --- |\n| Expenditure | 0.11*** |"},
    {"type": "table", "page_idx": 5, "text": "| Outcome | Coef |\n| --- | --- |\n| Schooling | 0.02 |"},
]


def test_a_missing_outcome_is_matched_by_its_words():
    assert mentions("Monthly household expenditure per adult", ["Household expenditure"]) == ["Household expenditure"]
    assert mentions("Schooling enrolment", ["Household expenditure"]) == []
    assert mentions("anything", ["the"]) == []


def test_only_the_units_that_mention_a_missing_outcome_are_selected():
    selected = select_units(CONTENT, ["Household expenditure", "Consumption"])
    assert [u["page"] for u in selected["tables"]] == [5]
    assert [u["page"] for u in selected["texts"]] == [4]
    assert selected["texts"][0]["text"].startswith("Household expenditure rose")


def test_nothing_is_selected_when_nothing_matches():
    selected = select_units(CONTENT, ["Fisheries revenue"])
    assert selected == {"tables": [], "texts": []}


def test_the_selection_is_capped():
    listed = [{"type": "table", "page_idx": i, "text": "| Outcome | Coef |\n| --- | --- |\n| Expenditure | 1*** |"}
              for i in range(20)]
    assert len(select_units(listed, ["Expenditure"])["tables"]) == MAX_UNITS


def test_a_second_read_is_merged_and_only_fills_gaps():
    rows = [{"outcome_name": "Expenditure", "treatment_arm": "Half", "effect_size": 107.0,
             "standard_error": None, "page": 9}]
    extra = [{"outcome_name": "Expenditure", "treatment_arm": "Half", "effect_size": 107.0,
              "standard_error": 148.0, "page": 9},
             {"outcome_name": "Expenditure", "treatment_arm": "Half", "effect_size": 206.0,
              "standard_error": 116.0, "page": 9}]
    merged, added = merge_rows(rows, extra)
    assert added == 1 and len(merged) == 2
    assert merged[0]["standard_error"] == 148.0
    assert merged[1]["effect_size"] == 206.0


def test_merge_keeps_a_row_that_differs_in_arm():
    rows = [{"outcome_name": "Expenditure", "treatment_arm": "Half", "effect_size": 107.0}]
    merged, added = merge_rows(rows, [{"outcome_name": "Expenditure", "treatment_arm": "Full",
                                       "effect_size": 107.0}])
    assert added == 1 and len(merged) == 2
    assert json.dumps(merged).count("107.0") == 2
