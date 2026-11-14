"""
Read tables that the parser left as images.

Some papers have tables the parser did not turn into text. Paper 121766336, for example, has 51
parsed items and zero tables: six image items and text. Its tables are pictures, so no text extractor
can read them, and 18 of the hand-typed estimates in the human key come from there.

This module renders the pages that hold image items and sends each page image to a vision model with
the same table-extraction task. It is deliberately separate from `table_estimates.py`: the text path
is cheaper and should stay first, and this is a fallback for pages without readable tables.

The model call is `extract_pages`. Everything else is pure and tested without a network call:
`table_image_pages`, `render_page_png` and `build_rows`.
"""

from __future__ import annotations

import base64
import json
import re
from typing import Any, Dict, List, Optional, Sequence

from src.extraction.table_estimates import parse_number
from src.extraction.table_rules import looks_garbled

VISION_PROMPT = """You are given one page of an academic paper as an image. Find any table, or any
figure or plot that prints its results as text, that reports estimated effects of a programme or
treatment: a regression table, a difference-in-differences table, an experiment's results table, an
appendix table of estimates, or a figure with printed data labels.

If the page has neither, return {"results_table": false, "estimates": []}.

Figures: when a plot prints values as text (data labels, callouts such as "0.12***" or
"[0.05, 0.19]"), extract those values the same way, using the printed label as the arm. Only report
numbers printed on the page. Never estimate a value from an axis position, a bar height or a line.

Otherwise return JSON only:
{"results_table": true,
 "table_label": "<table number and caption>",
 "estimates": [{
   "outcome": "<what is measured, as printed>",
   "arm": "<treatment group or model column, as printed>",
   "subgroup": "<subgroup if any>",
   "estimate_cell": "<the printed cell with the estimate, e.g. 0.15*** (0.05)>",
   "se_cell": "<the printed standard error cell if separate>",
   "coefficient": <number from the cell>,
   "standard_error": <number or null>,
   "p_value": <number between 0 and 1, or null>,
   "stars": <count of significance stars, 0 if none>,
   "sample_size": <number or null>
 }]}

Copy the numbers exactly as printed. If a cell holds "estimate (standard error)", put the whole text
in estimate_cell and split it into coefficient and standard_error. Do not invent values, and do not
report control-group means, observations, R2 or constants as outcomes."""


def table_image_pages(content_list: Sequence[Dict[str, Any]], max_pages: int = 12) -> List[int]:
    """1-based pages that carry an image item, deduplicated, sorted and capped.

    Image items are often figures, not tables. The page is still sent, because the model decides
    whether it holds a results table; the cap bounds the cost.
    """
    pages = set()
    for item in content_list:
        if item.get("type") != "image":
            continue
        page = item.get("page_idx")
        if page is None or str(page).strip() == "":
            continue
        try:
            pages.add(int(page) + 1)
        except (TypeError, ValueError):
            continue
    return sorted(pages)[:max_pages]


def _open_pdf(pdf_bytes: bytes):
    try:
        import pymupdf
        return pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except ImportError:
        import fitz
        return fitz.open(stream=pdf_bytes, filetype="pdf")


def garbled_table_pages(content_list: Sequence[Dict[str, Any]], max_pages: int = 12) -> List[int]:
    """Pages whose tables the parser returned as broken text, so the text reader cannot use them."""
    pages = set()
    for item in content_list:
        if item.get("type") != "table" or not looks_garbled(item.get("text")):
            continue
        page = item.get("page_idx")
        try:
            pages.add(int(page) + 1)
        except (TypeError, ValueError):
            continue
    return sorted(pages)[:max_pages]


def vision_pages(content_list: Sequence[Dict[str, Any]], pdf_pages: Optional[int] = None,
                 max_pages: int = 12, full_scan_cap: int = 40) -> List[int]:
    """Pages to read from images.

    Usually the pages with image items plus the pages whose table text is garbled. When the parser
    found no table at all, the tables are somewhere else in the document, so every page up to
    `full_scan_cap` is scanned instead (paper 121766336 has 51 items, no tables, and 18 needed
    estimates).
    """
    if pdf_pages and not any(item.get("type") == "table" for item in content_list):
        return list(range(1, min(int(pdf_pages), full_scan_cap) + 1))
    pages = set(table_image_pages(content_list, max_pages))
    pages.update(garbled_table_pages(content_list, max_pages))
    return sorted(pages)[:max_pages]


def auto_vision_pages(content_list: Sequence[Dict[str, Any]], pdf_pages: Optional[int] = None,
                      max_pages: int = 12, full_scan_cap: int = 40) -> List[int]:
    """Automatic decision for new uploads: read from images only when the text cannot be trusted.

    That is when some table text is garbled, or the parser found no table at all. A document with
    readable tables gets no vision calls, which keeps the default cost down.
    """
    has_table = any(item.get("type") == "table" for item in content_list)
    if garbled_table_pages(content_list, max_pages) or not has_table:
        return vision_pages(content_list, pdf_pages, max_pages, full_scan_cap)
    return []


def page_count(pdf_bytes: bytes) -> int:
    document = _open_pdf(pdf_bytes)
    try:
        return document.page_count
    finally:
        document.close()


def render_page_png(pdf_bytes: bytes, page_number: int, dpi: int = 200) -> bytes:
    """One page rendered to PNG, for the vision model."""
    document = _open_pdf(pdf_bytes)
    try:
        if not 1 <= page_number <= document.page_count:
            raise ValueError(f"page {page_number} outside 1..{document.page_count}")
        pixmap = document[page_number - 1].get_pixmap(dpi=dpi)
        return pixmap.tobytes("png")
    finally:
        document.close()


TRANSCRIBE_PROMPT = """Transcribe this page of an academic paper exactly, as text.

Keep every table as a GitHub Markdown pipe table: its caption, column headers, row labels, numbers,
significance stars, parentheses and notes, all in their original order. Do not summarise, explain or
add anything. If the page has no text table, return an empty string."""


async def transcribe_page(pdf_bytes: bytes, page: int, model: str, api_key: str, client=None,
                          dpi: int = 200) -> str:
    """Markdown transcription of one page, for replacing parser text that came through garbled."""
    import httpx

    own = client is None
    client = client or httpx.AsyncClient(timeout=300, headers={"Authorization": f"Bearer {api_key}"})
    try:
        png = render_page_png(pdf_bytes, page, dpi=dpi)
        data_url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        response = await client.post("/chat/completions", json={
            "model": model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": TRANSCRIBE_PROMPT},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]}],
        })
        return str(response.json()["choices"][0]["message"]["content"]).strip()
    finally:
        if own:
            await client.aclose()


async def transcribe_garbled_pages(content_list: Sequence[Dict[str, Any]], pdf_bytes: bytes,
                                   model: str, api_key: str, client=None, max_pages: int = 12,
                                   transcriber=None) -> List[Dict[str, Any]]:
    """A content list with garbled table pages replaced by a clean Markdown transcription.

    The parser sometimes returns broken glyphs for a page ("????? ?? ???????a114"). Those items are
    useless to retrieval and to the reader. One transcription per affected page replaces the garbled
    items, so the page can be chunked and read like any other. Good pages are left untouched.
    """
    pages = garbled_table_pages(content_list, max_pages)
    if not pages:
        return list(content_list)
    do_transcribe = transcriber or transcribe_page
    out: List[Dict[str, Any]] = []
    done: set = set()
    for item in content_list:
        try:
            page = int(item.get("page_idx")) + 1 if item.get("page_idx") not in (None, "") else None
        except (TypeError, ValueError):
            page = None
        if page in pages and item.get("type") in ("table", "text"):
            if page in done:
                continue
            transcript = await do_transcribe(pdf_bytes, page, model, api_key)
            done.add(page)
            if str(transcript).strip():
                out.append({"type": "text", "text": str(transcript).strip(), "page_idx": item.get("page_idx")})
            continue
        out.append(item)
    return out


def _row(project_id: str, doc: Dict[str, Any], page: int, label: str, model: str,
         raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    cell = str(raw.get("estimate_cell") or raw.get("coefficient") or "").strip()
    coefficient = parse_number(raw.get("coefficient")) if raw.get("coefficient") is not None else None
    if coefficient is None:
        coefficient = parse_number(cell)
    if coefficient is None:
        return None
    se = parse_number(raw.get("standard_error")) if raw.get("standard_error") is not None else None
    if se is None:
        se = parse_number(raw.get("se_cell"))
    if se is None:
        # "311** (119)": the standard error is the parenthesised number in the same cell.
        match = re.search(r"[(\[]\s*([-−–]?\d[\d.,]*)\s*[)\]]", cell)
        se = parse_number(match.group(1)) if match else None
    p = raw.get("p_value") if isinstance(raw.get("p_value"), (int, float)) else None
    stars = raw.get("stars") if isinstance(raw.get("stars"), int) else cell.count("*")
    n = parse_number(raw.get("sample_size"))
    outcome = str(raw.get("outcome") or raw.get("row_label") or "?")[:500]
    return {
        "rag_project_id": project_id, "document_id": doc["id"], "doc_key": doc["filename"],
        "source": "tables_v1",
        "table_number": str(raw.get("table_label") or label)[:120],
        "outcome_name": outcome,
        "treatment_arm": (str(raw.get("arm"))[:200] if raw.get("arm") else None),
        "subgroup": (str(raw.get("subgroup"))[:200] if raw.get("subgroup") else None),
        "effect_size": coefficient,
        "standard_error": se,
        "p_value": p if p is not None and 0 <= p <= 1 else None,
        "p_text": "*" * stars if isinstance(stars, int) and stars else None,
        "ci_text": None,
        "sample_size": int(n) if n is not None and abs(n) < 2 ** 31 and n == int(n) else None,
        "literal_text": (cell + (" " + str(raw.get("se_cell")) if raw.get("se_cell") else ""))[:500],
        "text_position": f"page {page}, vision read",
        "page": page, "extraction_method": model,
    }


def build_rows(project_id: str, doc: Dict[str, Any], page: int, data: Dict[str, Any],
               model: str) -> List[Dict[str, Any]]:
    """Rows in the `effect_estimates` shape from one page's model output."""
    if not isinstance(data, dict) or not data.get("results_table"):
        return []
    label = str(data.get("table_label") or f"table image on page {page}")
    rows = []
    for raw in data.get("estimates") or []:
        if isinstance(raw, dict):
            row = _row(project_id, doc, page, label, model, raw)
            if row is not None:
                rows.append(row)
    return rows


async def extract_pages(pdf_bytes: bytes, pages: Sequence[int], model: str, api_key: str,
                        project_id: str, doc: Dict[str, Any], client=None,
                        dpi: int = 200) -> Dict[str, Any]:
    """Render each page and ask the vision model for its table. Returns rows and per-page records."""
    import httpx

    own_client = client is None
    client = client or httpx.AsyncClient(timeout=300, headers={"Authorization": f"Bearer {api_key}"})
    rows: List[Dict[str, Any]] = []
    records = []
    try:
        for page in pages:
            try:
                png = render_page_png(pdf_bytes, page, dpi=dpi)
                data_url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
                response = await client.post("/chat/completions", json={
                    "model": model,
                    "messages": [{"role": "user", "content": [
                        {"type": "text", "text": VISION_PROMPT},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ]}],
                    "response_format": {"type": "json_object"},
                })
                text = response.json()["choices"][0]["message"]["content"]
                match = re.search(r"\{.*\}", text, re.S)
                data = json.loads(match.group(0)) if match else {}
                page_rows = build_rows(project_id, doc, page, data, model)
                rows.extend(page_rows)
                records.append({"page": page, "results_table": bool(data.get("results_table")),
                                "estimates": len(page_rows)})
            except Exception as e:
                records.append({"page": page, "error": f"{type(e).__name__}: {str(e)[:120]}"})
    finally:
        if own_client:
            await client.aclose()
    return {"rows": rows, "pages": records}
