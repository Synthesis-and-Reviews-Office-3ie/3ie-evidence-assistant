"""Add the 6 companion documents to the union (shadow) project.

MinerU parses for them now exist in the MinerU-all project; Docling parses exist in the live
project. This keeps both under the shadow's outputs/parses/, writes the merged parse to the
shadow's outputs/json/ (which the reader reads), copies the PDF, and ensures a documents row.

    python evaluation/unionise_extras.py [--shadow-project <uuid>] [--mineru-project <uuid>]

Then extract each with scripts/extract_estimates.py --project-id <shadow> --only <doc>.
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

import requests  # noqa: E402

from evaluation.graduation_gt import PROJECT_ID, load_overrides  # noqa: E402
from evaluation.outcome_gap_audit import mapped_and_all  # noqa: E402
from infrastructure.modal_lib.extraction import merge_parser_outputs  # noqa: E402

SHADOW = "a66764e7-2410-427f-ac3a-618c196e9115"
MINERU_ALL = "bf623758-b01d-4b7e-99ba-39cb83bf83f9"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shadow-project", default=SHADOW)
    ap.add_argument("--mineru-project", default=MINERU_ALL)
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
    extras = {d for sid, docs in all_docs.items() for d in docs if d != mapped.get(sid)}
    extras = {Path(d).stem for d in extras}
    print(f"extras: {len(extras)}")

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

    done = 0
    for doc in sorted(extras):
        docling = load(PROJECT_ID, doc)
        mineru = load(args.mineru_project, doc)
        if not docling or not mineru:
            print(f"  skip {doc}: docling={bool(docling)} mineru={bool(mineru)}")
            continue
        put(args.shadow_project, f"outputs/parses/docling/{doc}.json", docling)
        put(args.shadow_project, f"outputs/parses/mineru/{doc}.json", mineru)
        merged = merge_parser_outputs(docling, mineru)
        put(args.shadow_project, f"outputs/json/{doc}.json", {
            "doc_id": doc, "project_id": args.shadow_project,
            "source_key": f"rags/{args.shadow_project}/input-pdfs/{doc}.pdf",
            "processed_at": datetime.now().isoformat(), "title": merged.get("title"),
            "authors": merged.get("authors"), "year": merged.get("year"), "abstract": merged.get("abstract"),
            "content": merged.get("content"), "tables": merged.get("tables"), "formulas": merged.get("formulas"),
            "page_count": merged.get("page_count"), "parser": "union", "sources": merged.get("sources"),
            "content_list": merged.get("content_list"),
        })
        src_key = next((n for n in names if Path(n).stem == doc), None)
        if src_key:
            s3.copy_object(Bucket=bucket, CopySource={"Bucket": bucket, "Key": f"rags/{PROJECT_ID}/input-pdfs/{src_key}"},
                           Key=f"rags/{args.shadow_project}/input-pdfs/{src_key}")
        requests.post(f"{url}/rest/v1/documents?on_conflict=rag_project_id,filename",
                      headers={**headers, "Prefer": "resolution=ignore-duplicates,return=minimal"},
                      json=[{"rag_project_id": args.shadow_project, "filename": doc,
                             "original_filename": doc + ".pdf", "file_size_bytes": 0,
                             "mime_type": "application/pdf", "status": "pending",
                             "r2_input_key": f"rags/{args.shadow_project}/input-pdfs/{doc}.pdf"}], timeout=60)
        done += 1
    print(json.dumps({"unionised": done, "extras": sorted(extras)}))


if __name__ == "__main__":
    main()
