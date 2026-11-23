"""Card and gallery context: tagging, entry selection, allowed labels."""

from __future__ import annotations

from src.extraction.reader_context import (
    card_block,
    entry_text,
    examples_block,
    on_card,
    pick_entries,
    table_tags,
    validate_labels,
)

CARD = {"arms": ["grants only", "hybrid", "control"], "comparison_group": "control",
        "rounds": [{"name": "baseline", "since_baseline": "0 years"},
                   {"name": "endline", "since_baseline": "after 2 years"}],
        "populations": ["other poor women"],
        "sign_conventions": [{"convention": "treatment minus control", "evidence": {}}]}

ENTRIES = [
    {"id": "did", "tags": {"method": ["DiD and triple differences"], "format": ["coefficient"],
                           "layout": ["several rounds"]}},
    {"id": "or", "tags": {"method": ["RCT (ITT, TOT/LATE, ANCOVA)"],
                          "format": ["odds ratio, risk ratio, hazard ratio"], "layout": []}},
    {"id": "pval", "tags": {"method": ["RCT (ITT, TOT/LATE, ANCOVA)"], "format": ["coefficient"],
                            "layout": ["p-values in their own column"]}},
]


def test_table_tags_reads_method_and_layout_from_the_table():
    tags = table_tags("Table 4. Difference-in-differences estimates", "| Coef. | p-value |\n| 0.2*** | 0.01 |")
    assert "DiD and triple differences" in tags["method"]
    assert "p-values in their own column" in tags["layout"]


def test_table_tags_defaults_the_format_to_a_coefficient():
    assert table_tags("Table 1", "| a | b |\n| 1 | 2 |")["format"] == ["coefficient"]


def test_pick_entries_ranks_by_shared_tags():
    selected = pick_entries({"method": ["DiD and triple differences"], "format": ["coefficient"],
                             "layout": ["several rounds"]}, ENTRIES)
    assert selected[0]["id"] == "did"


def test_card_block_lists_arms_rounds_and_populations():
    text = card_block(CARD)
    assert "grants only" in text and "hybrid" in text
    assert "after 2 years" in text
    assert "other poor women" in text
    assert "treatment minus control" in text


def test_on_card_accepts_a_listed_label_and_rejects_another():
    assert on_card("Grants only", CARD["arms"])
    assert not on_card("blanket grants", CARD["arms"])


def test_an_arm_not_on_the_card_is_marked_not_on_card():
    row = {"arm": "some unlisted arm", "time_point": "after 2 years", "subgroup_or_population": "other poor women"}
    changed = validate_labels(row, CARD)
    assert row["arm"] == "not on card" and "arm" in changed
    assert row["time_point"] == "after 2 years"
    assert row["subgroup_or_population"] == "other poor women"


def test_entry_text_shows_stored_rows_not_stored_and_rule():
    entry = {"id": "x", "snippet": "| Outcome | Coef |", "rule": "A rule.",
             "stored_rows": [{"outcome": "Income", "value": 1.2, "effect_type": "main"}],
             "not_stored": [{"cell": "Controls", "reason": "covariates"}]}
    text = entry_text(entry)
    assert "Income" in text and "covariates" in text and "A rule." in text
    assert examples_block([entry]) == text
