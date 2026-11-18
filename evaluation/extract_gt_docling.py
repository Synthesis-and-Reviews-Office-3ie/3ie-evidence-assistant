"""Re-extract effect estimates for the 43 ground-truth documents from their Docling parses.

The live graduation project already holds Docling parses. To compare parsers without
conflating the parser with an extractor-version difference, this re-runs the current
extractor over exactly those 43 documents. Rows of the same source are replaced per
document; other documents and other sources are left alone.

    python evaluation/extract_gt_docling.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import boto3  # noqa: E402

from evaluation.graduation_gt import PROJECT_ID, study_to_document  # noqa: E402
from src.extraction.store_estimates import extract_and_store  # noqa: E402


def r2():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def main():
    bucket = os.environ.get("R2_BUCKET_NAME", "devchat-pdfs")
    pag = r2().get_paginator("list_objects_v2")
    prefix = f"rags/{PROJECT_ID}/input-pdfs/"
    names = [o["Key"].split("/")[-1] for p in pag.paginate(Bucket=bucket, Prefix=prefix)
             for o in p.get("Contents", [])]
    mapping = study_to_document(names)
    doc_keys = sorted({Path(d).stem for d in mapping.values() if d})
    print(f"extracting Docling-side estimates for {len(doc_keys)} documents", flush=True)
    totals = asyncio.run(extract_and_store(
        PROJECT_ID, doc_keys=doc_keys, log=lambda m: print(m, flush=True)))
    print(json.dumps(totals), flush=True)


if __name__ == "__main__":
    main()
