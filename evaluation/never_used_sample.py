"""Draw 60 random cells from the documents no sample has used, for a page-checked audit.

Run after the never-used documents are re-extracted, so each row carries the current reader output.
The rows are for a person to check against the printed page; nothing is classified here.

    python evaluation/never_used_sample.py --n 60 --seed 20261121
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from evaluation.stored_rows import fetch_all  # noqa: E402
from supabase import create_client  # noqa: E402

PROJECT = "7efdc60e-e863-480c-929e-616574725e5f"
SOURCE = "tables_v1"
COLUMNS = ["doc_key", "page", "table", "cell", "outcome", "arm", "subgroup", "value", "SE",
           "row_role", "column_role", "keep_effect"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--seed", type=int, default=20261121)
    ap.add_argument("--keys", default=r"C:\Users\LUCASS~1\AppData\Local\Temp\kilo\never_used.json")
    ap.add_argument("--out", default="evaluation/results/never_used_sample_2026-11-20.csv")
    args = ap.parse_args()

    keys = set(json.loads(Path(args.keys).read_text(encoding="utf-8")))
    client = create_client(os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    rows = fetch_all(client.table("effect_estimates")
                     .select("doc_key,page,table_number,cell_row,cell_column,outcome_name,treatment_arm,"
                             "subgroup,effect_size,standard_error,row_role,column_role,keep_effect")
                     .eq("rag_project_id", PROJECT).eq("source", SOURCE))
    candidates = [r for r in rows if r["doc_key"] in keys and r["effect_size"] is not None
                  and r["cell_row"] is not None]
    by_doc = {}
    for r in candidates:
        by_doc.setdefault(r["doc_key"], []).append(r)

    rng = random.Random(args.seed)
    docs = sorted(by_doc)
    rng.shuffle(docs)
    for d in docs:
        rng.shuffle(by_doc[d])
    picked = []
    while len(picked) < args.n and any(by_doc[d] for d in docs):
        for d in docs:
            if len(picked) >= args.n:
                break
            if by_doc[d]:
                picked.append(by_doc[d].pop())

    out = ROOT / args.out
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for r in picked:
            writer.writerow({
                "doc_key": r["doc_key"], "page": r.get("page"), "table": r.get("table_number"),
                "cell": f"r{r['cell_row']}c{r['cell_column']}", "outcome": r.get("outcome_name"),
                "arm": r.get("treatment_arm"), "subgroup": r.get("subgroup"),
                "value": r["effect_size"], "SE": r.get("standard_error"),
                "row_role": r.get("row_role"), "column_role": r.get("column_role"),
                "keep_effect": r.get("keep_effect")})
    print(f"candidates {len(candidates)} across {len(by_doc)} documents; wrote {len(picked)} to {out}")
    print("documents:", ", ".join(sorted({r['doc_key'][:12] for r in picked})))


if __name__ == "__main__":
    main()
