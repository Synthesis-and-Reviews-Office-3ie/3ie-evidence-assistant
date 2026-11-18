"""Tests for the canonical outcome taxonomy."""

from evaluation.outcome_taxonomy import categories, is_noise


def test_consumption_and_income_both_found_in_a_compound_label():
    cats = categories("Household consumption and income")
    assert "consumption" in cats and "income" in cats


def test_food_expenditure_is_food_security_not_general_consumption():
    cats = categories("Per capita food expenditure (per day)")
    assert "food_security" in cats


def test_poverty_headcount_is_poverty():
    assert "poverty" in categories("Poverty headcount rate (below $2.15 poverty line)")


def test_livestock_asset_value_hits_livestock_and_assets():
    cats = categories("Livestock asset value (USD)")
    assert "livestock" in cats


def test_bare_number_is_noise():
    assert is_noise("(0.038)")
    assert categories("(0.038)") == {"noise"}


def test_unknown_words_fall_back_to_other():
    assert categories("Zzz qqq") == {"other"}
