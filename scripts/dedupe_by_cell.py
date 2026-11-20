"""Remove stored rows that point to the same printed cell and value, keeping one.

Duplicate means the same document, the same table view, the same cell address and the same coefficient.
Rows with the same cell but a different value are different estimates from a multi-pair cell and are kept.
The keeper is chosen by `evaluation.dedupe.keeper` and the full removed rows are written to an undo log
before any delete.

    python scripts/dedupe_by_cell.py --docs <key> [<key> ...] --undo-log <path>
    python scripts/dedupe_by_cell.py --docs <key> ... --write --undo-log <path>
"""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import boto3  # noqa: E402
import psycopg2  # noqa: E402
from psycopg2.extras import execute_values  # noqa: E402

from evaluation.dedupe import combined_labels, keeper, should_combine  # noqa: E402
from evaluation.graduation_gt import PROJECT_ID, load_overrides  # noqa: E402
from evaluation.outcome_gap_audit import mapped_and_all  # noqa: E402
from evaluation.stored_rows import fetch_all  # noqa: E402
from supabase import create_client  # noqa: E402

DELETE = "DELETE FROM public.effect_estimates WHERE id = ANY(%s::uuid[])"


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
    rows = fetch_all(sb.table("effect_estimates").select("*")
                     .eq("rag_project_id", PROJECT_ID).eq("source", "tables_v1").in_("doc_key", docs))
    groups = defaultdict(list)
    for row in rows:
        if row.get("cell_row") is None or row.get("cell_column") is None or row.get("unit_index") is None:
            continue
        groups[(row["doc_key"], row["unit_index"], row["cell_row"], row["cell_column"],
                row.get("effect_size"))].append(row)

    removed, labels, by_doc = [], [], Counter()
    for group in groups.values():
        if len(group) < 2:
            continue
        keep = keeper(group)
        if should_combine([row.get("outcome_name") for row in group]):
            outcome = combined_labels([row.get("outcome_name") for row in group])
            arm = combined_labels([row.get("treatment_arm") for row in group])
            if outcome != keep.get("outcome_name") or arm != keep.get("treatment_arm"):
                labels.append({"id": keep["id"], "outcome_name": outcome, "treatment_arm": arm})
        for row in group:
            if row["id"] == keep["id"]:
                continue
            removed.append(row)
            by_doc[row["doc_key"][:12]] += 1

    print(f"rows that would be removed: {len(removed)}; labels combined: {len(labels)}")
    for name, count in by_doc.most_common(12):
        print(f"  {count:4d}  {name}")
    path = Path(args.undo_log)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps({"kind": "remove", **row}, default=str) + "\n" for row in removed)
                    + "".join(json.dumps({"kind": "label", **row}, default=str) + "\n" for row in labels),
                    encoding="utf-8")
    print(f"undo log: {len(removed)} removed and {len(labels)} label changes at {path}")
    if args.write and (removed or labels):
        conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"], connect_timeout=20)
        try:
            with conn, conn.cursor() as cur:
                if labels:
                    execute_values(cur, "UPDATE public.effect_estimates AS e "
                                        "SET outcome_name = v.outcome_name, treatment_arm = v.treatment_arm "
                                        "FROM (VALUES %s) AS v(id, outcome_name, treatment_arm) "
                                        "WHERE e.id = v.id::uuid",
                                   [(row["id"], row["outcome_name"], row["treatment_arm"]) for row in labels],
                                   page_size=1000)
                if removed:
                    execute_values(cur, "DELETE FROM public.effect_estimates AS e USING (VALUES %s) AS v(id) "
                                        "WHERE e.id = v.id::uuid",
                                   [(row["id"],) for row in removed], page_size=1000)
            print(f"deleted {len(removed)} rows; combined labels on {len(labels)}")
        finally:
            conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
