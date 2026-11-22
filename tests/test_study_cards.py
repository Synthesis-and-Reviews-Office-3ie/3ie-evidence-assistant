"""The study card: shape, table roles, the lists the reader may choose from."""

from __future__ import annotations

from src.extraction.study_cards import (
    build_card,
    card_lists,
    document_text,
    empty_card,
    normalise_card,
    role_of_table,
)


def test_document_text_takes_the_title_and_running_text():
    content = [{"type": "title", "text": "Assets and wellbeing"},
               {"type": "text", "text": "We randomised 5,000 households."},
               {"type": "table", "text": "| a | b |"}]
    title, text = document_text(content)
    assert title == "Assets and wellbeing"
    assert "randomised 5,000" in text and "| a | b |" not in text


def test_normalise_card_keeps_the_reader_fields_and_shapes():
    card = {"methods": ["difference-in-differences", ""], "arms": ["grants only", "control"],
            "rounds": [{"name": "round 1", "dates": "2005"}, "junk"],
            "comparison_group": "control", "sign_conventions": ["benefit (A-B) is control minus program"],
            "populations": ["other poor women"],
            "tables": [{"label": "Table 2", "page": 8, "role": "Main Effect",
                        "evidence": {"page": 8, "quote": "x"}}, "junk"],
            "evidence": {"methods": {"page": 3, "quote": "we use DiD"}}, "extra": 1}
    out = normalise_card(card)
    assert out["methods"] == ["difference-in-differences"]
    assert out["comparison_group"] == "control"
    assert out["rounds"] == [{"name": "round 1", "dates": "2005"}]
    assert out["tables"][0]["role"] == "main effect"
    assert "extra" not in out


def test_role_of_table_matches_by_page_then_by_label():
    card = normalise_card({"tables": [{"label": "Table 4. Impacts", "page": 12, "role": "main effect"},
                                      {"label": "Table 5. Balance", "page": 3, "role": "balance"}]})
    assert role_of_table(card, 12) == "main effect"
    assert role_of_table(card, None, "Table 5") == "balance"
    assert role_of_table(card, 99, "unknown") == ""


def test_card_lists_gives_arms_time_points_and_populations():
    card = normalise_card({"arms": ["grants only"], "comparison_group": "control",
                           "rounds": [{"name": "baseline", "since_baseline": "0 years"},
                                      {"name": "endline", "since_baseline": "after 2 years"}],
                           "populations": ["other poor women"]})
    lists = card_lists(card)
    assert "grants only" in lists["arms"] and "control" in lists["arms"]
    assert "after 2 years" in lists["time_points"] and "endline" in lists["time_points"]
    assert lists["populations"] == ["other poor women"]


def test_empty_card_on_a_failed_call(monkeypatch):
    import asyncio

    import httpx

    class FakeClient:
        async def post(self, *a, **k):
            raise httpx.ConnectError("boom")

    card = asyncio.run(build_card(FakeClient(), "m", "t", "text"))
    assert card == empty_card()
