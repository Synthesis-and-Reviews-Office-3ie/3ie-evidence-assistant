"""Value and parameter accuracy measured from the stored cell address.

Two levels are measured per row, and only where the row names a cell:

* level 1, value: the stored coefficient is the number printed in the addressed cell;
* level 2, parameter: the stored standard error is a number printed beside the coefficient in the
  addressed cell or in the cell the row names for the error.

A row with no address cannot be checked this way, so it is reported, not scored. Rows written by the
prose reader and the vision reader have no table cell by construction; they are counted separately so
the table rate is not diluted by rows that no address could ever describe.

Numbers are compared at their printed precision, the same rule the extractor uses, because 0.006 and
0.008 are different numbers and 0.085 and 0.0850 are the same one.

    python evaluation/accuracy.py [--docs a.csv b.csv] [--limit N] [--json PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from evaluation.stored_rows import fetch_all  # noqa: E402
from evaluation.usage_study import load_content  # noqa: E402
from src.extraction.table_estimates import (  # noqa: E402
    _holds,
    _value_decimals,
    parse_number,
    table_units,
)
from src.extraction.table_rules import normalise_tables, reclassify_pipe_tables  # noqa: E402
from src.extraction.table_structure import parse_markdown_table  # noqa: E402
from supabase import create_client  # noqa: E402

PROJECT = os.environ.get("RAG_PROJECT_ID") or "7efdc60e-e863-480c-929e-616574725e5f"
SOURCE = "tables_v1"
CACHE = ROOT / "evaluation" / "results" / "usage_study" / PROJECT / "content"
RESULT = ROOT / "evaluation" / "results" / f"accuracy_{date.today().isoformat()}.json"
PAREN = re.compile(r"\(\s*[-−–]?\d[\d.,]*\s*\)")
BRACKET = re.compile(r"\[\s*[-−–]?\d[\d.,]*\s*[,\]]")
NUM = re.compile(r"[-−–]?\d[\d.,]*")


def same_number(left, right) -> bool:
    """Two parsed numbers are the same at the finer of their printed precisions."""
    if left is None or right is None:
        return False
    decimals = max(_value_decimals(left), _value_decimals(right))
    return abs(abs(float(left)) - abs(float(right))) <= 0.5 * 10 ** -decimals + 1e-12


def parameters_after(cell, estimate):
    """Parenthesised or bracketed numbers printed after the coefficient in its own cell."""
    text = str(cell or "")
    position = None
    for token in NUM.finditer(text):
        if _holds(estimate, token.group(0)):
            position = token.end()
            break
    tail = text[position:] if position is not None else text
    found = [parse_number(m.group(0).strip("()[] ")) for m in PAREN.finditer(tail)]
    found += [parse_number(m.group(0).strip("()[] ")) for m in BRACKET.finditer(tail)]
    return [value for value in found if value is not None]


def cell_parameters(cell):
    """Every parenthesised or bracketed number in a cell, for the error cell the row names."""
    text = str(cell or "")
    found = [parse_number(m.group(0).strip("()[] ")) for m in PAREN.finditer(text)]
    found += [parse_number(m.group(0).strip("()[] ")) for m in BRACKET.finditer(text)]
    return [value for value in found if value is not None]


def classify(row) -> str:
    """Which reader wrote the row: table, prose or vision.

    A table row written before cell addresses existed has no unit, so the writer is read from the fields
    each reader sets rather than from the address alone.
    """
    position = str(row.get("text_position") or "")
    if (row.get("table_number") or "") == "prose" or position == "prose read":
        return "prose"
    if "vision read" in position:
        return "vision"
    return "table"


def _units(project: str, name: str):
    content = normalise_tables(load_content(project, name, CACHE))
    return table_units(reclassify_pipe_tables(content))


def measure(docs=None, limit=None, project: str = PROJECT) -> dict:
    """Accuracy by level, over every row of the given documents (or all of the project's)."""
    sb = create_client(os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    names = [d["filename"] for d in
             sb.table("documents").select("filename").eq("rag_project_id", project).execute().data]
    if docs:
        wanted = set(docs)
        names = [name for name in names if name in wanted]
    rows_by_doc: dict[str, list] = defaultdict(list)
    for row in fetch_all(sb.table("effect_estimates")
                         .select("doc_key,page,unit_index,cell_row,cell_column,se_row,se_column,"
                                 "effect_size,standard_error,table_number")
                         .eq("rag_project_id", project).eq("source", SOURCE)):
        rows_by_doc[row["doc_key"]].append(row)

    if limit:
        names = sorted(names, key=lambda n: -len(rows_by_doc.get(n, [])))[:limit]

    out = {"measured": date.today().isoformat(), "project": project, "documents": 0,
           "rows": 0, "table_rows": 0, "prose_rows": 0, "vision_rows": 0,
           "documents_with_table_rows": 0, "no_content": [], "sample": [],
           "addressed": 0, "no_address": 0,
           "value_ok": 0, "value_bad": [],
           "param_printed": 0, "param_ok": 0, "param_missing": 0, "param_bad": []}
    for name in names:
        rows = rows_by_doc.get(name, [])
        out["rows"] += len(rows)
        table_rows = [row for row in rows if classify(row) == "table"]
        out["table_rows"] += len(table_rows)
        out["prose_rows"] += sum(1 for row in rows if classify(row) == "prose")
        out["vision_rows"] += sum(1 for row in rows if classify(row) == "vision")
        if not table_rows:
            continue
        try:
            units = _units(project, name)
        except Exception as error:  # content not in the cache and storage unavailable
            out["no_content"].append(f"{name}: {type(error).__name__}")
            continue
        out["documents"] += 1
        out["documents_with_table_rows"] += 1
        out["sample"].append(name)
        for row in table_rows:
            address = (row.get("unit_index"), row.get("cell_row"), row.get("cell_column"))
            if None in address or row["unit_index"] >= len(units):
                out["no_address"] += 1
                continue
            grid = parse_markdown_table(units[row["unit_index"]]["text"])
            if row["cell_row"] >= len(grid.body) or row["cell_column"] >= len(grid.body[row["cell_row"]]):
                out["no_address"] += 1
                continue
            out["addressed"] += 1
            cell = grid.body[row["cell_row"]][row["cell_column"]]
            if _holds(row.get("effect_size"), cell):
                out["value_ok"] += 1
            elif len(out["value_bad"]) < 50:
                out["value_bad"].append({"doc": name[:30], "page": row.get("page"),
                                         "cell": str(cell)[:30], "stored": row.get("effect_size")})
            parameters = parameters_after(cell, row.get("effect_size"))
            if row.get("se_row") is not None and row.get("se_column") is not None and \
                    row["se_row"] < len(grid.body) and row["se_column"] < len(grid.body[row["se_row"]]):
                parameters += cell_parameters(grid.body[row["se_row"]][row["se_column"]])
            if not parameters:
                continue
            out["param_printed"] += 1
            stored = row.get("standard_error")
            if stored is not None and any(same_number(stored, value) for value in parameters):
                out["param_ok"] += 1
            elif stored is None:
                out["param_missing"] += 1
            elif len(out["param_bad"]) < 50:
                out["param_bad"].append({"doc": name[:30], "page": row.get("page"),
                                         "cell": str(cell)[:30], "stored": stored,
                                         "printed": parameters[:3]})
    return out


def rates(result: dict) -> dict:
    addressed = result["addressed"]
    printed = result["param_printed"]
    return {"value": result["value_ok"] / addressed if addressed else 0.0,
            "parameter": result["param_ok"] / printed if printed else 0.0,
            "addressed": addressed / result["table_rows"] if result["table_rows"] else 0.0}


def baseline_entry(result: dict) -> dict:
    """The stored baseline: both rates, their bases, and the documents they were measured on.

    The sample is stored with the rates so a later run measures the same documents. A rate that fell
    because a different set of papers was measured would be a false alarm.
    """
    return {**rates(result),
            "documents": result["documents_with_table_rows"],
            "rows": result["table_rows"],
            "sample": result["sample"]}


def below_baseline(baseline: dict | None, current: dict | None) -> list[str]:
    """Reasons value or parameter accuracy sits below the stored baseline, in words for the gate."""
    if not baseline or not current:
        return []
    reasons = []
    for field in ("value", "parameter"):
        was, now = baseline.get(field), current.get(field)
        if was is None or now is None:
            continue
        if now + 1e-9 < was:
            reasons.append(f"{field} accuracy fell from {100 * was:.1f}% to {100 * now:.1f}%")
    return reasons


def report(result: dict) -> str:
    rate = rates(result)
    lines = [
        f"# Accuracy by address, {result['measured']}", "",
        f"Documents with table rows: {result['documents_with_table_rows']}.",
        f"Rows: {result['rows']} (table {result['table_rows']}, prose {result['prose_rows']}, "
        f"vision {result['vision_rows']}).", "",
        f"- table rows carrying an address: {result['addressed']} of {result['table_rows']} "
        f"({100 * rate['addressed']:.1f}%); without {result['no_address']}",
        f"- level 1, value: {result['value_ok']} of {result['addressed']} "
        f"({100 * rate['value']:.1f}%)",
        f"- level 2, parameter: {result['param_ok']} of {result['param_printed']} printed parameters "
        f"({100 * rate['parameter']:.1f}%); printed but not stored {result['param_missing']}",
    ]
    if result["no_content"]:
        lines.append(f"- documents whose content could not be loaded: {len(result['no_content'])}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docs", nargs="*", help="document keys to measure (default: all)")
    parser.add_argument("--limit", type=int, help="measure only the N documents with the most rows")
    parser.add_argument("--json", default=str(RESULT), help="where to write the full result")
    args = parser.parse_args()
    result = measure(args.docs, args.limit)
    print(report(result))
    path = Path(args.json)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(f"\nwritten: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
