"""Why an estimate-shaped cell has no stored row: the triage that makes the queue usable.

`table_coverage.py` counts cells, and 5,609 of them look alarming. Most are not gaps: a control mean, an
observation count, a standard-error cell or a table reproduced in an appendix is estimate-shaped and is
never meant to become a row. This classifies every unstored cell by the reason it is unstored, so the
number that remains, the cells nothing explains, is the one worth reading.

It reads only, calls no model, and writes a report with a sample of the unexplained cells and their row
labels, so the sample can be checked by eye against the papers.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from evaluation.stored_rows import fetch_all, matches  # noqa: E402
from evaluation.table_coverage import cell_values  # noqa: E402
from evaluation.usage_study import load_content  # noqa: E402
from src.extraction.table_rules import classify_table, looks_garbled  # noqa: E402
from src.extraction.table_structure import parse_markdown_table  # noqa: E402
from supabase import create_client  # noqa: E402

PROJECT = os.environ.get("RAG_PROJECT_ID") or "7efdc60e-e863-480c-929e-616574725e5f"
REPORT = ROOT / "evaluation" / "results" / f"coverage_triage_{date.today().isoformat()}.md"
EXPORT = ROOT / "evaluation" / "results" / f"coverage_unexplained_{date.today().isoformat()}.json"
CACHE = ROOT / "evaluation" / "results" / "usage_study" / PROJECT / "content"
SAMPLE = 30


def reason(row_label: str, column_label: str, caption: str, page: int, pages: int,
           cell: str = "") -> str:
    label = f"{row_label} {column_label}".lower()
    # Some PDFs render brackets with a broken glyph: "SUP-NSUP ð2Þ" is "SUP-NSUP (2)".
    column = re.sub(r"[þÞ]", ")", re.sub(r"[ðÐ]", "(", str(column_label or "").strip()))
    # A balance table often has no caption word for it. Its columns give it away: a year against a group
    # ("2005 - Treated") or a difference between baseline groups ("SUP-NSUP (2)", "SB1-SNB0 (4)").
    if re.match(r"^(19|20)\d{2}\s*[-–]\s*(treated|control|treatment)\b", column, re.I):
        return "balance or attrition table"
    if re.match(r"^[A-Za-z]{2,5}\s*[-–]\s*[A-Za-z0-9]{2,5}\s*\(\d\)\s*$", column):
        return "balance or attrition table"
    # A mean with its standard deviation in brackets, on a row that is itself a descriptive average, is
    # descriptive statistics rather than an effect.
    if (re.match(r"\s*(average|proportion|mean|share)\b", str(row_label or ""), re.I)
            and re.search(r"\[\s*[\d.,]+\s*\]", str(cell or "")) and not re.search(r"[*†‡]", str(cell or ""))):
        return "table of means"
    # Household characteristics printed without stars are descriptions of the sample, not effects; the
    # same rows with stars are estimates and stay unexplained so they remain on the work list.
    if (re.search(r"\b(age|men|women|male|female|members?|participants?|household size|children)\b",
                  str(row_label or ""), re.I) and not re.search(r"[*†‡]", str(cell or ""))):
        return "covariate row"
    # A balance or attrition table reports pre-programme differences or who answered the survey, not an
    # effect of the programme. Paper a72b's "Table 2a: Test of difference in mean characteristics ... in
    # 2002" and 121058373's "Pooled Attrition" are the examples; storing their starred cells would be wrong.
    if re.search(r"balance|attrition|orthogonal|take[- ]?up|compliance|test of difference in mean|"
                 r"baseline characteristics|completed survey|surveyed mean", str(caption or "").lower()):
        return "balance or attrition table"
    if re.match(r"\s*(test|t[- ]?test|f[- ]?test)\b", str(row_label or "").lower()) or "p-value of" in label:
        # "Test: T2 = T3 | 0.072*" and "t-test | 0.31" carry the p-value of a test, not an estimate.
        return "hypothesis test"
    if re.match(r"\s*(po mean|potential outcome mean)\b", str(row_label or "").lower()):
        # A potential-outcome mean is a level, not an effect.
        return "mean row"
    if re.search(r"control\s+(mean|group mean)|mean (in|of) (the )?control|control\b.*\bmean", label):
        return "control mean"
    # Regression tables with outcomes in the columns list the covariates down the rows. Paper 121058367
    # pages 152 and 153 are all of this shape: "Child age in months", "Male child" and "Endline" are
    # controls, and their coefficients are not treatment effects. Checked after a control mean, because
    # "control" is also a covariate cue.
    if re.match(r"\s*(child age|male child|female child|endline|baseline|constant|controls?\b|age\b|"
                r"male\b|female\b|household size|age squared|year dummies|district\b|region\b)",
                str(row_label or "").lower()):
        return "covariate row"
    if re.search(r"\bobs\b|observation|sample size|\bn\b\s*=", label):
        return "observation count"
    if re.search(r"standard error|\bs\.?e\.?\b|\bt-?stat|\bp-?value|\bsd\b|standard deviation", label):
        return "statistic"
    if re.match(r"\s*table\s+a", caption or "", re.I):
        return "appendix table"
    if pages and page > pages * 0.85:
        return "late appendix page"
    return "unexplained"


def main() -> None:
    sb = create_client(os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    names = [d["filename"] for d in
             sb.table("documents").select("filename").eq("rag_project_id", PROJECT).execute().data]
    only = [a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--doc=")]
    if only:
        names = [n for n in names if n in only]

    counts: Counter = Counter()
    examples: dict = defaultdict(list)
    unexplained_cells = []
    # One pass over the project's rows, grouped by document and page: the instance budgets disk IO.
    by_document: dict = defaultdict(lambda: defaultdict(list))
    for row in fetch_all(sb.table("effect_estimates").select("doc_key,page,effect_size,standard_error")
                         .eq("rag_project_id", PROJECT).eq("source", "tables_v1")):
        for field in ("effect_size", "standard_error"):
            if row.get(field) is not None:
                by_document[row.get("doc_key")][row.get("page")].append(row[field])
    read = 0
    for name in names:
        try:
            content = load_content(PROJECT, name, CACHE)
        except Exception:
            continue
        read += 1
        pages = max(((item.get("page_idx") or 0) + 1 for item in content), default=0)
        # Captions often arrive as a separate title item, so the page's text is the context that says
        # whether a table is a balance, attrition or compliance table rather than a table of effects.
        page_text: dict = {}
        for other in content:
            if other.get("type") in ("text", "title"):
                key = (other.get("page_idx") or 0) + 1
                page_text[key] = (page_text.get(key, "") + " " + str(other.get("text") or ""))[:2000]
        stored = by_document.get(name, {})
        document_values = [value for rows in stored.values() for value in rows]
        for item in content:
            text = str(item.get("text") or "")
            if item.get("type") != "table" or "|" not in text or looks_garbled(text):
                continue
            if classify_table(text[:400])[0] == "descriptive":
                continue
            grid = parse_markdown_table(text)
            headers = grid.headers[-1] if grid.headers else []
            caption = str(item.get("table_caption") or "")
            page = (item.get("page_idx") or 0) + 1
            # A table with no significance stars at all and cells of the form "value (se)" is a table of
            # means, not of effects: paper 121058367 page 64 has 63 such cells and storing them would be
            # wrong. Stars are the signal the reader uses to tell an estimate from a mean.
            table_has_stars = any("*" in cell or "†" in cell or "‡" in cell
                                  for row in grid.body for cell in row[1:])
            for body in grid.body:
                row_label = body[0] if body else ""
                for index, cell in enumerate(body[1:], start=1):
                    candidates = cell_values(cell)
                    if not candidates or any(matches(value, stored.get(page, [])) for value in candidates):
                        continue
                    # A table that spans pages stores its rows under the page it starts on, so a value on
                    # the continuation page is in the store already. Counting those as gaps overstated the
                    # queue by 192 cells of 296; they are attribution, not coverage.
                    if any(matches(value, document_values) for value in candidates):
                        counts["stored on another page"] += 1
                        continue
                    if not table_has_stars:
                        why = "table of means"
                    else:
                        why = reason(row_label, headers[index] if index < len(headers) else "",
                                     f"{caption} {page_text.get(page, '')}", page, pages, cell)
                    counts[why] += 1
                    if why == "unexplained":
                        unexplained_cells.append({
                            "doc": name, "page": page, "row": str(row_label)[:120],
                            "column": str(headers[index] if index < len(headers) else "")[:80],
                            "cell": str(cell)[:40], "caption": caption[:80]})
                        if len(examples[name]) < 3:
                            examples[name].append((page, row_label[:50],
                                                   (headers[index] if index < len(headers) else "")[:28],
                                                   cell[:20]))

    total = sum(counts.values())
    lines = [f"# Coverage triage {date.today().isoformat()}", "",
             f"{total} estimate-shaped cells on {read} documents have no stored row on their page.", ""]
    for why, count in counts.most_common():
        share = 100 * count / total if total else 0
        lines.append(f"- {why}: {count} ({share:.0f}%)")
    unexplained = counts.get("unexplained", 0)
    lines += ["", f"The unexplained remainder is {unexplained} cells, against {total} on the raw count "
                  "that the coverage report quotes.", ""]
    shown = 0
    for name, items in examples.items():
        for page, label, column, cell in items:
            if shown >= SAMPLE:
                break
            lines.append(f"- {name[:46]} p{page}: row '{label}', column '{column}', cell {cell}")
            shown += 1
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    EXPORT.write_text(json.dumps(unexplained_cells, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"documents read {read} of {len(names)} | cells {total}")
    for why, count in counts.most_common():
        print(f"  {why:20} {count}")
    print(f"report {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
