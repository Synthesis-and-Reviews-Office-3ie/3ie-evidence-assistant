"""Tests for merging Docling and MinerU output into one canonical document."""

from infrastructure.modal_lib.extraction import merge_parser_outputs


def _table(text, page, caption=""):
    return {"type": "table", "text": text, "page_idx": page, "table_caption": caption}


def _text(text, page):
    return {"type": "text", "text": text, "page_idx": page}


def test_table_in_both_parsers_is_merged_with_both_sources():
    docling = {"content_list": [_text("intro", 0), _table("| a | b |\n| --- | --- |\n| 1 | 2 |", 1, "Table 1 Results")],
               "page_count": 2, "title": "T"}
    mineru = {"content_list": [_text("intro", 0), _table("| a | b |\n| --- | --- |\n| 1 | 2 |", 1, "Results Table 1")],
              "page_count": 2}
    out = merge_parser_outputs(docling, mineru)
    tables = [i for i in out["content_list"] if i["type"] == "table"]
    assert len(tables) == 1
    assert tables[0]["_sources"] == ["docling", "mineru"]
    assert out["parser"] == "union" and out["sources"] == ["docling", "mineru"]


def test_table_only_in_one_parser_survives():
    docling = {"content_list": [_table("| a |\n| --- |\n| 1 |", 1, "Results 1")], "page_count": 2}
    mineru = {"content_list": [_table("| a |\n| --- |\n| 1 |", 1, "Results 1"),
                               _table("| z |\n| --- |\n| 9 |", 5, "Appendix Table")], "page_count": 6}
    out = merge_parser_outputs(docling, mineru)
    tables = [i for i in out["content_list"] if i["type"] == "table"]
    assert len(tables) == 2
    sources = sorted(tuple(t["_sources"]) for t in tables)
    assert ("docling", "mineru") in sources
    assert ("mineru",) in sources


def test_adjacent_page_content_signature_matches():
    body = "| Outcome | Coef |\n| --- | --- |\n| Consumption | 0.15 |"
    docling = {"content_list": [_table(body, 7, "")], "page_count": 9}
    mineru = {"content_list": [_table(body, 8, "")], "page_count": 9}
    out = merge_parser_outputs(docling, mineru)
    tables = [i for i in out["content_list"] if i["type"] == "table"]
    assert len(tables) == 1 and tables[0]["_sources"] == ["docling", "mineru"]


def test_prose_from_primary_and_recovered_from_secondary():
    docling = {"content_list": [_text("primary text on page 0", 0)], "page_count": 3}
    mineru = {"content_list": [_text("primary text on page 0", 0), _text("page two only mineru", 2)],
              "page_count": 3}
    out = merge_parser_outputs(docling, mineru)
    texts = [i["text"] for i in out["content_list"] if i["type"] == "text"]
    assert "primary text on page 0" in texts
    assert any("page two only mineru" in t and t for t in texts)
    recovered = [i for i in out["content_list"] if i.get("recovered")]
    assert len(recovered) == 1


def test_html_table_from_mineru_is_normalised():
    html = "<table><tr><th>Outcome</th><th>Coef</th></tr><tr><td>Income</td><td>0.2</td></tr></table>"
    docling = {"content_list": [_text("intro", 0)], "page_count": 1}
    mineru = {"content_list": [{"type": "table", "text": "", "table_body": html, "page_idx": 0}],
              "page_count": 1}
    out = merge_parser_outputs(docling, mineru)
    tables = [i for i in out["content_list"] if i["type"] == "table"]
    assert len(tables) == 1
    assert "| Outcome | Coef |" in tables[0]["text"]
