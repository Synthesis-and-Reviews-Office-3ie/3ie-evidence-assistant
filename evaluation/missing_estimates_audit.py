"""
Diagnose the hand-typed estimates the stored rows do not match.

The recall check uses exact value matching, so a stored 0.1503 against a printed 0.15, a sign
convention, or a different scale (percent against share, thousands) counts as a miss. For every
hand-typed estimate that has no exact match, this asks why:

- rounding: a stored value equals it after rounding or within 1%
- sign: a stored value equals its negative
- scale: a stored value equals it times or divided by 100 or 1000
- outcome present: the study has a stored row with the same outcome, but a different value
- missing: none of the above, which is a real gap

Same for standard errors. Read-only, no model calls.

Usage:
    python evaluation/missing_estimates_audit.py
"""

from __future__ import annotations

import os
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from supabase import create_client  # noqa: E402

from evaluation.stored_rows import fetch_all, matches  # noqa: E402
from evaluation.usage_study import load_content  # noqa: E402
from src.extraction.provenance import looks_like_review, looks_like_wrong_version  # noqa: E402

PROJ = "7efdc60e-e863-480c-929e-616574725e5f"
STUDY = ROOT / "evaluation" / "results" / "usage_study" / PROJ
REPORT = ROOT / "evaluation" / "results" / f"missing_estimates_audit_{date.today().isoformat()}.md"


def num(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).replace(",", "").replace("\xa0", " ").replace("\u2212", "-").replace("\u2013", "-").replace("\u2014", "-")
    m = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(m.group()) if m else None


def norm(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def classify(h, values, outcome, rows_by_outcome):
    if any(abs(v - h) < 1e-6 for v in values):
        return "exact"
    if any(round(v, 2) == round(h, 2) for v in values):
        return "rounding 2dp"
    if any(abs(v - h) / max(abs(h), abs(v), 1e-9) < 0.01 for v in values):
        return "rounding 1%"
    if matches(h, values):
        # Within half of the last decimal the paper prints: a match at printed precision, not a gap.
        return "printed precision"
    if any(abs(v + h) < 1e-6 for v in values):
        return "sign"
    for factor in (100, 0.01, 1000, 0.001):
        if any(abs(v - h * factor) / max(abs(h * factor), abs(v), 1e-9) < 1e-6 for v in values):
            return f"scale x{factor:g}"
    if norm(outcome) and norm(outcome) in rows_by_outcome:
        return "outcome present, value differs"
    return "missing"


def main():
    sb = create_client(os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    key = pd.ExcelFile(ROOT / "data" / "8WR QEX Combined.xlsx").parse("Sheet1")
    key.columns = [str(c).replace("\xa0", " ").strip() for c in key.columns]
    key = key[key["StudyID"].notna()].copy()
    key["sid"] = key["StudyID"].astype(float).astype(int).astype(str)

    docs = sb.table("documents").select("filename").eq("rag_project_id", PROJ).execute().data
    names = [d["filename"] for d in docs]
    mapping = {sid: hits[0] for sid in key["sid"].unique()
               for hits in [[n for n in names if sid in n]] if len(hits) == 1}

    counts = Counter()
    samples = {}
    for sid, group in key.groupby("sid"):
        if sid not in mapping:
            continue
        rows = fetch_all(sb.table("effect_estimates").select("effect_size,standard_error,outcome_name")
                         .eq("rag_project_id", PROJ).eq("doc_key", mapping[sid])
                         .eq("source", "tables_v1"))
        ests = [r["effect_size"] for r in rows if r.get("effect_size") is not None]
        ses = [r["standard_error"] for r in rows if r.get("standard_error") is not None]
        by_outcome = {norm(r.get("outcome_name")) for r in rows if norm(r.get("outcome_name"))}
        try:
            content = load_content(PROJ, mapping[sid], STUDY / "content")
        except Exception:
            content = []
        blob = " ".join(str(item.get("text") or "") for item in content)
        title = next((str(item.get("text") or "") for item in content if item.get("type") == "title"), "")
        table_count = sum(1 for item in content if item.get("type") == "table")
        if looks_like_review(blob, title):
            # A review has no results of its own; its absence from the rows is not an extraction gap.
            for _, row in group.iterrows():
                for column, label in (("Coeff reg", "estimate"), ("SE reg", "se")):
                    if num(row.get(column)) is not None:
                        counts[(label, "document is a review")] += 1
            continue
        if looks_like_wrong_version(blob, table_count):
            # The mapped document is a brief or summary; the study's paper is not in the collection.
            for _, row in group.iterrows():
                for column, label in (("Coeff reg", "estimate"), ("SE reg", "se")):
                    if num(row.get(column)) is not None:
                        counts[(label, "document is not the paper")] += 1
            continue
        for _, row in group.iterrows():
            outcome = row.get("Outcome name")
            for column, values, label in (("Coeff reg", ests, "estimate"), ("SE reg", ses, "se")):
                value = num(row.get(column))
                if value is None:
                    continue
                kind = classify(value, values, outcome, by_outcome)
                counts[(label, kind)] += 1
                if kind != "exact":
                    samples.setdefault((label, kind), []).append(
                        (sid, str(outcome)[:60], value, os.path.basename(mapping[sid])[:30]))

    lines = ["# Missing-estimate audit", "",
             "Why hand-typed values have no exact match in the stored rows.", ""]
    for label in ("estimate", "se"):
        total = sum(v for (l, _), v in counts.items() if l == label)
        exact = counts[(label, "exact")]
        lines += [f"## {label.capitalize()}", "",
                  f"Exact match {exact} of {total} ({100 * exact / max(1, total):.0f}%). Breakdown:", "",
                  "| Why | Count |", "| --- | --- |"]
        for kind in ("rounding 2dp", "rounding 1%", "sign", "scale x100", "scale x0.01",
                     "scale x1000", "scale x0.001", "outcome present, value differs",
                     "document is not the paper", "document is a review", "missing"):
            if counts[(label, kind)]:
                lines.append(f"| {kind} | {counts[(label, kind)]} |")
        lines.append("")
        for kind in ("rounding 2dp", "rounding 1%", "sign", "outcome present, value differs", "missing"):
            if samples.get((label, kind)):
                lines.append(f"Samples, {kind}:")
                for sid, outcome, value, doc in samples[(label, kind)][:5]:
                    lines.append(f"- {sid}: {outcome} = {value} ({doc})")
                lines.append("")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines).encode("ascii", "replace").decode("ascii"))
    print(f"\nwritten to {REPORT}")


if __name__ == "__main__":
    main()

