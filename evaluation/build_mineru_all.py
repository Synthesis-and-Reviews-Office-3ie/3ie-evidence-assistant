"""Build a project holding MinerU parses for all 49 study documents.

The MinerU rows for the 43 mapped documents were overwritten when the shadow became the union
project. Their raw parses are saved under the shadow's outputs/parses/mineru/, so this copies
those into a fresh project's outputs/json/ and copies all 49 PDFs across. The 6 companion
documents still need a MinerU parse, which the caller runs afterwards.

    python evaluation/build_mineru_all.py [--name "..."] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import requests  # noqa: E402

from evaluation.graduation_gt import PROJECT_ID, load_overrides  # noqa: E402
from evaluation.outcome_gap_audit import mapped_and_all  # noqa: E402

SHADOW = "a66764e7-2410-427f-ac3a-618c196e9115"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="Graduation MinerU (all)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    import boto3
    s3 = boto3.client(
        "s3", endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")
    bucket = os.environ.get("R2_BUCKET_NAME", "devchat-pdfs")
    url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    names = [o["Key"].split("/")[-1] for p in s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix=f"rags/{PROJECT_ID}/input-pdfs/") for o in p.get("Contents", [])]
    mapped, all_docs = mapped_and_all(names, load_overrides())
    docs = sorted({Path(d).stem for ds in all_docs.values() for d in ds})
    saved_mineru = {o["Key"].split("/")[-1][:-5] for p in s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix=f"rags/{SHADOW}/outputs/parses/mineru/") for o in p.get("Contents", [])}
    print(f"documents: {len(docs)}; MinerU parses available: {len(saved_mineru)}; need parse: {len(set(docs) - saved_mineru)}")
    if args.dry_run:
        return

    src = requests.get(f"{url}/rest/v1/rag_projects?id=eq.{PROJECT_ID}&select=*", headers=headers).json()[0]
    row = {k: v for k, v in src.items() if k not in ("id", "created_at", "updated_at")}
    row.update({"name": args.name, "slug": f"graduation-mineru-all-{int(time.time())}",
                "is_public": False, "document_count": 0, "chunk_count": 0,
                "status": row.get("status") or "ready"})
    created = requests.post(f"{url}/rest/v1/rag_projects?select=id",
                            headers={**headers, "Prefer": "return=representation"}, json=row, timeout=60)
    if created.status_code >= 300:
        raise SystemExit(created.text[:300])
    pid = created.json()[0]["id"]
    print(f"project: {pid}")

    # Copy all 49 PDFs, so the 6 without a MinerU parse can be parsed in this project.
    for name in names:
        stem = Path(name).stem
        if stem not in docs:
            continue
        s3.copy_object(Bucket=bucket, CopySource={"Bucket": bucket, "Key": f"rags/{PROJECT_ID}/input-pdfs/{name}"},
                       Key=f"rags/{pid}/input-pdfs/{name}")

    # Reuse the saved MinerU parses as this project's canonical outputs.
    rows = []
    for doc in docs:
        raw_key = f"rags/{SHADOW}/outputs/parses/mineru/{doc}.json"
        try:
            body = s3.get_object(Bucket=bucket, Key=raw_key)["Body"].read()
            s3.put_object(Bucket=bucket, Key=f"rags/{pid}/outputs/json/{doc}.json", Body=body,
                          ContentType="application/json")
        except Exception:
            print(f"  no saved MinerU parse for {doc}")
        rows.append({"rag_project_id": pid, "filename": doc, "original_filename": doc + ".pdf",
                     "file_size_bytes": 0, "mime_type": "application/pdf", "status": "pending",
                     "r2_input_key": f"rags/{pid}/input-pdfs/{doc}.pdf"})
    ins = requests.post(f"{url}/rest/v1/documents?on_conflict=rag_project_id,filename",
                        headers={**headers, "Prefer": "resolution=ignore-duplicates,return=minimal"},
                        json=rows, timeout=120)
    if ins.status_code >= 300:
        raise SystemExit(f"documents insert failed: {ins.text[:300]}")
    print(json.dumps({"project": pid, "documents": len(docs), "copied_parses": len(docs) - len(set(docs) - saved_mineru)}))


if __name__ == "__main__":
    main()
