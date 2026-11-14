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

VISION_PROMPT = """You are given one page of an academic paper as an image. Find any table that
reports estimated effects of a programme or treatment: a regression table, a difference-in-differences
table, an experiment's results table, or an appendix table of estimates.

If the page has no such table, return {"results_table": false, "estimates": []}.

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


def vision_pages(content_list: Sequence[Dict[str, Any]], max_pages: int = 12) -> List[int]:
    """Pages to read from images: those with image items and those whose table text is garbled."""
    pages = set(table_image_pages(content_list, max_pages))
    pages.update(garbled_table_pages(content_list, max_pages))
    return sorted(pages)[:max_pages]


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
