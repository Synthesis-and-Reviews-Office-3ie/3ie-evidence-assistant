"""Write the merged (union) parse into the shadow project for the evaluation.

Reads the Docling parse from the live graduation project and the MinerU parse from the shadow
project, keeps both under outputs/parses/, and writes the canonical merged document to the
shadow's outputs/json/, which the estimate reader reads.

    python evaluation/unionise_shadow.py [--shadow-project <uuid>]

Then run: python scripts/extract_estimates.py --project-id <shadow-project>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from evaluation.graduation_gt import PROJECT_ID, study_to_document  # noqa: E402
from infrastructure.modal_lib.extraction import merge_parser_outputs  # noqa: E402

DEFAULT_SHADOW = "a66764e7-2410-427f-ac3a-618c196e9115"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shadow-project", default=DEFAULT_SHADOW)
    args = ap.parse_args()

    import boto3
    s3 = boto3.client(
        "s3", endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")
    bucket = os.environ.get("R2_BUCKET_NAME", "devchat-pdfs")

    names = [o["Key"].split("/")[-1] for p in s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix=f"rags/{PROJECT_ID}/input-pdfs/") for o in p.get("Contents", [])]
    docs = sorted({Path(d).stem for d in study_to_document(names).values() if d})

    def load(project_id, doc):
        try:
            return json.loads(s3.get_object(
                Bucket=bucket, Key=f"rags/{project_id}/outputs/json/{doc}.json")["Body"].read())
        except Exception:
            return None

    def put(project_id, suffix, payload):
        s3.put_object(Bucket=bucket, Key=f"rags/{project_id}/{suffix}",
                      Body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                      ContentType="application/json")

    merged_count = skipped = 0
    for doc in docs:
        docling = load(PROJECT_ID, doc)
        mineru = load(args.shadow_project, doc)
        if not docling or not mineru:
            skipped += 1
            continue
        put(args.shadow_project, f"outputs/parses/docling/{doc}.json", docling)
        put(args.shadow_project, f"outputs/parses/mineru/{doc}.json", mineru)
        merged = merge_parser_outputs(docling, mineru)
        put(args.shadow_project, f"outputs/json/{doc}.json", {
            "doc_id": doc,
            "project_id": args.shadow_project,
            "source_key": f"rags/{args.shadow_project}/input-pdfs/{doc}.pdf",
            "processed_at": datetime.now().isoformat(),
            "title": merged.get("title"),
            "authors": merged.get("authors"),
            "year": merged.get("year"),
            "abstract": merged.get("abstract"),
            "content": merged.get("content"),
            "tables": merged.get("tables"),
            "formulas": merged.get("formulas"),
            "page_count": merged.get("page_count"),
            "parser": "union",
            "sources": merged.get("sources"),
            "content_list": merged.get("content_list"),
        })
        merged_count += 1
    print(json.dumps({"merged": merged_count, "skipped": skipped, "shadow_project": args.shadow_project}))


if __name__ == "__main__":
    main()
