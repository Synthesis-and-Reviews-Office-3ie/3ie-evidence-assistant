"""Export every effect_estimates row for a project to JSONL with stable paging and a completeness check.

Paging without an order repeats and omits rows (a previous snapshot had 32,581 lines but only 24,704 unique
ids). This orders by id, and fails if the unique id count does not equal the row count.
"""
import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="7efdc60e-e863-480c-929e-616574725e5f")
    ap.add_argument("--out", required=True)
    ap.add_argument("--page", type=int, default=1000)
    args = ap.parse_args()
    sb = create_client(os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    rows, seen, offset = [], set(), 0
    while True:
        batch = (sb.table("effect_estimates").select("*").eq("rag_project_id", args.project)
                 .order("id").range(offset, offset + args.page - 1).execute().data)
        for r in batch:
            rows.append(r)
            seen.add(r["id"])
        if len(batch) < args.page:
            break
        offset += args.page
    out = Path(args.out)
    with out.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, default=str) + "\n")
    print(f"rows {len(rows)} unique ids {len(seen)} -> {out}")
    if len(seen) != len(rows):
        raise SystemExit(f"snapshot incomplete: {len(rows)} rows but {len(seen)} unique ids")


if __name__ == "__main__":
    main()
