"""Re-extract every source at one commit, so the parser comparison is not confounded by reader versions.

Prune is on: rows are replaced, not carried forward, so every stored row comes from the current code.
Run from a pinned commit and record it with the result.

    python evaluation/reextract_all.py [--sources docling,mineru,union]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from evaluation.graduation_gt import PROJECT_ID, load_overrides  # noqa: E402
from evaluation.outcome_gap_audit import mapped_and_all  # noqa: E402
from src.extraction.store_estimates import extract_and_store  # noqa: E402

PROJECTS = {
    "docling": PROJECT_ID,
    "mineru": "bf623758-b01d-4b7e-99ba-39cb83bf83f9",
    "union": "a66764e7-2410-427f-ac3a-618c196e9115",
}


def commit_hash():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="docling,mineru,union")
    args = ap.parse_args()
    wanted = [s.strip() for s in args.sources.split(",") if s.strip()]

    import boto3
    s3 = boto3.client(
        "s3", endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")
    bucket = os.environ.get("R2_BUCKET_NAME", "devchat-pdfs")
    names = [o["Key"].split("/")[-1] for p in s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix=f"rags/{PROJECT_ID}/input-pdfs/") for o in p.get("Contents", [])]
    mapped, all_docs = mapped_and_all(names, load_overrides())
    keys = sorted({Path(d).stem for ds in all_docs.values() for d in ds})
    print(json.dumps({"commit": commit_hash(), "documents": len(keys), "sources": wanted}), flush=True)

    for label in wanted:
        pid = PROJECTS[label]
        print(f"== {label} ({pid}): {len(keys)} documents, prune on", flush=True)
        totals = asyncio.run(extract_and_store(
            pid, doc_keys=keys, prune=True, log=lambda m: print(m, flush=True)))
        print(f"RESULT {label} {json.dumps(totals)}", flush=True)


if __name__ == "__main__":
    main()
