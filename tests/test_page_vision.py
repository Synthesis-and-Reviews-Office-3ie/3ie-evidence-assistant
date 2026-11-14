"""Image-table fallback: page selection, rendering and row building (src/extraction/page_vision.py)."""

import pytest

from src.extraction.page_vision import (
    apply_transcriptions, auto_vision_pages, build_rows, garbled_table_pages, render_page_png,
    table_image_pages, transcribe_garbled_pages, vision_pages,
)

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


def test_a_document_with_no_parsed_tables_scans_every_page():
    content = [{"type": "text", "page_idx": 0}, {"type": "image", "page_idx": 3}]
    pages = vision_pages(content, pdf_pages=9, full_scan_cap=40)
    assert pages == list(range(1, 10))


def test_auto_vision_runs_only_when_the_text_is_untrustworthy():
    good = [{"type": "table", "page_idx": 2, "text": "| Outcome | Coef |\n| --- | --- |\n| Food | 0.5 |"},
            {"type": "image", "page_idx": 5}]
    assert auto_vision_pages(good, pdf_pages=20) == []
    garbled = [{"type": "table", "page_idx": 5,
                "text": "| ?????? a114 a116 a115 a80 a91 a92 a93 a94 a95 |"}]
    assert auto_vision_pages(garbled, pdf_pages=20) == [6]


def test_garbled_table_pages_are_read_from_images():
    content = [
        {"type": "image", "page_idx": 2},
        {"type": "table", "page_idx": 5,
         "text": "| ?????? a114 a116 a115 a80 a91 a92 a93 a94 a95 a96 |"},
        {"type": "table", "page_idx": 9, "text": "| Outcome | Coef |\n| --- | --- |\n| Food | 0.5 |"},
    ]
    assert garbled_table_pages(content) == [6]
    assert vision_pages(content) == [3, 6]


async def test_a_garbled_page_is_replaced_by_one_transcription():
    content = [
        {"type": "table", "page_idx": 5, "text": "| ?????? a114 a116 a115 a80 a91 a92 a93 a94 a95 |"},
        {"type": "text", "page_idx": 5, "text": "????? a114 a116"},
        {"type": "text", "page_idx": 9, "text": "A normal paragraph."},
    ]

    async def fake(pdf, page, model, key):
        return "| Outcome | Coef |\n| --- | --- |\n| Food | 0.5 |"

    out = await transcribe_garbled_pages(content, b"pdf", "m", "k", transcriber=fake)
    assert len(out) == 2
    assert out[0]["type"] == "text" and "Outcome" in out[0]["text"] and out[0]["page_idx"] == 5
    assert out[1]["text"] == "A normal paragraph."


async def test_clean_content_is_returned_unchanged():
    content = [{"type": "text", "page_idx": 1, "text": "A normal paragraph."}]
    assert await transcribe_garbled_pages(content, b"pdf", "m", "k") == content


def test_transcriptions_replace_the_page_items_and_join_the_markdown():
    content = [
        {"type": "table", "page_idx": 5, "text": "| ?????? a114 |"},
        {"type": "text", "page_idx": 9, "text": "Kept paragraph."},
    ]
    content, markdown = apply_transcriptions(content, "# Title", {6: "| Outcome | Coef |"})
    assert [item["type"] for item in content] == ["text", "text"]
    assert content[0]["page_idx"] == 5 and "Outcome" in content[0]["text"]
    assert content[1]["text"] == "Kept paragraph."
    assert "page 6" in markdown and "| Outcome | Coef |" in markdown


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
