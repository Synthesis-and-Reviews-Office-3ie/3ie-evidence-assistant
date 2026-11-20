"""Repair a stored arm that repeats the column header or the outcome.

No model call and no re-extraction. Dry-run by default; `--write` updates the rows. The full old arm is
written to the undo log before any update.

    python scripts/fix_arms.py --docs <key> ... --undo-log <path>
    python scripts/fix_arms.py --docs <key> ... --write --undo-log <path>
"""
import argparse
import json
import os
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

from evaluation.arm_fix import PANEL, fixed_arm  # noqa: E402
from evaluation.graduation_gt import PROJECT_ID, load_overrides  # noqa: E402
from evaluation.outcome_gap_audit import mapped_and_all  # noqa: E402
from evaluation.stored_rows import fetch_all  # noqa: E402
from evaluation.usage_study import load_content  # noqa: E402
from src.extraction.table_estimates import table_units  # noqa: E402
from src.extraction.table_rules import normalise_tables, reclassify_pipe_tables  # noqa: E402
from src.extraction.table_structure import parse_markdown_table  # noqa: E402
from supabase import create_client  # noqa: E402

UPDATE = """
UPDATE public.effect_estimates AS e
SET treatment_arm = v.treatment_arm
FROM (VALUES %s) AS v(id, treatment_arm)
WHERE e.id = v.id::uuid
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--docs", nargs="*", help="document keys; default is the 49 study documents")
    ap.add_argument("--undo-log", required=True)
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
            Bucket=bucket, Prefix=f"rags/{PROJECT_ID}/input-pdfs/") for o in p.get("Contents", [])]
        _, all_docs = mapped_and_all(names, load_overrides())
        docs = sorted({d for ds in all_docs.values() for d in ds})

    sb = create_client(os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    rows = fetch_all(sb.table("effect_estimates")
                     .select("id,doc_key,page,unit_index,cell_row,cell_column,effect_size,outcome_name,treatment_arm")
                     .eq("rag_project_id", PROJECT_ID).eq("source", "tables_v1").in_("doc_key", docs))
    by_doc = {}
    for row in rows:
        by_doc.setdefault(row["doc_key"], []).append(row)

    updates, undo, changed = [], [], Counter()
    for name in docs:
        units = table_units(reclassify_pipe_tables(normalise_tables(
            load_content(PROJECT_ID, name, ROOT / "evaluation" / "results" / "usage_study" / PROJECT_ID / "content"))))
        for row in by_doc.get(name, []):
            ui, r, c = row.get("unit_index"), row.get("cell_row"), row.get("cell_column")
            if ui is None or r is None or c is None or ui >= len(units):
                continue
            unit = units[ui]
            grid = parse_markdown_table(unit["text"])
            if r >= len(grid.body) or c >= len(grid.body[r]):
                continue
            header = grid.headers[-1] if grid.headers else []
            column_header = str(header[c]) if c < len(header) else ""
            panel_match = PANEL.search(str(unit.get("caption") or ""))
            arm = fixed_arm(row.get("outcome_name"), row.get("treatment_arm"),
                            str(grid.body[r][0]), column_header,
                            f"Panel {panel_match.group(1)}" if panel_match else "")
            if arm == row.get("treatment_arm"):
                continue
            updates.append((row["id"], arm[:200]))
            undo.append({"id": row["id"], "doc_key": name, "page": row.get("page"),
                         "cell_row": r, "cell_column": c,
                         "outcome_name": row.get("outcome_name"), "old_arm": row.get("treatment_arm"),
                         "new_arm": arm, "row_label": str(grid.body[r][0]), "column_header": column_header})
            changed[name[:12]] += 1

    print(f"rows that would change: {len(updates)}")
    for name, count in changed.most_common(12):
        print(f"  {count:3d}  {name}")
    path = Path(args.undo_log)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record, default=str) + "\n" for record in undo), encoding="utf-8")
    print(f"undo log: {len(undo)} rows at {path}")
    for record in undo[:8]:
        print(f"  {record['doc_key'][:12]} p{record['page']} outcome={str(record['outcome_name'])[:28]!r} "
              f"arm {str(record['old_arm'])[:28]!r} -> {record['new_arm'][:28]!r}")
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
