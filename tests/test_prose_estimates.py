"""Prose extraction for table-free documents (src/extraction/prose_estimates.py)."""

from src.extraction.prose_estimates import build_rows, page_for_quote, quote_in_text

TEXT = ("Poultry ownership rose by 4 percentage points among treated households. "
        "Women's savings increased by 12 percent in the treatment group.")

CONTENT = [
    {"type": "title", "page_idx": 0, "text": "SPIR learning brief"},
    {"type": "text", "page_idx": 2, "text": "Poultry ownership rose by 4 percentage points among treated households."},
    {"type": "text", "page_idx": 3, "text": "Women's savings increased by 12 percent in the treatment group."},
]

DOC = {"id": "doc-1", "filename": "brief.pdf"}


def test_a_grounded_sentence_becomes_a_row():
    data = {"estimates": [{"outcome": "Poultry ownership", "arm": "treatment",
                           "quote": "Poultry ownership rose by 4 percentage points among treated households.",
                           "effect": 4, "effect_unit": "percentage points"}]}
    rows = build_rows("proj", DOC, CONTENT, TEXT, data, "model")
    assert len(rows) == 1
    assert rows[0]["effect_size"] == 4 and rows[0]["page"] == 3
    assert rows[0]["extraction_method"].endswith("prose")


def test_an_ungrounded_quote_is_dropped():
    data = {"estimates": [{"outcome": "Income", "quote": "Income doubled everywhere overnight.", "effect": 100}]}
    assert build_rows("proj", DOC, CONTENT, TEXT, data, "model") == []


def test_a_missing_number_is_dropped():
    data = {"estimates": [{"outcome": "Poultry", "quote": "Poultry ownership rose by 4 percentage points among treated households."}]}
    assert build_rows("proj", DOC, CONTENT, TEXT, data, "model") == []


def test_quote_helpers():
    quote = "Women's savings increased by 12 percent in the treatment group."
    assert quote_in_text(quote, TEXT)
    assert page_for_quote(quote, CONTENT) == 4
    assert not quote_in_text("A sentence absent from the paper.", TEXT)
