"""Cell-address recall: a key value counts only when a stored row's address is the cell that prints it.

The hand key's `Source` records the page, the table number and the table label. For each key row this
finds the parsed table on that page (falling back to the label, then the number, because the key's page
is a printed page and the parsed page is the PDF page), the cell in that table that prints the value,
and whether any stored row for the study carries that cell as its address.

    python evaluation/cell_recall.py

Read-only; no model call.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import boto3  # noqa: E402

from evaluation.accuracy import _units  # noqa: E402
from evaluation.graduation_gt import PROJECT_ID, load_key, load_overrides  # noqa: E402
from evaluation.outcome_gap_audit import mapped_and_all  # noqa: E402
from evaluation.outcome_taxonomy import categories  # noqa: E402
from evaluation.stored_rows import fetch_all  # noqa: E402
from evaluation.three_way_eval import num  # noqa: E402
from src.extraction.table_estimates import _holds  # noqa: E402
from src.extraction.table_structure import parse_markdown_table  # noqa: E402
from supabase import create_client  # noqa: E402

PAGE = re.compile(r"page:\s*(\d+)", re.I)
TABLE = re.compile(r"table:\s*(\d+)", re.I)
LABEL = re.compile(r"table label:\s*(.+)", re.I)
TABLE_IN_CAPTION = re.compile(r"table\s+([a-z]?\d+)", re.I)


def _label_matches(unit, label):
    return bool(label) and label.strip().lower()[:24] in str(unit.get("caption") or "").lower()


def _number_matches(unit, table_no):
    found = TABLE_IN_CAPTION.search(str(unit.get("caption") or ""))
    if not found or table_no is None:
        return False
    digits = re.sub(r"\D", "", found.group(1))
    return bool(digits) and int(digits) == int(table_no)


def _page_matches(unit, page, table_no, label):
    caption = str(unit.get("caption") or "")
    found = TABLE_IN_CAPTION.search(caption)
    if found and table_no is not None:
        digits = re.sub(r"\D", "", found.group(1))
        if digits and int(digits) == int(table_no):
            return True
    if _label_matches(unit, label):
        return True
    return (table_no is not None and unit.get("table_index") is not None and not found
            and int(unit["table_index"]) + 1 == int(table_no))


def measure(project: str = PROJECT_ID) -> Counter:
    bucket = os.environ.get("R2_BUCKET_NAME", "devchat-pdfs")
    s3 = boto3.client(
        "s3", endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")
    names = [o["Key"].split("/")[-1] for p in s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix=f"rags/{project}/input-pdfs/") for o in p.get("Contents", [])]
    _, all_docs = mapped_and_all(names, load_overrides())
    docs = sorted({d for ds in all_docs.values() for d in ds})
    sb = create_client(os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    rows = fetch_all(sb.table("effect_estimates")
                     .select("doc_key,unit_index,cell_row,cell_column,se_row,se_column,"
                             "effect_size,standard_error")
                     .eq("rag_project_id", project).eq("source", "tables_v1").in_("doc_key", docs))
    by_doc: dict[str, list] = {}
    for row in rows:
        by_doc.setdefault(row["doc_key"], []).append(row)
    units_by_doc = {}
    for doc in docs:
        try:
            units_by_doc[doc] = _units(project, doc)
        except Exception:
            units_by_doc[doc] = []

    counts = Counter()
    for _, gt in load_key().iterrows():
        cats = categories(str(gt.get("Outcome name") or "")) - {"noise"}
        if not cats or cats == {"other"}:
            continue
        value = num(gt.get("Coeff reg"))
        if value is None:
            continue
        se = num(gt.get("SE reg"))
        source = str(gt.get("Source") or "")
        counts["key"] += 1
        if se is not None:
            counts["se_total"] += 1
        page_match, table_match, label_match = PAGE.search(source), TABLE.search(source), LABEL.search(source)
        page = int(page_match.group(1)) if page_match else None
        table_no = int(table_match.group(1)) if table_match else None
        label = label_match.group(1).strip() if label_match else ""
        study_units = [(doc, unit) for doc in all_docs.get(gt.get("sid"), [])
                       for unit in units_by_doc.get(doc, [])]
        candidates = [(doc, unit) for doc, unit in study_units
                      if (page is None or unit.get("page") == page)
                      and _page_matches(unit, page, table_no, label)]
        via = "page"
        if not candidates:
            candidates = [(doc, unit) for doc, unit in study_units if _label_matches(unit, label)]
            via = "label"
        if not candidates:
            candidates = [(doc, unit) for doc, unit in study_units if _number_matches(unit, table_no)]
            via = "number"
        if not candidates:
            counts["no_table"] += 1
            continue
        counts["table"] += 1
        counts[f"table_by_{via}"] += 1
        value_seen = se_seen = value_found = se_found = False
        for doc, unit in candidates:
            grid = parse_markdown_table(unit["text"])
            value_cells = [(r, c) for r, row in enumerate(grid.body) for c, cell in enumerate(row)
                           if c > 0 and _holds(value, cell)]
            se_cells = [(r, c) for r, row in enumerate(grid.body) for c, cell in enumerate(row)
                        if c > 0 and se is not None and _holds(se, cell, signed=False)]
            value_seen = value_seen or bool(value_cells)
            se_seen = se_seen or bool(se_cells)
            for row in by_doc.get(doc, []):
                if row.get("unit_index") != unit.get("unit_index"):
                    continue
                value_found = value_found or (row.get("cell_row"), row.get("cell_column")) in value_cells
                se_found = se_found or (se is not None
                                        and (row.get("se_row"), row.get("se_column")) in se_cells)
        if value_seen:
            counts["value_in_table"] += 1
            counts["value_address"] += 1 if value_found else 0
        if se is not None and se_seen:
            counts["se_in_table"] += 1
            counts["se_address"] += 1 if se_found else 0
    return counts


def report(counts: Counter) -> str:
    return "\n".join([
        f"key values: {counts['key']}",
        f"table matched: {counts['table']} (page {counts['table_by_page']}, label "
        f"{counts['table_by_label']}, number {counts['table_by_number']}); no table "
        f"{counts['no_table']}",
        f"cell-address coefficient: {counts['value_address']}/{counts['key']}; "
        f"{counts['value_address']}/{counts['value_in_table']} of those printed in the named table",
        f"cell-address SE: {counts['se_address']}/{counts['se_total']}; "
        f"{counts['se_address']}/{counts['se_in_table']} of those printed in the named table",
    ])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=PROJECT_ID)
    args = ap.parse_args()
    print(report(measure(args.project)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
