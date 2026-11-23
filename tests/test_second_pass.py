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


def test_the_second_pass_prompt_has_every_format_key(monkeypatch):
    # Regression: the shared PROMPT gained {card} and {examples}; the second pass formatted it without
    # those keys and raised KeyError('card') on every document, losing its rows.
    import asyncio

    import src.extraction.table_estimates as module
    from src.extraction.second_pass import run_second_pass

    async def fake_chat(client, model, prompt):
        assert "{card}" not in prompt and "{examples}" not in prompt
        return json.dumps({"results_table": True, "table_label": "Table 1", "estimates": [
            {"outcome": "Expenditure", "estimate_cell": "0.11***", "row_number": 1, "column_number": 2,
             "row_label": "Expenditure", "outcome_row": 3, "outcome_column": 1}]})

    monkeypatch.setattr(module, "_chat", fake_chat)
    out = asyncio.run(run_second_pass(CONTENT, ["Expenditure"], "m", "k"))
    assert out["estimates"] and out["estimates"][0]["effect_size"] == 0.11


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


def test_a_missing_address_is_filled_from_the_other_read():
    current = {"outcome_name": "Expenditure", "treatment_arm": "Half", "effect_size": 107.0,
               "unit_index": None}
    extra = {"outcome_name": "Expenditure", "treatment_arm": "Half", "effect_size": 107.0,
             "unit_index": 7, "cell_row": 1, "cell_column": 2}
    merged, added = merge_rows([current], [extra])
    assert added == 0 and merged[0]["unit_index"] == 7 and merged[0]["cell_column"] == 2


def test_an_existing_address_is_not_overwritten():
    current = {"outcome_name": "Expenditure", "treatment_arm": "Half", "effect_size": 107.0,
               "unit_index": 3, "cell_row": 0, "cell_column": 1}
    extra = {"outcome_name": "Expenditure", "treatment_arm": "Half", "effect_size": 107.0,
             "unit_index": 7, "cell_row": 4, "cell_column": 5}
    merged, _ = merge_rows([current], [extra])
    assert merged[0]["unit_index"] == 3 and merged[0]["cell_column"] == 1


def test_a_second_pass_error_is_checked_against_the_cell():
    from src.extraction.second_pass import _finalise
    from src.extraction.table_estimates import table_units, to_estimate

    content = [{"type": "table", "page_idx": 0, "text":
                "| Outcome | Coef |\n| --- | --- |\n| Income | 0.391** |\n|  | (0.160) |"}]
    units = table_units(content)
    e = to_estimate({"outcome": "Income", "estimate_cell": "0.391**", "se_cell": "",
                     "row_number": 1, "column_number": 2},
                    "Table 1", units[0]["page"], units[0]["text"], unit_index=units[0]["unit_index"])
    e.standard_error = 0.160          # printed in the row below, not named by the model
    _finalise([e], content)
    assert e.standard_error == 0.160 and (e.se_row, e.se_column) == (1, 1)


def test_a_second_pass_error_not_printed_anywhere_is_dropped():
    from src.extraction.second_pass import _finalise
    from src.extraction.table_estimates import table_units, to_estimate

    content = [{"type": "table", "page_idx": 0, "text":
                "| Outcome | Coef |\n| --- | --- |\n| Income | 0.391** |\n| Assets | 0.400** |"}]
    units = table_units(content)
    e = to_estimate({"outcome": "Income", "estimate_cell": "0.391**", "se_cell": "",
                     "row_number": 1, "column_number": 2},
                    "Table 1", units[0]["page"], units[0]["text"], unit_index=units[0]["unit_index"])
    e.standard_error = 0.160
    _finalise([e], content)
    assert e.standard_error is None
