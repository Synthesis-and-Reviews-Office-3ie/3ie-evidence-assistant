#!/usr/bin/env python
"""Create a shadow RAG project holding the 43 ground-truth graduation papers.

The live graduation project already holds Docling parses. To compare parsers without
touching them, this copies the study documents (server-side in R2) into a new project,
where a different parser can run. It copies files and inserts the project row only; it
never runs a parser.

    python scripts/make_graduation_shadow.py --name "Graduation MinerU shadow" --dry-run
    python scripts/make_graduation_shadow.py --name "Graduation MinerU shadow"
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import boto3  # noqa: E402
import requests  # noqa: E402

from evaluation.graduation_gt import PROJECT_ID, study_to_document  # noqa: E402


def r2():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def bucket():
    return os.environ.get("R2_BUCKET_NAME", "devchat-pdfs")


def supabase():
    url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return url, {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def input_names(client, project_id):
    pag = client.get_paginator("list_objects_v2")
    prefix = f"rags/{project_id}/input-pdfs/"
    return [o["Key"].split("/")[-1] for p in pag.paginate(Bucket=bucket(), Prefix=prefix)
            for o in p.get("Contents", [])]


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "shadow"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--name", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    client = r2()
    names = input_names(client, PROJECT_ID)
    mapping = study_to_document(names)
    docs = sorted({d for d in mapping.values() if d})
    print(f"ground-truth studies: {len(mapping)}; distinct documents: {len(docs)}")
    for sid, doc in sorted(mapping.items()):
        if not doc:
            print(f"  UNMAPPED study {sid}")
    if args.dry_run:
        for d in docs:
            print("  copy", d)
        print("dry run: nothing written")
        return

    url, headers = supabase()
    src = requests.get(
        f"{url}/rest/v1/rag_projects?id=eq.{PROJECT_ID}&select=*", headers=headers, timeout=60
    ).json()
    if not src:
        raise SystemExit(f"source project not found: {PROJECT_ID}")

    row = {k: v for k, v in src[0].items() if k not in ("id", "created_at", "updated_at")}
    row.update({
        "name": args.name,
        "slug": f"{slugify(args.name)}-{int(time.time())}",
        "is_public": False,
        "document_count": 0,
        "chunk_count": 0,
        "status": row.get("status") or "ready",
    })
    created = requests.post(
        f"{url}/rest/v1/rag_projects?select=id",
        headers={**headers, "Prefer": "return=representation"},
        json=row, timeout=60,
    )
    if created.status_code >= 300:
        raise SystemExit(f"project insert failed ({created.status_code}): {created.text[:300]}")
    shadow_id = created.json()[0]["id"]
    print(f"shadow project: {shadow_id}")

    copied = 0
    for name in docs:
        client.copy_object(
            Bucket=bucket(),
            CopySource={"Bucket": bucket(), "Key": f"rags/{PROJECT_ID}/input-pdfs/{name}"},
            Key=f"rags/{shadow_id}/input-pdfs/{name}",
        )
        copied += 1
    print(f"copied {copied} documents into rags/{shadow_id}/input-pdfs/")
    print(f"SHADOW_PROJECT_ID {shadow_id}")


if __name__ == "__main__":
    main()
