"""Score Docling, MinerU and the union against the graduation key, all documents of each study.

Canonical matching: both the hand label and the stored label are mapped to a small category set
(`evaluation/outcome_taxonomy.py`), a value counts only when it is carried by a row in a shared
category, and the value must match at the paper's printed precision. Exact-name and token-overlap
matches are reported alongside as sensitivities.

Rows are pooled across every document that names the study (paper, appendix, brief, translation).

    python evaluation/three_way_eval.py --docling <uuid> --mineru <uuid> --union <uuid>

Read-only; writes evaluation/results/three_way_<date>.md.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from evaluation.graduation_gt import PROJECT_ID, load_key, load_overrides  # noqa: E402
from evaluation.outcome_gap_audit import mapped_and_all  # noqa: E402
from evaluation.outcome_taxonomy import categories  # noqa: E402
from evaluation.stored_rows import classify_miss  # noqa: E402

PAGE = 1000
FIELDS = "doc_key,outcome_name,effect_size,standard_error,created_at"
REPORT = ROOT / "evaluation" / "results" / f"three_way_{date.today().isoformat()}.md"


def supabase():
    url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return url, {"apikey": key, "Authorization": f"Bearer {key}"}


def git_commit():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


def window_of(rows_by_doc):
    """Earliest and latest row timestamp over the study's documents only."""
    stamps = [r["created_at"] for rows in rows_by_doc.values() for r in rows if r.get("created_at")]
    return (min(stamps)[:16], max(stamps)[:16]) if stamps else ("none", "none")


def num(value):
    if value is None:
        return None
    text = (str(value).replace(",", "").replace("\xa0", " ").replace("\u2212", "-"))
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group()) if match else None


def norm(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def tokens(text):
    return set(norm(text).split())


def same_outcome(a, b):
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb or not (ta & tb):
        return False
    if len(ta & tb) / len(ta | tb) >= 0.5:
        return True
    return (ta <= tb or tb <= ta) and min(len(ta), len(tb)) >= 2


def fetch_rows(project_id, doc):
    url, headers = supabase()
    rows, start = [], 0
    while True:
        h = {**headers, "Range": f"{start}-{start + PAGE - 1}"}
        r = requests_get(f"{url}/rest/v1/effect_estimates", params={
            "rag_project_id": f"eq.{project_id}", "source": "eq.tables_v1",
            "doc_key": f"eq.{doc}", "select": FIELDS}, headers=h)
        batch = r if isinstance(r, list) else []
        rows.extend(batch)
        if len(batch) < PAGE:
            return rows
        start += PAGE


def requests_get(url, params, headers):
    import time

    import requests

    last = None
    for attempt in range(6):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=120)
            if r.status_code >= 500:
                last = RuntimeError(f"status {r.status_code}")
                time.sleep(2 * (attempt + 1))
                continue
            return r.json() if r.status_code < 300 else []
        except Exception as e:  # transient TLS/connection resets are common against Supabase
            last = e
            time.sleep(2 * (attempt + 1))
    raise last


def matched(value, rows, field="effect_size"):
    if value is None:
        return False
    values = [r[field] for r in rows if r.get(field) is not None]
    return bool(values) and classify_miss(value, values) in ("exact", "rounded")


def score(label, project_id, rows_by_doc, key, all_docs):
    c = Counter()
    for sid, group in key.groupby("sid"):
        docs = all_docs.get(sid, [])
        rows = [r for d in docs for r in rows_by_doc.get(d, [])]
        c["stored"] += len(rows)
        cats_here = set().union(*[categories(r.get("outcome_name")) for r in rows]) if rows else set()
        names = {norm(r.get("outcome_name")) for r in rows if norm(r.get("outcome_name"))}
        for _, gt in group.iterrows():
            outcome = gt.get("Outcome name")
            cats = categories(outcome) - {"noise"}
            if not cats or cats == {"other"}:
                c["uncategorised"] += 1
                continue
            c["out_total"] += 1
            if cats & cats_here:
                c["out_present"] += 1
            in_cat = [r for r in rows if categories(r.get("outcome_name")) & cats]
            exact = [r for r in rows if norm(r.get("outcome_name")) == norm(outcome)]
            near = [r for r in rows if r.get("outcome_name") and same_outcome(r.get("outcome_name"), outcome)]
            value = num(gt.get("Coeff reg"))
            if value is not None:
                c["est_total"] += 1
                if matched(value, in_cat):
                    c["est_canonical"] += 1
                if matched(value, exact):
                    c["est_exact"] += 1
                if matched(value, near):
                    c["est_fuzzy"] += 1
            se = num(gt.get("SE reg"))
            if se is not None:
                c["se_total"] += 1
                if matched(se, in_cat, "standard_error"):
                    c["se_canonical"] += 1
    return {"label": label, "c": c}


def pct(a, b):
    return f"{a}/{b} ({100 * a / b:.0f}%)" if b else "n/a"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docling", default=PROJECT_ID)
    ap.add_argument("--mineru", required=True)
    ap.add_argument("--union", required=True)
    ap.add_argument("--out", help="report path; default is commit-stamped in evaluation/results")
    ap.add_argument("--commit", help="commit to record; default is git HEAD")
    ap.add_argument("--prune", action="store_true", help="state that rows were replaced, not carried forward")
    args = ap.parse_args()
    commit = args.commit or git_commit()

    import boto3
    s3 = boto3.client(
        "s3", endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")
    bucket = os.environ.get("R2_BUCKET_NAME", "devchat-pdfs")
    names = [o["Key"].split("/")[-1] for p in s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix=f"rags/{PROJECT_ID}/input-pdfs/") for o in p.get("Contents", [])]
    mapped, all_docs = mapped_and_all(names, load_overrides())
    docs = sorted({d for ds in all_docs.values() for d in ds})
    print(f"studies: {len(all_docs)}, documents: {len(docs)}", flush=True)

    sources = [("Docling", args.docling), ("MinerU", args.mineru), ("Union", args.union)]
    results = []
    windows = {}
    for label, pid in sources:
        rows_by_doc = {d: fetch_rows(pid, d) for d in docs}
        results.append(score(label, pid, rows_by_doc, load_key(), all_docs))
        windows[label] = window_of(rows_by_doc)
        print(f"  {label}: {results[-1]['c']['stored']} stored rows", flush=True)

    window_text = "; ".join(f"{label} {a} to {b}" for label, (a, b) in windows.items())
    lines = ["# Three-way parser comparison, all documents of each study", "",
             f"Pinned commit `{commit}`. Prune {'on' if args.prune else 'not recorded'}. All sources read by "
             "this one code version.", "",
             f"Extraction windows: {window_text}.", "",
             "Caveat: the reader is still changing, so this measurement is valid for this commit only.", "",
             "Canonical matching: shared outcome category and a value equal at printed precision.",
             "Rows pooled across every document that names the study.", "",
             "| Source | Canonical + value | Exact name + value | Token overlap + value | Canonical SE + value | Outcome present | Stored rows |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in results:
        c = r["c"]
        lines.append(f"| {r['label']} | {pct(c['est_canonical'], c['est_total'])} | "
                     f"{pct(c['est_exact'], c['est_total'])} | {pct(c['est_fuzzy'], c['est_total'])} | "
                     f"{pct(c['se_canonical'], c['se_total'])} | {pct(c['out_present'], c['out_total'])} | "
                     f"{c['stored']} |")
    out = Path(args.out) if args.out else (
        ROOT / "evaluation" / "results" / f"three_way_{date.today().isoformat()}_{commit[:7]}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\nwritten to {out}")


if __name__ == "__main__":
    main()
