"""Measure how often two parsers' tables need a judgement call to be matched.

For the 43 mapped graduation papers, load each parser's saved tables and try to pair them
in two deterministic passes:

1. same page and similar caption;
2. same or adjacent page and similar content signature (number set and word set).

Tables that pass someone-to-one are free. Tables that stay ambiguous or unmatched after
both passes are what would need a model.

Read-only. Prints counts.

    python evaluation/table_union_probe.py [--mineru-project <uuid>]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from evaluation.graduation_gt import PROJECT_ID, study_to_document  # noqa: E402

DEFAULT_MINERU = "a66764e7-2410-427f-ac3a-618c196e9115"
TAG = re.compile(r"<[^>]+>")


def words(text):
    return {w for w in re.sub(r"[^a-z0-9]+", " ", TAG.sub(" ", str(text or "")).lower()).split() if len(w) >= 3}


def numbers(text):
    return {round(float(x), 4) for x in re.findall(r"-?\d+(?:\.\d+)?", TAG.sub(" ", str(text or "")))}


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def caption_of(item):
    caption = item.get("table_caption")
    if isinstance(caption, (list, tuple)):
        return " ".join(str(c) for c in caption)
    return str(caption or "")


def body_of(item):
    return str(item.get("text") or item.get("table_body") or "")


def page_of(item):
    try:
        return int(item.get("page_idx"))
    except (TypeError, ValueError):
        return None


def load_tables(s3, bucket, project_id, doc):
    try:
        payload = json.loads(s3.get_object(Bucket=bucket, Key=f"rags/{project_id}/outputs/json/{doc}.json")["Body"].read())
    except Exception:
        return None
    return [i for i in (payload.get("content_list") or []) if i.get("type") == "table"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mineru-project", default=DEFAULT_MINERU)
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

    counts = Counter()
    for doc in docs:
        docling = load_tables(s3, bucket, PROJECT_ID, doc)
        mineru = load_tables(s3, bucket, args.mineru_project, doc)
        if docling is None or mineru is None:
            counts["missing one parser's output"] += 1
            continue
        counts["documents"] += 1
        counts["docling tables"] += len(docling)
        remaining = list(range(len(mineru)))

        # Pass 1: same page, similar caption.
        after_caption = []
        for d in docling:
            same_page = [i for i in remaining if page_of(mineru[i]) == page_of(d) and page_of(d) is not None]
            strong = [i for i in same_page if jaccard(words(caption_of(d)), words(caption_of(mineru[i]))) >= 0.5]
            if len(strong) == 1:
                counts["pass 1 caption one-to-one"] += 1
                remaining.remove(strong[0])
            elif len(strong) > 1:
                counts["pass 1 ambiguous"] += 1
                remaining.remove(strong[0])
            else:
                after_caption.append(d)

        # Pass 2: same or adjacent page, similar content signature.
        for d in after_caption:
            dpage = page_of(d)
            dn, dw = numbers(body_of(d)), words(body_of(d))
            candidates = []
            for i in remaining:
                mpage = page_of(mineru[i])
                if dpage is None or mpage is None or abs(mpage - dpage) > 1:
                    continue
                if jaccard(dn, numbers(body_of(mineru[i]))) >= 0.5 and jaccard(dw, words(body_of(mineru[i]))) >= 0.3:
                    candidates.append(i)
            if len(candidates) == 1:
                counts["pass 2 content one-to-one"] += 1
                remaining.remove(candidates[0])
            elif len(candidates) > 1:
                counts["pass 2 ambiguous"] += 1
                remaining.remove(candidates[0])
            else:
                counts["unmatched after both passes"] += 1

    counts["docling tables unpaired to mineru"] = counts["unmatched after both passes"] + counts["pass 1 ambiguous"] + counts["pass 2 ambiguous"]
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
