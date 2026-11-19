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


def test_resolver_breaks_an_ambiguous_caption_match():
    body_a = "| x | 1 |\n| --- | --- |\n| a | 1 |"
    body_b = "| y | 2 |\n| --- | --- |\n| b | 2 |"
    docling = {"content_list": [_table(body_a, 3, "Table 2 Consumption Results")], "page_count": 4}
    mineru = {"content_list": [_table(body_b, 3, "Table 2 Consumption Results"),
                               _table(body_a, 3, "Table 2 Consumption Results")], "page_count": 4}
    calls = []

    def resolver(table, candidates, reason):
        calls.append(reason)
        for i, c in enumerate(candidates):
            if c.get("text") == body_a:
                return i
        return -1

    out = merge_parser_outputs(docling, mineru, resolver=resolver)
    tables = [i for i in out["content_list"] if i["type"] == "table"]
    assert calls and calls[0] == "ambiguous"
    both = [t for t in tables if t["_sources"] == ["docling", "mineru"]]
    solo = [t for t in tables if t["_sources"] == ["mineru"]]
    assert len(both) == 1 and both[0]["text"] == body_a
    assert len(solo) == 1 and solo[0]["text"] == body_b


def test_resolver_can_decline_all_candidates():
    docling = {"content_list": [_table("| a | 1 |\n| --- | --- |\n| a | 1 |", 3, "Table 2 Results")], "page_count": 4}
    mineru = {"content_list": [_table("| b | 2 |\n| --- | --- |\n| b | 2 |", 3, "Table 2 Results"),
                               _table("| c | 3 |\n| --- | --- |\n| c | 3 |", 3, "Table 2 Results")], "page_count": 4}
    out = merge_parser_outputs(docling, mineru, resolver=lambda t, c, r: -1)
    tables = [i for i in out["content_list"] if i["type"] == "table"]
    # Declined everywhere, so the primary and both secondary tables each survive alone.
    assert sorted(tuple(t["_sources"]) for t in tables) == [("docling",), ("mineru",), ("mineru",)]


def test_resolver_pairs_across_pages_when_rules_fail():
    docling = {"content_list": [_table("| q | 7 |\n| --- | --- |\n| q | 7 |", 5, "Annex A")], "page_count": 7}
    mineru = {"content_list": [_table("| z | 9 |\n| --- | --- |\n| z | 9 |", 6, "Annex")], "page_count": 7}
    calls = []

    def resolver(table, candidates, reason):
        calls.append(reason)
        return 0

    out = merge_parser_outputs(docling, mineru, resolver=resolver)
    tables = [i for i in out["content_list"] if i["type"] == "table"]
    assert len(tables) == 1 and tables[0]["_sources"] == ["docling", "mineru"]
    assert "unmatched" in calls


def test_duplicate_table_under_different_caption_is_collapsed():
    body = "| a | 1 |\n| --- | --- |\n| x | 1 |"
    docling = {"content_list": [_table(body, 3, "Table A")], "page_count": 10}
    mineru = {"content_list": [_table(body, 8, "Annex Table")], "page_count": 10}
    out = merge_parser_outputs(docling, mineru)
    tables = [i for i in out["content_list"] if i["type"] == "table"]
    assert len(tables) == 1 and tables[0]["_sources"] == ["docling", "mineru"]


def test_distinct_tables_are_not_collapsed():
    docling = {"content_list": [_table("| a | 1 |\n| --- | --- |\n| x | 1 |", 3, "Table A")], "page_count": 5}
    mineru = {"content_list": [_table("| b | 2 |\n| --- | --- |\n| y | 2 |", 3, "Table B")], "page_count": 5}
    out = merge_parser_outputs(docling, mineru)
    assert len([i for i in out["content_list"] if i["type"] == "table"]) == 2


def test_captioned_copy_preferred_over_uncaptioned():
    body = "| a | 1 |\n| --- | --- |\n| x | 1 |"
    docling = {"content_list": [_table(body, 3, "")], "page_count": 10}
    mineru = {"content_list": [_table(body, 9, "Annex Table")], "page_count": 10}
    out = merge_parser_outputs(docling, mineru)
    tables = [i for i in out["content_list"] if i["type"] == "table"]
    assert len(tables) == 1 and tables[0]["table_caption"] == "Annex Table"
