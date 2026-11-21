"""Survey every table of the 49 mapped study documents on three axes: method, effect format, layout.

The reader will choose few-shot examples from a gallery by these tags, so the survey counts which
combinations actually occur. Classification is a cheap model call per table; the counts and the
per-table labels land in evaluation/gallery/survey.json and survey.md.

    python evaluation/gallery_survey.py            # all mapped documents
    python evaluation/gallery_survey.py --limit 20 # a quick sample
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

import boto3
import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from evaluation.graduation_gt import PROJECT_ID, load_overrides  # noqa: E402
from evaluation.outcome_gap_audit import mapped_and_all  # noqa: E402
from src.extraction.table_rules import RESULTS, classify_table, looks_garbled  # noqa: E402

MODEL = "anthropic/claude-haiku-5.5"
OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"
OUT_DIR = ROOT / "evaluation" / "gallery"

METHODS = [
    "RCT (ITT, TOT/LATE, ANCOVA)", "DiD and triple differences", "event study", "panel fixed effects",
    "IV/2SLS (first stage vs second stage)", "regression discontinuity", "matching/PSM/IPW",
    "synthetic control", "heterogeneity by interaction terms", "quantile regression",
    "bounds (Lee, Manski)", "multiple-testing adjusted (q-values, FWER)", "mediation",
    "descriptive means with a difference column", "cost-effectiveness", "other/unknown",
]
FORMATS = [
    "coefficient", "mean difference", "percentage change or % of control mean",
    "standardised effect size (d, g, SD units)", "odds ratio, risk ratio, hazard ratio",
    "marginal effect from logit or probit", "index or z-score", "change in effect between rounds",
    "comparison minus programme or other reversed convention", "other/unknown",
]
LAYOUTS = [
    "SE, t or CI in brackets below or beside", "p-values in their own column", "stars only, no SE",
    "two or three header rows", "Panel A/B stacks", "transposed (outcomes in columns)", "several arms",
    "several rounds", "subgroup columns or rows", "subgroups by indentation", "covariate rows",
    "controls: yes/no rows", "control-mean and N rows", "footnotes define the sign or comparison",
    "split across pages", "rotated table", "text layer mangles the minus sign",
]

PROMPT = """Classify one results table from a development impact evaluation on three axes. Answer with the
exact label strings given, as JSON with keys "method", "format", "layout", "reason".

Never leave method or format empty. Choose the closest label even when imperfect; use "other/unknown" only
when none fits, and then give a one-line "reason" saying what the table is. Give every layout label present;
layout may be empty only when no feature applies.

method (an evaluation method, one or two most specific, never empty):
{methods}

format (how the effect is printed, one or two, never empty):
{formats}

layout (every layout feature present, may be empty):
{layouts}

Caption: {caption}
Table:
{table}

Return JSON only: {{"method": ["..."], "format": ["..."], "layout": ["..."], "reason": ""}}"""


def s3_client():
    return boto3.client(
        "s3", endpoint_url="https://" + os.environ["R2_ACCOUNT_ID"] + ".r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")


def mapped_keys(s3, bucket):
    names = [o["Key"].split("/")[-1] for p in s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix=f"rags/{PROJECT_ID}/input-pdfs/") for o in p.get("Contents", [])]
    _, all_sets = mapped_and_all(names, load_overrides())
    return sorted({Path(d).stem for docs in all_sets.values() for d in docs})


def tables_of(content):
    out = []
    for idx, item in enumerate(content):
        if item.get("type") != "table":
            continue
        text = str(item.get("text") or "")
        if "|" not in text or looks_garbled(text):
            continue
        label = ""
        for prior in reversed(content[:idx]):
            t = str(prior.get("text") or "").strip()
            if t:
                label = t[:160]
                break
        out.append({"page": item.get("page_idx", 0) + 1, "caption": label,
                    "text": text[:6000], "garbled_minus": bool(re.search(r"[\ufffd¡]", text))})
    return out


async def classify(client, table, sem):
    body = {"model": MODEL, "temperature": 0, "max_tokens": 600,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": PROMPT.format(
                methods="\n".join("- " + m for m in METHODS), formats="\n".join("- " + f for f in FORMATS),
                layouts="\n".join("- " + l for l in LAYOUTS),
                caption=table["caption"], table=table["text"])}]}
    async with sem:
        data = {}
        for attempt in range(5):
            try:
                r = await client.post(OPENROUTER, json=body)
                if r.status_code == 429 or r.status_code >= 500:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                r.raise_for_status()
                text = r.json()["choices"][0]["message"]["content"] or "{}"
                m = re.search(r"\{.*\}", text, re.S)
                data = json.loads(m.group(0)) if m else {}
                break
            except Exception:
                await asyncio.sleep(1 * (attempt + 1))
    if not isinstance(data, dict):
        data = {}
    method = [x for x in (data.get("method") or []) if x in METHODS]
    fmt = [x for x in (data.get("format") or []) if x in FORMATS]
    reason = str(data.get("reason") or "").strip()[:200]
    if not method:
        method = ["other/unknown"]
    if not fmt:
        fmt = ["other/unknown"]
    return {"method": method, "format": fmt,
            "layout": [x for x in (data.get("layout") or []) if x in LAYOUTS], "reason": reason}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--count-only", action="store_true")
    args = ap.parse_args()
    bucket = os.environ.get("R2_BUCKET_NAME", "devchat-pdfs")
    s3 = s3_client()
    keys = mapped_keys(s3, bucket)
    if args.limit:
        keys = keys[:args.limit]

    # Only tables that hold results: those the results-table check accepts, or those on a page that already
    # has stored estimates.
    from supabase import create_client

    sb = create_client(os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    stored_pages = set()
    pos = 0
    while True:
        batch = (sb.table("effect_estimates").select("doc_key,page").eq("rag_project_id", PROJECT_ID)
                 .eq("source", "tables_v1").range(pos, pos + 999).execute().data)
        for r in batch:
            stored_pages.add((r["doc_key"], r["page"]))
        if len(batch) < 1000:
            break
        pos += 1000

    tables = []
    for key in keys:
        try:
            body = json.loads(s3.get_object(Bucket=bucket, Key=f"rags/{PROJECT_ID}/outputs/json/{key}.json")["Body"].read())
        except Exception:
            continue
        for t in tables_of(body.get("content_list") or []):
            t["doc"] = key
            if classify_table(t["caption"])[0] != RESULTS and (key, t["page"]) not in stored_pages:
                continue
            tables.append(t)
    print(f"{len(keys)} documents, {len(tables)} results tables", flush=True)
    if args.count_only:
        # Haiku at about 1.3k prompt and 0.1k completion tokens per table is about $0.00015 a call.
        print(f"estimated cost: {len(tables)} x $0.00015 = ${len(tables) * 0.00015:.3f}")
        return

    sem = asyncio.Semaphore(4)
    headers = {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"}
    async with httpx.AsyncClient(timeout=180, headers=headers) as client:
        results = await asyncio.gather(*(classify(client, t, sem) for t in tables))
    for t, r in zip(tables, results):
        t.update(r)

    # Hand-check on the two documents known to have several DiD tables.
    for tag in ("Das_(2010)", "Siddiquee_(2016)"):
        hits = [t for t in tables if tag.lower().replace("_", " ") in t["doc"].lower().replace("_", " ")]
        print(f"\n--- sanity {tag}: {len(hits)} results tables ---")
        for t in hits[:15]:
            print(f"  p{t['page']} | {t['caption'][:46]} | {t['method']} | {t['format']}", flush=True)

    method_counts = Counter(m for t in tables for m in t["method"])
    format_counts = Counter(f for t in tables for f in t["format"])
    layout_counts = Counter(l for t in tables for l in t["layout"])
    pair = Counter()
    for t in tables:
        for m in (t["method"] or ["other/unknown"]):
            for l in (t["layout"] or ["none"]):
                pair[(m, l)] += 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "survey.json").write_text(json.dumps(
        {"documents": len(keys), "tables": len(tables), "method": method_counts, "format": format_counts,
         "layout": layout_counts, "method_by_layout": {f"{m} | {l}": n for (m, l), n in pair.items()},
         "rows": [{k: t[k] for k in ("doc", "page", "caption", "method", "format", "layout", "reason", "garbled_minus")}
                  for t in tables]}, indent=1), encoding="utf-8")
    lines = [f"# Table survey, {len(tables)} tables across {len(keys)} mapped documents", "",
             "## Method", ""]
    lines += [f"- {m}: {n}" for m, n in method_counts.most_common()]
    lines += ["", "## Effect format", ""] + [f"- {f}: {n}" for f, n in format_counts.most_common()]
    lines += ["", "## Layout", ""] + [f"- {l}: {n}" for l, n in layout_counts.most_common()]
    (OUT_DIR / "survey.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"method": method_counts.most_common(6), "format": format_counts.most_common(6),
                      "layout": layout_counts.most_common(8)}, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
