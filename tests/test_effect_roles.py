"""The two-axis role decision: it labels both axes and fails open, dropping nothing on its own."""

from __future__ import annotations

from src.extraction.effect_roles import (
    BEFORE,
    CONTROL,
    DROP_ROLES,
    FIXED_EFFECT,
    NOT_AN_EFFECT,
    OUTCOME,
    PROGRAMME_EFFECT,
    build_prompt,
    keep_effect,
    match_role,
    parse_roles,
    role_for_cell,
)


def test_keep_effect_accepts_a_programme_effect_cell():
    assert keep_effect(OUTCOME, PROGRAMME_EFFECT)
    assert keep_effect(PROGRAMME_EFFECT, OUTCOME)


def test_keep_effect_fails_open_on_empty_or_unknown_roles():
    assert keep_effect("", "")
    assert keep_effect("outcome", "")
    assert keep_effect("something_new", "outcome")
    assert not DROP_ROLES & {"programme_effect", "outcome", "something_new"}


def test_keep_effect_drops_when_an_axis_is_a_non_effect_role():
    for role in (CONTROL, FIXED_EFFECT, BEFORE, NOT_AN_EFFECT):
        assert not keep_effect(role, OUTCOME)
        assert not keep_effect(OUTCOME, role)


def test_keep_effect_is_case_and_space_insensitive():
    assert not keep_effect(" Control_Or_Covariate ", OUTCOME)


def test_match_role_exact_then_containment_then_overlap():
    roles = {"sup 2002": CONTROL, "owned land cultivable land": OUTCOME,
             "tup impact 2005 over 2002": PROGRAMME_EFFECT}
    assert match_role(roles, "SUP 2002") == CONTROL
    assert match_role(roles, "  sup   2002 ") == CONTROL
    assert match_role(roles, "Owned land/ cultivable land") == OUTCOME
    assert match_role(roles, "TUP Impact - 2005 over 2002") == PROGRAMME_EFFECT


def test_match_role_returns_empty_for_no_match():
    assert match_role({"a b c": OUTCOME}, "") == ""
    assert match_role({}, "anything") == ""
    assert match_role({"alpha beta": OUTCOME}, "zeta") == ""


def test_parse_roles_tolerates_a_missing_or_malformed_axis():
    assert parse_roles({"rows": {"x": OUTCOME}, "columns": {"y": PROGRAMME_EFFECT}}) == \
        {"rows": {"x": OUTCOME}, "columns": {"y": PROGRAMME_EFFECT}}
    assert parse_roles({"rows": {"x": OUTCOME}}) == {"rows": {"x": OUTCOME}, "columns": {}}
    assert parse_roles({"rows": "nope", "columns": None}) == {"rows": {}, "columns": {}}
    assert parse_roles(None) == {"rows": {}, "columns": {}}


def test_role_for_cell_keeps_a_programme_effect_and_drops_a_control_column():
    roles = {"rows": {"Farm work": OUTCOME, "Control mean": CONTROL},
             "columns": {"TUP vs control": PROGRAMME_EFFECT, "Baseline": BEFORE}}
    assert role_for_cell(roles, "Farm work", "TUP vs control") == \
        (OUTCOME, PROGRAMME_EFFECT, True)
    assert role_for_cell(roles, "Farm work", "Baseline")[2] is False
    assert role_for_cell(roles, "Control mean", "TUP vs control")[2] is False


def test_role_for_cell_fails_open_when_labels_are_unmatched():
    assert role_for_cell({"rows": {}, "columns": {}}, "Whatever", "Anything") == ("", "", True)


def test_build_prompt_is_text_without_an_image_and_multimodal_with_one():
    text = build_prompt("Table 3. Consumption", ["Consumption"], ["TUP vs control"], "| a | b |")
    assert isinstance(text, str)
    assert "Table 3. Consumption" in text
    assert "Consumption" in text
    parts = build_prompt("cap", ["r"], ["c"], "| a |", page_image="data:image/png;base64,AAAA")
    assert isinstance(parts, list) and parts[1]["type"] == "image_url"
