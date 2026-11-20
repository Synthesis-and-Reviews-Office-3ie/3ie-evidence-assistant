"""The deterministic keeper for duplicate rows at one printed cell."""

from evaluation.dedupe import combined_labels, keeper


def test_keeper_prefers_the_row_with_a_standard_error():
    rows = [{"id": "a", "standard_error": None, "treatment_arm": "arm", "outcome_name": "Long outcome"},
            {"id": "b", "standard_error": 0.1, "treatment_arm": "", "outcome_name": "Y"}]
    assert keeper(rows)["id"] == "b"


def test_keeper_prefers_an_arm_before_the_outcome_length():
    rows = [{"id": "b", "standard_error": None, "treatment_arm": "", "outcome_name": "Long outcome"},
            {"id": "a", "standard_error": None, "treatment_arm": "arm", "outcome_name": "Short"}]
    assert keeper(rows)["id"] == "a"


def test_keeper_prefers_the_longer_outcome_and_then_the_lowest_id():
    rows = [{"id": "b", "standard_error": None, "treatment_arm": "arm", "outcome_name": "Long outcome"},
            {"id": "a", "standard_error": None, "treatment_arm": "arm", "outcome_name": "Short"}]
    assert keeper(rows)["id"] == "b"
    rows = [{"id": "b", "standard_error": None, "treatment_arm": "arm", "outcome_name": "Same"},
            {"id": "a", "standard_error": None, "treatment_arm": "arm", "outcome_name": "Same"}]
    assert keeper(rows)["id"] == "a"


def test_combined_labels_keeps_the_table_subject_and_the_subgroup():
    assert combined_labels(["Delta Jobs", "Industry"]) == "Delta Jobs - Industry"


def test_combined_labels_drops_a_label_contained_in_a_longer_one():
    assert combined_labels(["% of households: With outstanding loan in kind",
                            "With outstanding loan in kind"]) == \
        "% of households: With outstanding loan in kind"


def test_combined_labels_deduplicates_identical_labels():
    assert combined_labels(["Same", "Same"]) == "Same"
    assert combined_labels([]) == ""
