#!/usr/bin/env python
"""Promote staged PDFs into a RAG project's input prefix.

Copies PDFs from staging prefixes in R2 to rags/{project_id}/input-pdfs/ using the
application's naming convention, {sha256-of-content[:12]}_{basename}.pdf, and inserts
the matching documents rows so the project UI lists them.

Does NOT trigger Modal processing. That is a separate, explicit step.

Idempotent: a file whose target key already exists is skipped.

Usage
  python scripts/promote_staging_to_project.py --project-id <uuid> \
      --prefix _staging/full_text_paywall/ --prefix _staging/full_text_open_access/ \
      [--min-bytes 10240] [--workers 12] [--dry-run] [--no-db]
"""

import argparse
import hashlib
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3
import requests
from botocore.config import Config
from dotenv import load_dotenv

load_dotenv()

_S3 = None


def r2():
    global _S3
    if _S3 is None:
        _S3 = boto3.client(
            "s3",
            endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            region_name="auto",
            config=Config(max_pool_connections=64),
        )
    return _S3


def bucket():
    return os.environ.get("R2_BUCKET_NAME", "devchat-pdfs")


def supabase_headers():
    url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return url, {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def list_staging(prefixes, min_bytes):
    s3 = r2()
    pag = s3.get_paginator("list_objects_v2")
    items = []
    for p in prefixes:
        for page in pag.paginate(Bucket=bucket(), Prefix=p):
            for o in page.get("Contents", []):
                if o["Key"].lower().endswith(".pdf") and o["Size"] >= min_bytes:
                    items.append({"key": o["Key"], "size": o["Size"], "name": os.path.basename(o["Key"])})
    return items


def existing_targets(project_id):
    s3 = r2()
    pag = s3.get_paginator("list_objects_v2")
    keys = set()
    for page in pag.paginate(Bucket=bucket(), Prefix=f"rags/{project_id}/input-pdfs/"):
        for o in page.get("Contents", []):
            keys.add(o["Key"])
    return keys


def sha256_12(key):
    s3 = r2()
    h = hashlib.sha256()
    body = s3.get_object(Bucket=bucket(), Key=key)["Body"]
    while True:
        chunk = body.read(1 << 20)
        if not chunk:
            break
        h.update(chunk)
    return h.hexdigest()[:12]


def safe_base(name):
    return os.path.splitext(name.replace(" ", "_").replace("/", "_"))[0]


def promote_one(project_id, item):
    content_hash = sha256_12(item["key"])
    doc_id = f"{content_hash}_{safe_base(item['name'])}"
    target = f"rags/{project_id}/input-pdfs/{doc_id}.pdf"
    r2().copy_object(
        Bucket=bucket(),
        Key=target,
        CopySource={"Bucket": bucket(), "Key": item["key"]},
        ContentType="application/pdf",
        MetadataDirective="REPLACE",
        Metadata={
            "doc_id": doc_id,
            "content_hash": content_hash,
            "original_filename": item["name"],
            "project_id": project_id,
        },
    )
    row = {
        "rag_project_id": project_id,
        "filename": doc_id,
        "original_filename": item["name"],
        "file_size_bytes": item["size"],
        "mime_type": "application/pdf",
        "status": "pending",
        "r2_input_key": target,
        "metadata": {"content_hash": content_hash},
    }
    return target, row


def insert_rows(rows):
    if not rows:
        return 0
    url, headers = supabase_headers()
    headers["Prefer"] = "resolution=ignore-duplicates,return=minimal"
    inserted = 0
    for i in range(0, len(rows), 500):
        batch = rows[i:i + 500]
        r = requests.post(
            f"{url}/rest/v1/documents?on_conflict=rag_project_id,filename",
            headers=headers, json=batch, timeout=60,
        )
        if r.status_code >= 300:
            print(f"  insert failed ({r.status_code}): {r.text[:300]}")
            raise SystemExit(1)
        inserted += len(batch)
    return inserted


def sync_rows_from_r2(project_id):
    """Reconcile documents rows from the R2 project prefix (repair path)."""
    s3 = r2()
    prefix = f"rags/{project_id}/input-pdfs/"
    keys = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket(), Prefix=prefix):
        for o in page.get("Contents", []):
            if o["Key"].lower().endswith(".pdf"):
                keys.append(o)

    url, headers = supabase_headers()
    existing = set()
    step = 1000
    start = 0
    while True:
        h = dict(headers)
        h["Range"] = f"{start}-{start + step - 1}"
        r = requests.get(
            f"{url}/rest/v1/documents?rag_project_id=eq.{project_id}&select=filename",
            headers=h, timeout=60,
        )
        if r.status_code >= 300:
            raise SystemExit(r.text[:200])
        data = r.json()
        existing.update(d["filename"] for d in data)
        if len(data) < step:
            break
        start += step

    rows = []
    for o in keys:
        fn = os.path.basename(o["Key"])[:-4]
        parts = fn.split("_", 1)
        ch = parts[0] if len(parts) > 1 else ""
        orig = (parts[1] + ".pdf") if len(parts) > 1 else fn + ".pdf"
        if fn in existing:
            continue
        rows.append({
            "rag_project_id": project_id,
            "filename": fn,
            "original_filename": orig,
            "file_size_bytes": o["Size"],
            "mime_type": "application/pdf",
            "status": "pending",
            "r2_input_key": o["Key"],
            "metadata": {"content_hash": ch} if ch else {},
        })
    print(f"r2 pdfs: {len(keys)}; existing rows: {len(existing)}; to insert: {len(rows)}")
    insert_rows(rows)
    count = update_document_count(project_id)
    print(f"document_count now {count}")
    return count


def update_document_count(project_id):
    url, headers = supabase_headers()
    h = dict(headers)
    h["Prefer"] = "count=exact"
    h["Range"] = "0-0"
    r = requests.get(
        f"{url}/rest/v1/documents?rag_project_id=eq.{project_id}&select=id",
        headers=h, timeout=60,
    )
    count = 0
    content_range = r.headers.get("Content-Range", "")
    if "/" in content_range:
        count = int(content_range.split("/")[-1])
    elif r.status_code == 200:
        count = len(r.json())
    h2 = dict(headers)
    h2["Prefer"] = "return=minimal"
    requests.patch(
        f"{url}/rest/v1/rag_projects?id=eq.{project_id}",
        headers=h2, json={"document_count": count}, timeout=60,
    )
    return count


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project-id", required=True)
    ap.add_argument("--prefix", action="append", default=[], help="staging prefix (repeatable)")
    ap.add_argument("--min-bytes", type=int, default=10 * 1024)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-db", action="store_true", help="copy to R2 but do not insert rows")
    ap.add_argument("--sync-db-only", action="store_true", help="only reconcile documents rows from R2")
    args = ap.parse_args()

    if args.sync_db_only:
        sync_rows_from_r2(args.project_id)
        return

    if not args.prefix:
        ap.error("--prefix is required unless --sync-db-only is set")

    items = list_staging(args.prefix, args.min_bytes)
    total_bytes = sum(i["size"] for i in items)
    print(f"staging candidates: {len(items)} pdfs >= {args.min_bytes} bytes, {total_bytes/1e9:.2f} GB")

    present = existing_targets(args.project_id)
    print(f"already in project target prefix: {len(present)} objects")

    if args.dry_run:
        print("dry run: would hash, copy and index the candidates above; nothing written")
        return

    done = skipped = failed = 0
    rows = []

    def run(item):
        return promote_one(args.project_id, item)

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = [ex.submit(run, it) for it in items]
        for i, fut in enumerate(as_completed(futures), 1):
            try:
                target, row = fut.result()
            except Exception as e:
                failed += 1
                print(f"  FAILED: {e}", flush=True)
                continue
            if target in present:
                skipped += 1
            else:
                rows.append(row)
                done += 1
            if i % 100 == 0 or i == len(items):
                print(f"  [{i}/{len(items)}] {done} promoted, {skipped} skipped, {failed} failed", flush=True)

    rows = list({row["filename"]: row for row in rows}.values())
    print(f"copied in {time.time()-t0:.0f}s; writing {len(rows)} unique document rows", flush=True)
    if not args.no_db:
        inserted = insert_rows(rows)
        count = update_document_count(args.project_id)
        print(f"inserted {inserted} document rows; project document_count now {count}")

    print(f"done: {done} promoted, {skipped} skipped, {failed} failed")
    if failed:
        sys.exit(3)


if __name__ == "__main__":
    main()
