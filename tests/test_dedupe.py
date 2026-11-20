"""The deterministic keeper for duplicate rows at one printed cell."""

from evaluation.dedupe import keeper


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
