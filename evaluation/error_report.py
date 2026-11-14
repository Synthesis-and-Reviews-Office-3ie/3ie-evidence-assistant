"""
Every remaining extraction error, itemised.

For each hand-typed estimate and standard error with no exact match in the stored rows, print why,
with the nearest stored value for context. The point is to make the residual error legible: absent
papers, rounding, sign, units, reviews, and genuinely missed values.

Read-only, no model calls. Writes evaluation/results/error_report_<date>.md.
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

from evaluation.usage_study import load_content  # noqa: E402
from src.extraction.provenance import looks_like_review, looks_like_wrong_version  # noqa: E402

PROJ = "7efdc60e-e863-480c-929e-616574725e5f"
STUDY = ROOT / "evaluation" / "results" / "usage_study" / PROJ
REPORT = ROOT / "evaluation" / "results" / f"error_report_{date.today().isoformat()}.md"


def num(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", "").replace("\xa0", " "))
    return float(m.group()) if m else None


def norm(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def why(value, values, outcome, outcomes_present):
    if any(abs(v - value) < 1e-6 for v in values):
        return "exact"
    if any(round(v, 2) == round(value, 2) for v in values):
        return "rounding 2dp"
    if any(abs(v - value) / max(abs(value), abs(v), 1e-9) < 0.01 for v in values):
        return "rounding 1%"
    if any(abs(v + value) < 1e-6 for v in values):
        return "sign flipped"
    for factor, name in ((100, "x100"), (0.01, "x0.01"), (1000, "x1000"), (0.001, "x0.001")):
        if any(abs(v - value * factor) / max(abs(value * factor), abs(v), 1e-9) < 1e-6 for v in values):
            return f"unit {name}"
    if norm(outcome) and norm(outcome) in outcomes_present:
        return "outcome present, value differs"
    return "value not found"


def main():
    sb = create_client(os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    key = pd.ExcelFile(ROOT / "data" / "8WR QEX Combined.xlsx").parse("Sheet1")
    key.columns = [str(c).replace("\xa0", " ").strip() for c in key.columns]
    key = key[key["StudyID"].notna()].copy()
    key["sid"] = key["StudyID"].astype(float).astype(int).astype(str)
    names = [d["filename"] for d in sb.table("documents").select("filename").eq("rag_project_id", PROJ).execute().data]
    mapping = {sid: hits[0] for sid in key["sid"].unique()
               for hits in [[n for n in names if sid in n]] if len(hits) == 1}

    summary = Counter()
    lines: list = []
    details: list = []
    for sid, group in key.groupby("sid"):
        if sid not in mapping:
            continue
        doc = mapping[sid]
        rows = (sb.table("effect_estimates").select("effect_size,standard_error,outcome_name")
                .eq("rag_project_id", PROJ).eq("doc_key", doc).eq("source", "tables_v1")
                .limit(5000).execute().data)
        ests = [r["effect_size"] for r in rows if r.get("effect_size") is not None]
        ses = [r["standard_error"] for r in rows if r.get("standard_error") is not None]
        present = {norm(r.get("outcome_name")) for r in rows if norm(r.get("outcome_name"))}
        content = load_content(PROJ, doc, STUDY / "content") if (STUDY / "content").exists() else []
        text = " ".join(str(i.get("text") or "") for i in content)
        title = next((str(i.get("text") or "") for i in content if i.get("type") == "title"), "")
        tables = sum(1 for i in content if i.get("type") == "table")
        if looks_like_review(text, title):
            document_state = "review"
        elif looks_like_wrong_version(text, tables):
            document_state = "wrong version"
        else:
            document_state = "paper present"
        for _, row in group.iterrows():
            outcome = row.get("Outcome name")
            for column, values, label in (("Coeff reg", ests, "estimate"), ("SE reg", ses, "se")):
                value = num(row.get(column))
                if value is None:
                    continue
                kind = "document is a review" if document_state == "review" else (
                    "document is not the paper" if document_state == "wrong version" else
                    why(value, values, outcome, present))
                summary[(label, kind)] += 1
                if kind != "exact":
                    nearest = min(values, key=lambda v: abs(v - value)) if values else None
                    details.append((sid, doc, str(outcome)[:55], label, value, nearest,
                                    kind, len(rows), document_state))

    rows_total = {label: sum(v for (l, _), v in summary.items() if l == label) for label in ("estimate", "se")}
    lines += ["# Remaining extraction errors", "",
              f"Studies mapped to the key: {len(mapping)}. Hand-typed estimates: {rows_total['estimate']}, "
              f"standard errors: {rows_total['se']}.", "",
              "## Summary", "", "| Category | Estimates | Standard errors |", "| --- | --- | --- |"]
    for kind in ("exact", "document is not the paper", "document is a review", "rounding 2dp",
                 "rounding 1%", "sign flipped", "unit x100", "unit x0.01", "unit x1000", "unit x0.001",
                 "outcome present, value differs", "value not found"):
        if summary[("estimate", kind)] or summary[("se", kind)]:
            lines.append(f"| {kind} | {summary[('estimate', kind)]} | {summary[('se', kind)]} |")
    lines += ["", "## Every remaining error", "",
              "`nearest` is the closest stored value for that study, for context.", "",
              "| Study | Document | Outcome | Field | Hand | Nearest stored | Why | Rows | Document state |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for sid, doc, outcome, label, value, nearest, kind, count, state in details:
        lines.append(f"| {sid} | {doc[:28]} | {outcome} | {label} | {value} | {nearest} | {kind} | {count} | {state} |")

    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:40]).encode("ascii", "replace").decode("ascii"))
    print(f"\nwritten to {REPORT}")


if __name__ == "__main__":
    main()
