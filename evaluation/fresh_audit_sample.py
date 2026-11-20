"""Draw a fresh audit sample of stored cells from documents a previous sample did not use.

Run after a re-extraction, so every row carries the reader's current output and the two-axis role
flag. Documents named by an earlier `fresh_audit_sample*.csv` are excluded, so the sample tests the
reader on papers it has not been tuned against. Rows are spread across documents, one at a time, so
one long appendix cannot fill the sample.

    python evaluation/fresh_audit_sample.py --n 60 --seed 20261120
"""

from __future__ import annotations

import argparse
import csv
import glob
import os
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from evaluation.stored_rows import fetch_all  # noqa: E402
from supabase import create_client  # noqa: E402

PROJECT = "7efdc60e-e863-480c-929e-616574725e5f"
SOURCE = "tables_v1"
COLUMNS = ["doc_key", "page", "table", "cell", "outcome", "arm", "subgroup", "estimation_method",
           "value", "SE", "row_role", "column_role", "keep_effect"]


def used_documents() -> set:
    used = set()
    for path in glob.glob(str(ROOT / "evaluation/results/fresh_audit_sample*.csv")):
        for row in csv.DictReader(open(path, encoding="utf-8")):
            used.add(row.get("doc_key"))
    return used


def cell_address(row) -> str:
    if row.get("cell_row") is None or row.get("cell_column") is None:
        return ""
    return f"r{row['cell_row']}c{row['cell_column']}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--seed", type=int, default=20261120)
    ap.add_argument("--out", default="evaluation/results/final_audit_sample_2026-11-20.csv")
    args = ap.parse_args()

    client = create_client(os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    rows = fetch_all(client.table("effect_estimates")
                     .select("doc_key,page,table_number,cell_row,cell_column,outcome_name,treatment_arm,"
                             "subgroup,estimation_method,effect_size,standard_error,row_role,column_role,"
                             "keep_effect,literal_text,text_position")
                     .eq("rag_project_id", PROJECT).eq("source", SOURCE))
    used = used_documents()
    candidates = [r for r in rows if r["doc_key"] not in used and r["effect_size"] is not None
                  and r["cell_row"] is not None]
    by_doc = defaultdict(list)
    for row in candidates:
        by_doc[row["doc_key"]].append(row)

    rng = random.Random(args.seed)
    docs = sorted(by_doc)
    rng.shuffle(docs)
    for doc in docs:
        rng.shuffle(by_doc[doc])

    picked, index = [], 0
    while len(picked) < args.n and any(by_doc[d] for d in docs):
        for doc in docs:
            if len(picked) >= args.n:
                break
            if by_doc[doc]:
                picked.append(by_doc[doc].pop())
        index += 1

    out = ROOT / args.out
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for row in picked:
            writer.writerow({
                "doc_key": row["doc_key"], "page": row.get("page"), "table": row.get("table_number"),
                "cell": cell_address(row), "outcome": row.get("outcome_name"), "arm": row.get("treatment_arm"),
                "subgroup": row.get("subgroup"), "estimation_method": row.get("estimation_method"),
                "value": row["effect_size"], "SE": row.get("standard_error"),
                "row_role": row.get("row_role"), "column_role": row.get("column_role"),
                "keep_effect": row.get("keep_effect")})
    print(f"candidates {len(candidates)} across {len(by_doc)} unused documents; wrote {len(picked)} to {out}")
    print("documents used:", ", ".join(sorted({r['doc_key'][:12] for r in picked})))


if __name__ == "__main__":
    main()
