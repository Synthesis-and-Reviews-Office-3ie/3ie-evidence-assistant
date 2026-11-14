"""Confirming the paper's stated outcomes against the extracted rows."""

from src.extraction.outcome_confirmation import missing_outcomes

CONFIRMATION = {
    "primary": [{"name": "Household consumption", "quote": "consumption rose"}],
    "secondary": [{"name": "Income", "quote": "income"}, {"name": "School enrolment", "quote": "enrolment"}],
}


def test_outcomes_present_in_the_extraction_are_not_flagged():
    misses = missing_outcomes(CONFIRMATION, ["Total household consumption", "Monthly income"])
    assert [m["name"] for m in misses] == ["School enrolment"]


def test_an_outcome_absent_from_the_extraction_is_flagged_with_its_role():
    misses = missing_outcomes(CONFIRMATION, ["Total household consumption"])
    assert {m["name"] for m in misses} == {"Income", "School enrolment"}
    assert misses[0]["role"] == "secondary"


def test_nothing_confirmed_means_nothing_flagged():
    assert missing_outcomes({}, ["Consumption"]) == []


def test_an_unrelated_extraction_flags_every_confirmed_outcome():
    misses = missing_outcomes(CONFIRMATION, ["Height", "Weight"])
    assert len(misses) == 3


def test_a_longer_extracted_label_contains_the_confirmed_outcome():
    misses = missing_outcomes(
        {"primary": [{"name": "Poultry ownership"}]},
        ["Poultry ownership among cash transfer recipients"])
    assert misses == []
