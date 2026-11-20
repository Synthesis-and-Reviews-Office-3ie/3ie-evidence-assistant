"""Apply the outcome-in-columns rule to stored rows, with an undo record written before any update.

No model call and no re-extraction: the row's unit gives the row label and column header, and the
row's cell address says which cell it was read from. Dry-run by default.

    python scripts/backfill_outcomes.py --undo-log evaluation/results/outcome_backfill_undo.jsonl
    python scripts/backfill_outcomes.py --write --undo-log evaluation/results/outcome_backfill_undo.jsonl

The undo log is one JSON object per line with the id and the old and new outcome and arm, so a run can
be reversed exactly. It is written before the update, and it is written on a dry run too.
"""
import argparse
import json
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
import psycopg2  # noqa: E402
from psycopg2.extras import execute_values  # noqa: E402

from evaluation.graduation_gt import PROJECT_ID, load_overrides  # noqa: E402
from evaluation.outcome_gap_audit import mapped_and_all  # noqa: E402
from evaluation.stored_rows import fetch_all  # noqa: E402
from evaluation.usage_study import load_content  # noqa: E402
from src.extraction.table_estimates import table_units  # noqa: E402
from src.extraction.table_rules import normalise_tables, reclassify_pipe_tables  # noqa: E402
from src.extraction.table_structure import (  # noqa: E402
    header_name, outcome_in_columns, parse_markdown_table,
)
from supabase import create_client  # noqa: E402

PROJECT = PROJECT_ID
CACHE = ROOT / "evaluation" / "results" / "usage_study" / PROJECT / "content"
PANEL = re.compile(r"panel\s+([a-z0-9]+)", re.I)
UPDATE = """
UPDATE public.effect_estimates AS e
SET outcome_name = v.outcome_name, treatment_arm = v.treatment_arm
FROM (VALUES %s) AS v(id, outcome_name, treatment_arm)
WHERE e.id = v.id::uuid
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help="apply the update; default is a dry run")
    ap.add_argument("--docs", nargs="*", help="document keys; default is the 49 study documents")
    ap.add_argument("--undo-log", help="write the id and old/new names here before any update")
    args = ap.parse_args()

    if args.docs:
        docs = sorted(set(args.docs))
    else:
        bucket = os.environ.get("R2_BUCKET_NAME", "devchat-pdfs")
        s3 = boto3.client(
            "s3", endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")
        names = [o["Key"].split("/")[-1] for p in s3.get_paginator("list_objects_v2").paginate(
            Bucket=bucket, Prefix=f"rags/{PROJECT}/input-pdfs/") for o in p.get("Contents", [])]
        _, all_docs = mapped_and_all(names, load_overrides())
        docs = sorted({d for ds in all_docs.values() for d in ds})

    sb = create_client(os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    rows = fetch_all(sb.table("effect_estimates")
                     .select("id,doc_key,page,unit_index,cell_row,cell_column,outcome_name,treatment_arm")
                     .eq("rag_project_id", PROJECT).eq("source", "tables_v1").in_("doc_key", docs))
    by_doc = {}
    for row in rows:
        by_doc.setdefault(row["doc_key"], []).append(row)

    updates, undo = [], []
    changed = Counter()
    for name in docs:
        units = table_units(reclassify_pipe_tables(normalise_tables(load_content(PROJECT, name, CACHE))))
        for row in by_doc.get(name, []):
            ui, r, c = row.get("unit_index"), row.get("cell_row"), row.get("cell_column")
            if ui is None or r is None or c is None or ui >= len(units):
                continue
            unit = units[ui]
            if unit.get("whole_of_views") or not unit.get("arm_hint"):
                continue
            grid = parse_markdown_table(unit["text"])
            if r >= len(grid.body) or c >= len(grid.body[r]):
                continue
            row_label = str(grid.body[r][0]).strip()
            header = str(unit["arm_hint"]).strip()
            if not outcome_in_columns(row_label, header):
                continue
            if str(row.get("outcome_name") or "").strip() != row_label:
                continue
            outcome = header_name(header)
            panel = PANEL.search(str(unit.get("caption") or ""))
            if panel:
                outcome = f"Panel {panel.group(1)}: {outcome}"
            if outcome == row.get("outcome_name") and row_label == row.get("treatment_arm"):
                continue
            updates.append((row["id"], outcome[:500], row_label[:200]))
            undo.append({"id": row["id"], "doc_key": name, "page": row.get("page"),
                         "old_outcome": row.get("outcome_name"), "old_arm": row.get("treatment_arm"),
                         "new_outcome": outcome, "new_arm": row_label})
            changed[name[:12]] += 1

    print(f"rows that would change: {len(updates)}")
    for name, count in changed.most_common(12):
        print(f"  {count:3d}  {name}")
    if args.undo_log:
        path = Path(args.undo_log)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(record) + "\n" for record in undo), encoding="utf-8")
        print(f"undo log: {len(undo)} records at {path}")
    if args.write and updates:
        conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"], connect_timeout=20)
        try:
            with conn, conn.cursor() as cur:
                execute_values(cur, UPDATE, updates, page_size=1000)
            print(f"updated {len(updates)} rows")
        finally:
            conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
