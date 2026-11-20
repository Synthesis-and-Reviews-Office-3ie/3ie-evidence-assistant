"""The deterministic arm repair."""

from evaluation.arm_fix import fixed_arm


def test_an_arm_that_repeats_the_header_comes_from_the_row():
    assert fixed_arm("GVAO (IHST)", "(2) GVAO (IHST)", "Intensive Extension in Phase 1",
                     "(2) GVAO (IHST)") == "Intensive Extension in Phase 1"


def test_an_arm_that_repeats_the_outcome_comes_from_the_row():
    assert fixed_arm("Beds", "Beds", "T1: Ind. coaching + asset", "Treatment impact") == \
        "T1: Ind. coaching + asset"


def test_an_arm_with_no_role_row_uses_the_panel():
    assert fixed_arm("X", "X", "", "X", "Panel B") == "Panel B"


def test_a_subgroup_row_does_not_become_the_arm():
    assert fixed_arm("Delta Jobs", "Hierarchy 5 - Diff", "Industry", "Hierarchy 5 - Diff") == \
        "Hierarchy 5 - Diff"


def test_an_arm_that_is_already_distinct_is_unchanged():
    assert fixed_arm("Beds", "T1", "Beds", "Treatment impact") == "T1"


def test_an_outcome_that_is_the_row_is_not_copied_to_the_arm():
    assert fixed_arm("ITT w1-w2 * Saturation", "Savings ($PPP)", "ITT w1-w2 * Saturation",
                     "Savings ($PPP)") == "Savings ($PPP)"
