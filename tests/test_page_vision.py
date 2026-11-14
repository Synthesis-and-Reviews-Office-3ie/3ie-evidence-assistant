"""Image-table fallback: page selection, rendering and row building (src/extraction/page_vision.py)."""

import pytest

from src.extraction.page_vision import build_rows, render_page_png, table_image_pages

DOC = {"id": "doc-1", "filename": "paper.pdf"}


def test_image_pages_are_one_based_deduplicated_and_sorted():
    content = [
        {"type": "image", "page_idx": "6", "text": "FIGURE 1"},
        {"type": "image", "page_idx": 7, "text": "FIGURE 2"},
        {"type": "image", "page_idx": 7, "text": "FIGURE 3"},
        {"type": "text", "page_idx": 9},
        {"type": "image"},
    ]
    assert table_image_pages(content) == [7, 8]


def test_image_pages_are_capped():
    content = [{"type": "image", "page_idx": i} for i in range(40)]
    assert len(table_image_pages(content, max_pages=5)) == 5


def _tiny_pdf() -> bytes:
    pymupdf = pytest.importorskip("pymupdf")
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "0.15*** (0.05)")
    data = document.tobytes()
    document.close()
    return data


def test_a_page_renders_to_png():
    png = render_page_png(_tiny_pdf(), 1, dpi=100)
    assert png.startswith(b"\x89PNG")


def test_an_out_of_range_page_is_rejected():
    with pytest.raises(ValueError):
        render_page_png(_tiny_pdf(), 99)


def test_rows_are_built_from_the_model_output():
    data = {"results_table": True, "table_label": "Table 4. Impacts",
            "estimates": [{"outcome": "Total income", "arm": "T1", "estimate_cell": "0.15*** (0.05)",
                           "coefficient": 0.15, "standard_error": 0.05, "stars": 3}]}
    rows = build_rows("proj", DOC, 7, data, "vision-model")
    assert len(rows) == 1
    row = rows[0]
    assert row["effect_size"] == 0.15 and row["standard_error"] == 0.05
    assert row["outcome_name"] == "Total income" and row["treatment_arm"] == "T1"
    assert row["p_text"] == "***" and row["page"] == 7
    assert row["doc_key"] == "paper.pdf"


def test_a_cell_with_estimate_and_se_is_split():
    data = {"results_table": True,
            "estimates": [{"outcome": "Expenditure", "estimate_cell": "311** (119)"}]}
    row = build_rows("proj", DOC, 3, data, "vision-model")[0]
    assert row["effect_size"] == 311 and row["standard_error"] == 119
    assert row["p_text"] == "**"


def test_no_table_or_no_number_yields_no_rows():
    assert build_rows("proj", DOC, 3, {"results_table": False}, "m") == []
    assert build_rows("proj", DOC, 3, {"results_table": True, "estimates": [{"outcome": "x"}]}, "m") == []
