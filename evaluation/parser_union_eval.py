"""Score Docling, MinerU and their output-level union against the graduation ground truth.

The key is data/8WR QEX Combined.xlsx: 43 studies, 442 outcome rows, with the hand-typed
estimate and standard error in ``Coeff reg`` and ``SE reg``.

Three match rules are reported, because they answer different questions:

- value anywhere: the hand value appears among any stored value in the document. This is
  inflated by coincidence (a document holds thousands of numbers) and is not a recall.
- exact outcome + value: a stored row with the same normalised outcome name carries the
  value. This is the honest joint recall.
- fuzzy outcome + value: as above, but the outcome names need only overlap in their tokens,
  which separates missing estimates from naming differences.

For rows that fail the exact joint rule, the reason is classified with the audit's own
categories (rounding, sign, scale, outcome present but value differs, outcome missing).

    python evaluation/parser_union_eval.py [--mineru-project <uuid>]

Read-only: no model calls, no writes except the markdown report.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from evaluation.graduation_gt import PROJECT_ID, load_key, study_to_document  # noqa: E402
from evaluation.missing_estimates_audit import classify as audit_classify  # noqa: E402
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


def tokens(text):
    return set(norm(text).split())


def same_outcome(a, b):
    """Token overlap strong enough to call two outcome labels the same estimate."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return False
    intersect = len(ta & tb)
    if not intersect:
        return False
    if intersect / len(ta | tb) >= 0.5:
        return True
    return (ta <= tb or tb <= ta) and min(len(ta), len(tb)) >= 2


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


def _values(rows, field):
    return [r[field] for r in rows if r.get(field) is not None]


def _matched(value, values):
    return bool(values) and classify_miss(value, values) in ("exact", "rounded")


def score(label, rows_by_doc, key, study_doc):
    c = Counter()
    reasons = Counter()
    for sid, group in key.groupby("sid"):
        doc = study_doc.get(sid)
        if not doc:
            continue
        rows = rows_by_doc.get(doc, [])
        all_est = _values(rows, "effect_size")
        all_se = _values(rows, "standard_error")
        outcome_names = {norm(r.get("outcome_name")) for r in rows if norm(r.get("outcome_name"))}
        for _, gt in group.iterrows():
            outcome = gt.get("Outcome name")
            same = [r for r in rows if norm(r.get("outcome_name")) == norm(outcome)]
            near = [r for r in rows if r.get("outcome_name") and same_outcome(r.get("outcome_name"), outcome)]

            c["out_total"] += 1
            if norm(outcome) in outcome_names:
                c["out_exact"] += 1
            if near:
                c["out_fuzzy"] += 1

            value = num(gt.get("Coeff reg"))
            if value is not None:
                c["est_total"] += 1
                if _matched(value, all_est):
                    c["est_anywhere"] += 1
                if _matched(value, _values(same, "effect_size")):
                    c["est_exact"] += 1
                near_values = _values(near, "effect_size")
                if _matched(value, near_values):
                    c["est_fuzzy"] += 1
                elif not _matched(value, _values(same, "effect_size")):
                    if near:
                        kind = audit_classify(value, near_values, outcome,
                                              {norm(r.get("outcome_name")) for r in near})
                        if kind == "missing":
                            kind = "value differs (name variant)"
                    else:
                        kind = "outcome missing"
                    reasons[kind] += 1

            se = num(gt.get("SE reg"))
            if se is not None:
                c["se_total"] += 1
                if _matched(se, all_se):
                    c["se_anywhere"] += 1
                if _matched(se, _values(same, "standard_error")):
                    c["se_exact"] += 1
                if _matched(se, _values(near, "standard_error")):
                    c["se_fuzzy"] += 1

    return {"label": label, "counts": c, "reasons": reasons, "stored": sum(len(v) for v in rows_by_doc.values())}


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
             f"Test set: {key['sid'].nunique()} studies, {len(key)} outcome rows with a hand-typed key.", "",
             "`Value anywhere` is the inflated count (a hand value appears among any stored value in the",
             "document). `Exact + value` requires the same normalised outcome name; `Fuzzy + value` allows",
             "token overlap in the outcome names. The last two are the honest recalls.", "",
             "| Source | Value anywhere (est) | Exact + value (est) | Fuzzy + value (est) |",
             "| --- | --- | --- | --- |"]
    for s in scores:
        c = s["counts"]
        lines.append(f"| {s['label']} | {pct(c['est_anywhere'], c['est_total'])} | "
                     f"{pct(c['est_exact'], c['est_total'])} | {pct(c['est_fuzzy'], c['est_total'])} |")
    lines += ["", "| Source | Exact + value (SE) | Fuzzy + value (SE) | Outcome exact | Outcome fuzzy | Stored rows |",
              "| --- | --- | --- | --- | --- | --- |"]
    for s in scores:
        c = s["counts"]
        lines.append(f"| {s['label']} | {pct(c['se_exact'], c['se_total'])} | "
                     f"{pct(c['se_fuzzy'], c['se_total'])} | {pct(c['out_exact'], c['out_total'])} | "
                     f"{pct(c['out_fuzzy'], c['out_total'])} | {s['stored']} |")

    lines += ["", "## Why the exact joint match misses an estimate", ""]
    for s in scores:
        if not s["reasons"]:
            continue
        lines.append(f"**{s['label']}** ({sum(s['reasons'].values())} misses)")
        lines += ["", "| Reason | Rows |", "| --- | --- |"]
        for reason, n in s["reasons"].most_common():
            lines.append(f"| {reason} | {n} |")
        lines.append("")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\nwritten to {REPORT}")


if __name__ == "__main__":
    main()
