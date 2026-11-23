"""Image-table fallback: page selection, rendering and row building (src/extraction/page_vision.py)."""

import asyncio
import json

import pytest

import src.extraction.page_vision as page_vision
from src.extraction.page_vision import (
    _has_pipe_table,
    apply_transcriptions,
    auto_vision_pages,
    build_rows,
    garbled_table_pages,
    render_page_png,
    repaired_pages,
    table_image_pages,
    transcribe_garbled_pages,
    vision_pages,
)

DOC = {"id": "doc-1", "filename": "paper.pdf"}


def test_page_read_rows_get_the_role_flag(monkeypatch):
    # Audit 2026-11-20: rows read from the page image carried no roles, so the flag was blind on
    # odd-PDF documents (Emran 2014, 121346575). The role step now runs on them too.
    import src.extraction.table_estimates as module
    from src.extraction.page_vision import label_vision_roles

    async def fake_chat(client, model, content):
        assert isinstance(content, list) and content[1]["type"] == "image_url"  # the page image is sent
        return json.dumps({"rows": {"Consumption": "outcome", "Control mean": "control_or_covariate"},
                           "columns": {"Programme": "programme_effect"}})

    monkeypatch.setattr(module, "_chat", fake_chat)
    rows = [{"page": 3, "outcome_name": "Consumption", "treatment_arm": "Programme"},
            {"page": 3, "outcome_name": "Control mean", "treatment_arm": "Programme"}]
    out = asyncio.run(label_vision_roles(rows, {3: "data:image/png;base64,AAAA"}, "m", "k"))
    assert out[0]["row_role"] == "outcome" and out[0]["column_role"] == "programme_effect"
    assert out[0]["keep_effect"] is True
    assert out[1]["keep_effect"] is False


def test_page_read_rows_keep_open_when_the_page_image_is_absent(monkeypatch):
    import src.extraction.table_estimates as module
    from src.extraction.page_vision import label_vision_roles

    async def fake_chat(client, model, content):
        assert isinstance(content, str)  # no image, so a plain prompt
        return "{}"

    monkeypatch.setattr(module, "_chat", fake_chat)
    out = asyncio.run(label_vision_roles([{"page": 4, "outcome_name": "X", "treatment_arm": "Y"}], {}, "m", "k"))
    assert out[0]["keep_effect"] is True


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


def test_a_transcription_counts_as_a_table_only_with_two_pipe_rows():
    assert _has_pipe_table("| a | b |\n| --- | --- |\n| 1 | 2 |")
    assert not _has_pipe_table("Table 1.B.3 shows the categories in the programme.")
    assert not _has_pipe_table("I can't reproduce the full page verbatim, but here is a summary.")
    assert not _has_pipe_table("| only one row |")


GARBLED = [{"type": "table", "page_idx": 5,
            "text": "????? ?? ??????? a114 a116 a117 a118 a119 a120 a121 a122"},
           {"type": "text", "page_idx": 0, "text": "Kept paragraph."}]
TABLE_MD = "Table 1.B.3: Coaching sessions\n\n| Session | Phase |\n| --- | --- |\n| 5 | 2 |"


async def _run_repair(monkeypatch, replies):
    calls = []

    async def fake(pdf_bytes, page, model, api_key, client=None, dpi=200, prompt=None, image=None):
        calls.append(prompt)
        reply = replies[min(len(calls) - 1, len(replies) - 1)]
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(page_vision, "transcribe_page", fake)
    monkeypatch.setattr(page_vision, "page_data_url", lambda *a, **k: "data:x")
    stats = {}
    content, markdown = await page_vision.repair_garbled_document(
        GARBLED, "# Title", b"%PDF", "m", "k", stats=stats)
    return content, markdown, stats, calls


def test_a_page_flagged_garbled_is_replaced_by_a_table_transcription(monkeypatch):
    content, markdown, stats, _ = asyncio.run(_run_repair(monkeypatch, [TABLE_MD]))
    assert [item["type"] for item in content] == ["text", "text"]
    assert "Session" in content[0]["text"] and stats["replaced"] == 1 and stats["failed"] == []
    assert "page 6" in markdown
    assert content[0]["repaired"] is True


def test_a_repaired_page_is_still_read_from_the_image():
    good = {"type": "table", "page_idx": 9, "text": "| Outcome | Coef |\n| --- | --- |\n| Food | 0.5 |"}
    content = [{"type": "text", "page_idx": 5, "text": "Table 1 | a | b |", "repaired": True}, good]
    assert repaired_pages(content) == [6]
    assert auto_vision_pages(content) == [6]


def test_a_document_with_only_readable_tables_gets_no_vision_calls():
    good = {"type": "table", "page_idx": 3, "text": "| a | b |\n| --- | --- |\n| 1 | 2 |"}
    assert auto_vision_pages([good]) == []


def test_a_retyped_pipe_table_page_is_not_re_read_by_the_full_scan():
    content = [{"type": "table", "page_idx": 2, "reclassified": True,
                "text": "Table 1\n| a | b |\n| --- | --- |\n| 1 | 2 |"}]
    assert vision_pages(content, pdf_pages=6, full_scan_cap=6) == [1, 2, 4, 5, 6]
    assert auto_vision_pages(content, pdf_pages=6, full_scan_cap=6) == [1, 2, 4, 5, 6]


def test_a_page_is_rendered_once_across_prompt_attempts(monkeypatch):
    prompts = []

    async def fake(pdf_bytes, page, model, api_key, client=None, dpi=200, prompt=None, image=None):
        prompts.append(prompt)
        return "No tables on this page."

    renders = []
    monkeypatch.setattr(page_vision, "transcribe_page", fake)
    monkeypatch.setattr(page_vision, "page_data_url", lambda *a, **k: renders.append(1) or "data:x")
    stats = {}
    asyncio.run(page_vision.repair_garbled_document(GARBLED, "# T", b"%PDF", "m", "k", stats=stats))
    assert len(prompts) == 2 and len(renders) == 1
    assert stats["attempts"] == 2 and stats["failed"] == [6]


def test_a_refusal_is_retried_with_the_table_prompt_then_kept_when_it_fails(monkeypatch):
    content, _, stats, calls = asyncio.run(_run_repair(
        monkeypatch, ["I can't reproduce the full page verbatim, but here is a summary.", "No tables here."]))
    assert len(calls) == 2 and calls[0] != calls[1]
    assert stats["replaced"] == 0 and stats["failed"] == [6]
    assert "a114" in json.dumps(content)


def test_a_page_whose_transcription_carries_no_table_keeps_the_original(monkeypatch):
    content, _, stats, _ = asyncio.run(_run_repair(monkeypatch, ["Prose only, no table at all."]))
    assert stats["replaced"] == 0 and stats["failed"] == [6]
    assert any("a114" in (item.get("text") or "") for item in content)


def test_a_failed_vision_call_is_recorded_and_keeps_the_original(monkeypatch):
    content, _, stats, _ = asyncio.run(_run_repair(monkeypatch, [RuntimeError("429 rate limited")]))
    assert stats["replaced"] == 0 and stats["failed"] == [6]
    assert "429" in stats["errors"][6]


def test_a_figure_reading_keeps_its_series_and_wave():
    data = {"results_table": True, "table_label": "FIGURE 5 Food insecurity",
            "estimates": [{"outcome": "Food insecurity index", "arm": "Full cost", "subgroup": "Endline",
                           "estimate_cell": "-0.123", "coefficient": -0.123, "standard_error": None}]}
    rows = build_rows("p", DOC, 9, data, "m")
    assert len(rows) == 1
    assert rows[0]["treatment_arm"] == "Full cost" and rows[0]["subgroup"] == "Endline"
    assert rows[0]["effect_size"] == -0.123


def test_a_page_read_row_carries_a_cell_address():
    from src.extraction.page_vision import _row

    row = _row("p", DOC, 4, "Table 2", "m",
               {"outcome": "Income", "coefficient": 0.5, "row_index": 3, "column_index": 2})
    assert row["cell_row"] == 2 and row["cell_column"] == 1
    assert "r2c1" in row["text_position"]


def test_a_page_read_row_without_an_index_has_no_address():
    from src.extraction.page_vision import _row

    row = _row("p", DOC, 4, "Table 2", "m", {"outcome": "Income", "coefficient": 0.5})
    assert row["cell_row"] is None and row["cell_column"] is None
