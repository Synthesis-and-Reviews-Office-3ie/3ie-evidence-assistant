"""Fill cell addresses on stored table rows that do not have one.

Most rows were written before the reader recorded where a cell sits. Their value is already stored and
the parsed table is already in the content cache, so the address can be recovered without calling a
model: find the cell whose printed number equals the stored coefficient at its printed precision, using
the row and column labels only to break a tie. A row is updated only when exactly one cell matches.

The write is one batched UPDATE over a VALUES list, because thousands of single-row REST calls exhaust
the small instance's disk budget.

    python scripts/backfill_addresses.py --dry-run
    python scripts/backfill_addresses.py
    python scripts/backfill_addresses.py --docs <doc_key> [<doc_key> ...]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import psycopg2  # noqa: E402
from psycopg2.extras import execute_values  # noqa: E402

from evaluation.usage_study import load_content  # noqa: E402
from src.extraction.table_estimates import (  # noqa: E402
    _holds,
    _merge_outcome,
    _narrow_by_labels,
    parse_number,
    table_units,
)
from src.extraction.table_rules import normalise_tables, reclassify_pipe_tables  # noqa: E402
from src.extraction.table_structure import parse_markdown_table  # noqa: E402

PROJECT = os.environ.get("RAG_PROJECT_ID") or "7efdc60e-e863-480c-929e-616574725e5f"
SOURCE = "tables_v1"
CACHE = ROOT / "evaluation" / "results" / "usage_study" / PROJECT / "content"
NUM = re.compile(r"[-−–]?\d[\d.,]*")
ROW = re.compile(r"row '([^']*)'")
COL = re.compile(r"column '([^']*)'")
TABLE_ID = re.compile(r"(extended\s+data\s+table|annex\s+table|appendix\s+table|table)\s+([a-z]?\d+)", re.I)

QUERY = """
SELECT id, doc_key, page, unit_index, effect_size, standard_error,
       table_number, text_position, outcome_name, treatment_arm
FROM public.effect_estimates
WHERE rag_project_id = %s AND source = %s AND cell_row IS NULL
"""

UPDATE = """
UPDATE public.effect_estimates AS e
SET unit_index = v.unit_index, cell_row = v.cell_row, cell_column = v.cell_column,
    se_row = v.se_row, se_column = v.se_column, source_cell = v.source_cell
FROM (VALUES %s) AS v(id, unit_index, cell_row, cell_column, se_row, se_column, source_cell)
WHERE e.id = v.id
"""


def table_id(text) -> str:
    match = TABLE_ID.search(str(text or ""))
    return f"{re.sub(r'\s+', ' ', match.group(1).lower())} {match.group(2).lower()}" if match else ""


def index_units(units):
    """Each unit's grid and a printed-number to cells map, so a value lookup is a dictionary hit."""
    indexed = []
    for unit in units:
        grid = parse_markdown_table(unit["text"])
        index: dict[float, list] = defaultdict(list)
        for row_index, row in enumerate(grid.body):
            for column_index, cell in enumerate(row):
                if column_index == 0:
                    continue
                for token in NUM.findall(str(cell)):
                    value = parse_number(token)
                    if value is not None:
                        index[round(value, 9)].append((row_index, column_index, str(cell)))
        indexed.append({"unit": unit, "grid": grid, "index": index})
    return indexed


def collapse(candidates, indexed):
    """One address when every candidate is the same printed cell seen through different views.

    A wide table is read whole and column by column, so one printed cell appears in both a split view
    and the whole-table view. Those are the same address, not a tie; the narrowest view is kept because
    it has fewest neighbouring cells to confuse a later read.
    """
    keys = {(row_index, column_index, cell) for _, row_index, column_index, cell in candidates}
    if len(keys) != 1:
        return None
    row_index, column_index, cell = keys.pop()
    same = [(u, r, c, text) for u, r, c, text in candidates
            if (r, c, text) == (row_index, column_index, cell)]
    unit = min((u for u, _, _, _ in same),
               key=lambda u: (len(indexed[u]["grid"].headers[-1]) if indexed[u]["grid"].headers else 0, u))
    return unit, row_index, column_index, cell


def locate(row, indexed):
    """The one cell that holds this row's coefficient, or None when none or several do."""
    value = row.get("effect_size")
    if value is None or not indexed:
        return None
    key = round(float(value), 9)
    position = str(row.get("text_position") or "")
    match_row = ROW.search(position)
    match_col = COL.search(position)
    row_label = match_row.group(1) if match_row else (row.get("outcome_name") or "")
    column_label = match_col.group(1) if match_col else ""
    arm = row.get("treatment_arm") or ""

    unit_index = row.get("unit_index")
    if unit_index is not None and unit_index < len(indexed):
        own = indexed[unit_index]["unit"]
        pool = [indexed[unit_index]]
        pool += [u for u in indexed if u["unit"]["page"] == own["page"]
                 and u["unit"]["table_index"] == own["table_index"] and u is not indexed[unit_index]]
    else:
        pool = [u for u in indexed if u["unit"]["page"] == row.get("page")]
        wanted = table_id(row.get("table_number"))
        if wanted:
            matching = [u for u in pool if table_id(u["unit"].get("caption")) == wanted]
            if matching:
                pool = matching

    # A split view is one arm column: the value is usually unique in it, and it is the narrowest
    # address. When exactly one split view holds the value once, that is the cell, whatever the
    # whole-table view repeats.
    split = []
    for entry in pool:
        if not entry["unit"].get("arm_hint"):
            continue
        hits = [(r, c) for r, c, _ in entry["index"].get(key, [])]
        if len(hits) > 1:
            hits = _narrow_by_labels(entry["grid"], hits, row_label, column_label, arm)
        if len(hits) == 1:
            r, c = hits[0]
            cell = next(text for rr, cc, text in entry["index"][key] if (rr, cc) == (r, c))
            split.append((entry["unit"]["unit_index"], r, c, cell))
    if len(split) == 1:
        return split[0]

    candidates = []
    for entry in pool:
        for row_index, column_index, cell in entry["index"].get(key, []):
            candidates.append((entry["unit"]["unit_index"], row_index, column_index, cell))
    unique = list({(u, r, c): (u, r, c, cell) for u, r, c, cell in candidates}.values())
    same_cell = collapse(unique, indexed)
    if same_cell:
        return same_cell
    if len(unique) == 1:
        return unique[0]
    if not unique:
        return None
    by_unit = defaultdict(list)
    for u, r, c, _ in unique:
        by_unit[u].append((r, c))
    narrowed = []
    for u, hits in by_unit.items():
        kept = _narrow_by_labels(indexed[u]["grid"], hits, row_label, column_label, arm)
        narrowed += [(u, r, c) for r, c in kept]
    find = {(u, r, c): cell for u, r, c, cell in unique}
    cells = [(u, r, c, find[(u, r, c)]) for u, r, c in narrowed]
    same_cell = collapse(cells, indexed)
    if same_cell:
        return same_cell
    return cells[0] if len(cells) == 1 else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="report what would change and write nothing")
    parser.add_argument("--docs", nargs="*", help="only these document keys")
    args = parser.parse_args()
    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        print("SUPABASE_DB_URL is not set", file=sys.stderr)
        return 1
    conn = psycopg2.connect(db_url, connect_timeout=20)
    try:
        with conn.cursor() as cur:
            cur.execute(QUERY, (PROJECT, SOURCE))
            columns = [d[0] for d in cur.description]
            rows = [dict(zip(columns, values)) for values in cur.fetchall()]
    finally:
        conn.close()
    if args.docs:
        wanted = set(args.docs)
        rows = [row for row in rows if row["doc_key"] in wanted]
    by_doc = defaultdict(list)
    for row in rows:
        by_doc[row["doc_key"]].append(row)
    print(f"unaddressed table rows: {len(rows)} in {len(by_doc)} documents")

    updates = []
    for name, doc_rows in by_doc.items():
        try:
            units = table_units(reclassify_pipe_tables(normalise_tables(load_content(PROJECT, name, CACHE))))
        except Exception as error:
            print(f"  ! {name[:50]}: content unavailable: {type(error).__name__}")
            continue
        indexed = index_units(units)
        found = 0
        for row in doc_rows:
            hit = locate(row, indexed)
            if not hit:
                continue
            unit_index, row_index, column_index, cell = hit
            se_row = se_column = None
            if row.get("standard_error") is not None and _holds(row["standard_error"], cell, signed=False):
                se_row, se_column = row_index, column_index
            updates.append((row["id"], unit_index, row_index, column_index, se_row, se_column,
                            str(cell)[:500]))
            found += 1
        print(f"  {name[:56]:56} {found:4}/{len(doc_rows)}")

    print(f"addressable: {len(updates)} of {len(rows)}")
    if args.dry_run or not updates:
        return 0
    conn = psycopg2.connect(db_url, connect_timeout=20)
    try:
        with conn, conn.cursor() as cur:
            execute_values(cur, UPDATE, updates, page_size=1000)
        print(f"updated: {len(updates)}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
