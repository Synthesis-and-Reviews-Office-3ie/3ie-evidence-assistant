"""Explain the graduation key's misses after canonical outcome normalisation.

Step 2: for a hand-typed estimate that the mapped document does not match, search the
study's other documents (appendix, brief, translation) before calling it missing.

Step 3: for a hand-typed estimate whose outcome is present but whose value differs, list
the candidate stored rows so the cause can be read (arm, column, page).

Read-only. Writes evaluation/results/outcome_gap_audit_<date>.md.

    python evaluation/outcome_gap_audit.py
"""

from __future__ import annotations

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

from evaluation.graduation_gt import PROJECT_ID, load_key, load_overrides  # noqa: E402
from evaluation.outcome_taxonomy import categories  # noqa: E402
from evaluation.stored_rows import classify_miss  # noqa: E402

SOURCE = "tables_v1"
REPORT = ROOT / "evaluation" / "results" / f"outcome_gap_audit_{date.today().isoformat()}.md"
PAGE = 1000
FIELDS = "doc_key,outcome_name,effect_size,standard_error,treatment_arm,subgroup,table_number,page"


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
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb or not (ta & tb):
        return False
    if len(ta & tb) / len(ta | tb) >= 0.5:
        return True
    return (ta <= tb or tb <= ta) and min(len(ta), len(tb)) >= 2


def fetch_rows(doc_key):
    url, headers = supabase()
    rows, start = [], 0
    while True:
        h = {**headers, "Range": f"{start}-{start + PAGE - 1}"}
        r = requests.get(
            f"{url}/rest/v1/effect_estimates",
            params={"rag_project_id": f"eq.{PROJECT_ID}", "source": f"eq.{SOURCE}",
                    "doc_key": f"eq.{doc_key}", "select": FIELDS},
            headers=h, timeout=120,
        )
        batch = r.json() if r.status_code < 300 else []
        rows.extend(batch)
        if len(batch) < PAGE:
            return rows
        start += PAGE


def mapped_and_all(names, overrides):
    """The one scored document per study, and every document that names the study."""
    mapped, all_docs = {}, {}
    key = load_key()
    for sid in sorted(key["sid"].unique()):
        hits = [n for n in names if sid in n]
        ov = [d.replace(".pdf", "") for d in overrides.get(sid, {}).get("documents", [])]
        ov_hits = [n for n in names if any(o in n for o in ov)] if ov else []
        everything = sorted(set(hits) | set(ov_hits))
        all_docs[sid] = [Path(n).stem for n in everything]
        excluded = ("appendix", "_app.", "_app_", "_app ", "policy_brief", "brief", "supplement")
        mains = [n for n in hits if not any(t in n.lower() for t in excluded)]
        pick = ov_hits[0] if len(ov_hits) == 1 else (
            mains[0] if len(mains) == 1 else sorted(mains)[0] if mains else (hits[0] if hits else None))
        mapped[sid] = Path(pick).stem if pick else None
    return mapped, all_docs


def matched(value, rows):
    values = [r["effect_size"] for r in rows if r.get("effect_size") is not None]
    return bool(values) and value is not None and classify_miss(value, values) in ("exact", "rounded")


def main():
    key = load_key()
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
    rows_by_doc = {d: fetch_rows(d) for d in docs}
    print(f"studies {len(mapped)}; documents fetched {len(docs)}", flush=True)

    disposition = Counter()
    examples_other = []
    examples_absent = []
    value_cases = []
    canonical_est_total = canonical_est_match = 0
    full_est_match = 0
    canonical_out_total = canonical_out_present = 0
    full_out_present = 0

    for sid, group in key.groupby("sid"):
        doc = mapped.get(sid)
        if not doc:
            continue
        rows = rows_by_doc.get(doc, [])
        others = [r for d in all_docs[sid] if d != doc for r in rows_by_doc.get(d, [])]
        study_rows = rows + others
        outcome_cats_here = set().union(*[categories(r.get("outcome_name")) for r in rows]) if rows else set()
        outcome_cats_all = (set().union(*[categories(r.get("outcome_name")) for r in study_rows])
                            if study_rows else set())
        for _, gt in group.iterrows():
            outcome = gt.get("Outcome name")
            cats = categories(outcome) - {"noise"}
            if not cats or cats == {"other"}:
                disposition["uncategorised outcome label"] += 1
                continue
            canonical_out_total += 1
            if cats & outcome_cats_here:
                canonical_out_present += 1
            if cats & outcome_cats_all:
                full_out_present += 1
            here_cat = [r for r in rows if categories(r.get("outcome_name")) & cats]
            other_cat = [r for r in others if categories(r.get("outcome_name")) & cats]
            value = num(gt.get("Coeff reg"))
            if value is None:
                continue
            canonical_est_total += 1
            if matched(value, here_cat + other_cat):
                full_est_match += 1
            if matched(value, here_cat):
                canonical_est_match += 1
                continue
            if matched(value, other_cat):
                disposition["found in another document of the study"] += 1
                if len(examples_other) < 12:
                    examples_other.append((Path(doc).name, outcome, value))
            elif here_cat:
                disposition["mapped document has the category, value differs"] += 1
                value_cases.append((sid, outcome, value, here_cat))
            elif other_cat:
                disposition["other document has the category, value differs"] += 1
            else:
                disposition["category absent from the study"] += 1
                if len(examples_absent) < 12:
                    examples_absent.append((sid, outcome, value))

    lines = ["# Outcome gap audit", "",
             f"Key: {key['sid'].nunique()} studies, {len(key)} outcome rows. Scored document is one per study.",
             "",
             "Two units are reported: the single mapped document per study, and every document that names the "
             "study (appendix, brief, translation).",
             "",
             f"Canonical outcome present in the mapped document: {canonical_out_present}/{canonical_out_total} "
             f"({100 * canonical_out_present / canonical_out_total:.0f}%).",
             f"Canonical outcome present across the study's documents: {full_out_present}/{canonical_out_total} "
             f"({100 * full_out_present / canonical_out_total:.0f}%).",
             f"Canonical outcome and value matched, mapped document: {canonical_est_match}/{canonical_est_total} "
             f"({100 * canonical_est_match / canonical_est_total:.0f}%).",
             f"Canonical outcome and value matched, all of the study's documents: {full_est_match}/{canonical_est_total} "
             f"({100 * full_est_match / canonical_est_total:.0f}%).", "",
             "## Where an unmatched estimate is (mapped document)", "", "| Disposition | Rows |", "| --- | --- |"]
    for reason, n in disposition.most_common():
        lines.append(f"| {reason} | {n} |")
    lines += ["", "Examples found in another document:", ""]
    lines += [f"- {d}: {o} = {v}" for d, o, v in examples_other] or ["- none"]
    lines += ["", "Examples with the category absent from the study:", ""]
    lines += [f"- {s}: {o} = {v}" for s, o, v in examples_absent] or ["- none"]

    lines += ["", "## Value differs: candidate stored rows", "",
              f"{len(value_cases)} hand rows have the category in the mapped document but no matching value. "
              "The first 15 are listed with their candidates."]
    for sid, outcome, value, cands in value_cases[:15]:
        lines.append("")
        lines.append(f"- {sid} | {outcome} = {value}")
        for r in cands[:4]:
            lines.append(f"  - stored {r.get('effect_size')} (SE {r.get('standard_error')}) "
                         f"arm={str(r.get('treatment_arm'))[:40]} table={str(r.get('table_number'))[:24]} "
                         f"p={r.get('page')} label={str(r.get('outcome_name'))[:50]}")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:40]))
    print(f"\nwritten to {REPORT}")


if __name__ == "__main__":
    main()
