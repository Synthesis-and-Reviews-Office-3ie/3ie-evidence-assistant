"""Score Docling, MinerU and their output-level union against the graduation ground truth.

The key is data/8WR QEX Combined.xlsx: 43 studies, 442 outcome rows, with the hand-typed
estimate and standard error in ``Coeff reg`` and ``SE reg``. Each source is a project's
``effect_estimates`` rows. The union merges the Docling and MinerU rows, deduplicated on
document, normalised outcome name and the printed numbers, mirroring the TVET inventory
union.

    python evaluation/parser_union_eval.py [--mineru-project <uuid>]

Read-only: no model calls, no writes except the markdown report.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from evaluation.graduation_gt import PROJECT_ID, load_key, study_to_document  # noqa: E402
from evaluation.stored_rows import classify_miss  # noqa: E402

SOURCE = "tables_v1"
DEFAULT_MINERU = "a66764e7-2410-427f-ac3a-618c196e9115"
REPORT = ROOT / "evaluation" / "results" / f"parser_union_{date.today().isoformat()}.md"
PAGE = 1000


def supabase():
    url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return url, {"apikey": key, "Authorization": f"Bearer {key}"}


def num(value):
    if value is None:
        return None
    text = (str(value).replace(",", "").replace("\xa0", " ")
            .replace("\u2212", "-").replace("\u2013", "-").replace("\u2014", "-"))
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group()) if match else None


def norm(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def fetch_rows(project_id, doc_key):
    url, headers = supabase()
    rows, start = [], 0
    while True:
        h = {**headers, "Range": f"{start}-{start + PAGE - 1}"}
        r = requests.get(
            f"{url}/rest/v1/effect_estimates",
            params={"rag_project_id": f"eq.{project_id}", "source": f"eq.{SOURCE}",
                    "doc_key": f"eq.{doc_key}", "select": "doc_key,outcome_name,effect_size,standard_error"},
            headers=h, timeout=120,
        )
        batch = r.json() if r.status_code < 300 else []
        rows.extend(batch)
        if len(batch) < PAGE:
            return rows
        start += PAGE


def load_rows(project_id, doc_keys):
    return {doc: fetch_rows(project_id, doc) for doc in doc_keys}


def union_rows(a, b):
    out = {}
    for doc in set(a) | set(b):
        seen = {}
        for row in (a.get(doc, []) or []) + (b.get(doc, []) or []):
            key = (norm(row.get("outcome_name")),
                   None if row.get("effect_size") is None else round(float(row["effect_size"]), 6),
                   None if row.get("standard_error") is None else round(float(row["standard_error"]), 6))
            seen.setdefault(key, row)
        out[doc] = list(seen.values())
    return out


def score(label, rows_by_doc, key, study_doc):
    est_total = est_match = 0
    se_total = se_match = 0
    out_total = out_covered = 0
    stored_total = 0
    per_study = []
    for sid, group in key.groupby("sid"):
        doc = study_doc.get(sid)
        if not doc:
            continue
        rows = rows_by_doc.get(doc, [])
        stored_total += len(rows)
        est_values = [r["effect_size"] for r in rows if r.get("effect_size") is not None]
        se_values = [r["standard_error"] for r in rows if r.get("standard_error") is not None]
        outcomes = {norm(r.get("outcome_name")) for r in rows if norm(r.get("outcome_name"))}
        s_est = s_est_m = s_se = s_se_m = s_out = s_out_c = 0
        for _, row in group.iterrows():
            outcome = row.get("Outcome name")
            if norm(outcome):
                s_out += 1
                if norm(outcome) in outcomes:
                    s_out_c += 1
            value = num(row.get("Coeff reg"))
            if value is not None:
                s_est += 1
                if classify_miss(value, est_values) in ("exact", "rounded"):
                    s_est_m += 1
            se = num(row.get("SE reg"))
            if se is not None:
                s_se += 1
                if classify_miss(se, se_values) in ("exact", "rounded"):
                    s_se_m += 1
        est_total += s_est; est_match += s_est_m
        se_total += s_se; se_match += s_se_m
        out_total += s_out; out_covered += s_out_c
        per_study.append((sid, s_est, s_est_m, s_out, s_out_c))
    return {
        "label": label,
        "stored": stored_total,
        "est": (est_match, est_total),
        "se": (se_match, se_total),
        "outcome": (out_covered, out_total),
        "per_study": per_study,
    }


def pct(matched, total):
    return f"{matched}/{total} ({100 * matched / total:.0f}%)" if total else "n/a"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mineru-project", default=DEFAULT_MINERU)
    args = ap.parse_args()

    key = load_key()
    import boto3
    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )
    bucket = os.environ.get("R2_BUCKET_NAME", "devchat-pdfs")
    pag = s3.get_paginator("list_objects_v2")
    names = [o["Key"].split("/")[-1] for p in pag.paginate(Bucket=bucket, Prefix=f"rags/{PROJECT_ID}/input-pdfs/")
             for o in p.get("Contents", [])]
    study_doc = {sid: Path(doc).stem for sid, doc in study_to_document(names).items() if doc}
    print(f"studies mapped: {len(study_doc)} / {key['sid'].nunique()}", flush=True)

    docling = load_rows(PROJECT_ID, list(study_doc.values()))
    mineru = load_rows(args.mineru_project, list(study_doc.values()))
    union = union_rows(docling, mineru)

    scores = [score("Docling", docling, key, study_doc),
              score("MinerU", mineru, key, study_doc),
              score("Union", union, key, study_doc)]

    lines = ["# Parser comparison on the poverty graduation collection", "",
             f"Test set: {key['sid'].nunique()} studies, {len(key)} outcome rows with a hand-typed key.",
             "Match means the stored value equals the hand-typed value at the paper's printed precision.", "",
             "| Source | Effect size matched | Standard error matched | Outcome covered | Stored rows |",
             "| --- | --- | --- | --- | --- |"]
    for s in scores:
        lines.append(f"| {s['label']} | {pct(*s['est'])} | {pct(*s['se'])} | {pct(*s['outcome'])} | {s['stored']} |")
    lines.append("")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\nwritten to {REPORT}")


if __name__ == "__main__":
    main()
