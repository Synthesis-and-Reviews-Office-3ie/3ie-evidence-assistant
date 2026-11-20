"""Combine the labels of rows a dedupe removed into the row that survived at the same cell.

The dedupe kept one row and deleted the others. When the deleted rows carried a different part of the
label (the table subject and the row subgroup), this restores both as "A - B" on the survivor. It reads
the dedupe undo log, so it can be run after the delete. Dry-run by default.

    python scripts/merge_dedupe_labels.py --undo-log evaluation/results/dedupe_undo_ten_2026-11-20.jsonl \
        --out-log evaluation/results/label_merge_undo_ten_2026-11-20.jsonl
    ... --write
"""
import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import psycopg2  # noqa: E402
from psycopg2.extras import execute_values  # noqa: E402

from evaluation.dedupe import combined_labels, should_combine  # noqa: E402
from evaluation.stored_rows import fetch_all  # noqa: E402
from supabase import create_client  # noqa: E402

PROJECT = "7efdc60e-e863-480c-929e-616574725e5f"
UPDATE = """
UPDATE public.effect_estimates AS e
SET outcome_name = v.outcome_name, treatment_arm = v.treatment_arm
FROM (VALUES %s) AS v(id, outcome_name, treatment_arm)
WHERE e.id = v.id::uuid
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--undo-log", required=True)
    ap.add_argument("--out-log", required=True)
    ap.add_argument("--doc", help="only this document, by full key or prefix")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    removed = [json.loads(line) for line in Path(args.undo_log).read_text(encoding="utf-8").splitlines()]
    removed = [row for row in removed if row.get("doc_key")]
    if args.doc:
        removed = [row for row in removed if row["doc_key"].startswith(args.doc)]
    docs = sorted({row["doc_key"] for row in removed})
    sb = create_client(os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    rows = fetch_all(sb.table("effect_estimates")
                     .select("id,doc_key,unit_index,cell_row,cell_column,effect_size,outcome_name,treatment_arm")
                     .eq("rag_project_id", PROJECT).eq("source", "tables_v1").in_("doc_key", docs))
    groups = defaultdict(list)
    removed_ids = {row["id"] for row in removed}
    for row in rows:
        groups[(row["doc_key"], row["unit_index"], row["cell_row"], row["cell_column"],
                row.get("effect_size"))].append(row)
    for row in removed:
        key = (row["doc_key"], row.get("unit_index"), row.get("cell_row"), row.get("cell_column"),
               row.get("effect_size"))
        groups[key].append(row)

    updates, undo = [], []
    for group in groups.values():
        survivors = [row for row in group if row["id"] not in removed_ids]
        if len(survivors) != 1:
            continue
        keep = survivors[0]
        if not should_combine([row.get("outcome_name") for row in group]):
            continue
        outcome = combined_labels([row.get("outcome_name") for row in group])
        arm = combined_labels([row.get("treatment_arm") for row in group])
        if outcome == keep.get("outcome_name") and arm == keep.get("treatment_arm"):
            continue
        updates.append((keep["id"], outcome[:500], arm[:200]))
        undo.append({"id": keep["id"], "doc_key": keep["doc_key"],
                     "old_outcome": keep.get("outcome_name"), "old_arm": keep.get("treatment_arm"),
                     "new_outcome": outcome, "new_arm": arm})
    print(f"rows that would gain a combined label: {len(updates)}")
    for record in undo[:10]:
        print(f"  {record['doc_key'][:12]} {str(record['old_outcome'])[:26]!r} -> "
              f"{str(record['new_outcome'])[:40]!r}")
    path = Path(args.out_log)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record, default=str) + "\n" for record in undo), encoding="utf-8")
    print(f"undo log: {len(undo)} rows at {path}")
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
