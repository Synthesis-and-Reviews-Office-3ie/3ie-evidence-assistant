"""Tests for rendering parser tables to the Markdown form the extractor reads."""

from src.extraction.table_rules import html_table_to_markdown, normalise_tables


def test_html_table_becomes_pipe_table():
    html = (
        "<table><tr><th>Outcome</th><th>Coefficient</th><th>SE</th></tr>"
        "<tr><td>Consumption</td><td>0.15</td><td>(0.05)</td></tr></table>"
    )
    md = html_table_to_markdown(html)
    assert md.splitlines()[0] == "| Outcome | Coefficient | SE |"
    assert "| --- | --- | --- |" in md
    assert "| Consumption | 0.15 | (0.05) |" in md


def test_colspan_pads_the_row():
    html = "<table><tr><td colspan=2>Header</td><td>X</td></tr><tr><td>a</td><td>b</td><td>c</td></tr></table>"
    md = html_table_to_markdown(html)
    assert "| Header |  | X |" in md


def test_pipes_in_cells_are_escaped():
    html = "<table><tr><th>Outcome</th></tr><tr><td>income | consumption</td></tr></table>"
    assert "income \\| consumption" in html_table_to_markdown(html)


def test_normalise_renders_mineru_html_but_leaves_docling_markdown():
    mineru = {"type": "table", "text": "", "table_body": "<table><tr><td>a</td><td>1</td></tr></table>"}
    docling = {"type": "table", "text": "| a | 1 |\n| --- | --- |"}
    out = normalise_tables([mineru, docling])
    assert out[0]["text"].startswith("| a | 1 |")
    assert out[1]["text"] == docling["text"]


def test_empty_html_returns_empty_string():
    assert html_table_to_markdown("") == ""
