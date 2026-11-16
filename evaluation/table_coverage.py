"""Which results-table cells never reached the stored rows.

The hand-typed key found seven cells that the extractor dropped or attributed to the wrong column of
a wide table, and it finds them only because a person once typed them. A collection of 97 documents
needs a check that works without a key: read every results table the parser produced, list the cells
that carry an estimate (a number with stars, or a number with a value in parentheses beside it), and
compare them with the rows stored for that page.

A cell with no stored row within the printed precision is a coverage gap. The report ranks documents
by gaps so the extraction work follows the evidence instead of a guess. It reads only, calls no
model, and is meant to run after an ingestion batch and in CI.
"""

from __future__ import annotations

import os
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from evaluation.stored_rows import fetch_all, matches  # noqa: E402
from evaluation.usage_study import load_content  # noqa: E402
from src.extraction.table_rules import classify_table, is_pipe_table, looks_garbled  # noqa: E402
from supabase import create_client  # noqa: E402

PROJ = os.environ.get("RAG_PROJECT_ID") or "7efdc60e-e863-480c-929e-616574725e5f"
REPORT = ROOT / "evaluation" / "results" / f"table_coverage_{date.today().isoformat()}.md"

# A number, optional stars, and an optional number in parentheses on the same line. The stars or the
# parenthesised neighbour are what mark a cell as an estimate rather than a mean, a count or a note.
# A whole cell that is an estimate: a number, then significance stars, or a bracketed statistic, or
# both. Anchoring at the start of the cell matters: a label such as "Panel A. Endline 1 (18 months)"
# contains a number and a parenthesis and was counted as a cell until this was anchored.
CELL = re.compile(
    r"^\s*([-−–]?\d[\d,]*(?:\.\d+)?)\s*"
    r"(?:[*†‡]+(?:\s*[(\[]\s*[-−–]?\d[\d,]*(?:\.\d+)?\s*[)\]])?"
    r"|[(\[]\s*[-−–]?\d[\d,]*(?:\.\d+)?\s*[)\]])"
    r"\s*$")


def cell_value(cell: str):
    """The estimate of a table cell when the whole cell is an estimate, else None."""
    found = CELL.match(str(cell or ""))
    if not found:
        return None
    try:
        return float(found.group(1).replace(",", ""))
    except ValueError:
        return None


def estimate_cells(text: str) -> list:
    """The estimate-shaped values in one table's text, as floats."""
    out = []
    for line in str(text or "").splitlines():
        if "|" not in line:
            continue
        for cell in line.strip().strip("|").split("|"):
            value = cell_value(cell)
            if value is not None:
                out.append(value)
    return out


def uncovered(cells: list, stored: list) -> list:
    """Cell values with no stored value of the same page at printed precision."""
    return [value for value in cells if not matches(value, stored)]


def table_rows(content: list) -> list:
    """The results-shaped tables in a content list, with their page and cells."""
    out = []
    for item in content:
        text = str(item.get("text") or "")
        if item.get("type") != "table" and not is_pipe_table(text):
            continue
        if looks_garbled(text):
            continue
        kind = classify_table(text[:400])[0]
        if kind == "descriptive":
            continue
        cells = estimate_cells(text)
        if cells:
            out.append({"page": (item.get("page_idx") or 0) + 1, "cells": cells, "kind": kind})
    return out


def main() -> None:
    sb = create_client(os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_ROLE_KEY"])

    docs = sb.table("documents").select("filename").eq("rag_project_id", PROJ).execute().data
    wanted = [a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--doc=")]
    names = [d["filename"] for d in docs if not wanted or d["filename"] in wanted]

    lines = ["# Table coverage", "",
             "Results-table cells with no stored row on the same page, within the printed precision.",
             ""]
    total_cells = total_gaps = 0
    by_document = {}
    loaded = 0
    for name in names:
        try:
            content = load_content(PROJ, name, ROOT / "evaluation" / "results" / "usage_study" / PROJ / "content")
        except Exception:
            continue
        loaded += 1
        rows = fetch_all(sb.table("effect_estimates")
                         .select("page,effect_size,standard_error")
                         .eq("rag_project_id", PROJ).eq("doc_key", name).eq("source", "tables_v1"))
        by_page = {}
        for r in rows:
            for key in ("effect_size", "standard_error"):
                if r.get(key) is not None:
                    by_page.setdefault(r.get("page"), []).append(r[key])
        gaps = []
        for table in table_rows(content):
            stored = by_page.get(table["page"], [])
            missing = uncovered(table["cells"], stored)
            total_cells += len(table["cells"])
            total_gaps += len(missing)
            if missing:
                gaps.append((table["page"], table["kind"], len(missing), len(table["cells"]), missing[:6]))
        if gaps:
            lines.append(f"## {name}")
            lines.append("")
            for page, kind, miss, cells, samples in sorted(gaps, key=lambda g: -g[2])[:8]:
                lines.append(f"- page {page} ({kind}): {miss} of {cells} cells unstored, e.g. {samples}")
            lines.append("")
            by_document[name] = sum(g[2] for g in gaps)
    lines.insert(4, f"{total_gaps} of {total_cells} estimate-shaped cells have no stored row.")
    lines.insert(5, "")
    if not loaded:
        # Without object-storage credentials every document fails to load, and "0 of 0 cells" reads
        # like a clean bill of health. Say what happened instead.
        lines.insert(4, f"No document could be read ({len(names)} requested), so nothing was checked. "
                        "The parsed content lives in object storage; this check needs its credentials.")
        print("::notice::Table coverage skipped: no parsed document could be read. "
              "The check needs object-storage credentials for the parsed content.")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"documents read {loaded} of {len(names)} | cells {total_cells} | unstored {total_gaps} | "
          f"report {REPORT.relative_to(ROOT)}")
    for name, count in Counter(by_document).most_common(5):
        print(f"  {count:5} {name[:60]}")


if __name__ == "__main__":
    main()
