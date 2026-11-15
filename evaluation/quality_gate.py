"""The check that runs on a schedule and fails when recall drops.

Every measurement so far has been run by hand, which is how a change that halved the stored rows for a
paper went unnoticed until a hand-typed key was compared. This reads the stored rows with the paged
reader, compares them with the hand-typed key under the printed-precision rule, prints the same figures
the reports quote, and exits non-zero when the matched count falls below the baseline in
`evaluation/results/recall_baseline.json`.

It reads the database and the key only. It calls no model, so it is cheap enough to run weekly and on
every change to the answer or extraction path. `--update-baseline` rewrites the baseline from the
current numbers, which is a deliberate act after a change is understood.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import pandas as pd  # noqa: E402

from evaluation.stored_rows import classify_miss, fetch_all  # noqa: E402
from supabase import create_client  # noqa: E402

PROJECT = os.environ.get("RAG_PROJECT_ID") or "7efdc60e-e863-480c-929e-616574725e5f"
KEY_FILE = ROOT / "data" / "8WR QEX Combined.xlsx"
BASELINE = ROOT / "evaluation" / "results" / "recall_baseline.json"
REPORT = ROOT / "evaluation" / "results" / f"quality_gate_{date.today().isoformat()}.md"
KEY_OBJECT = os.environ.get("RECALL_KEY_OBJECT") or "reference/8WR QEX Combined.xlsx"


def key_path() -> Path:
    """The key on disk, fetched from private object storage when the checkout does not have it.

    `data/` is not in the public repository, so CI reads the same file from the private bucket the app
    already uses and keeps it out of the checkout. Without those credentials the path stays missing and
    the gate reports a skip.
    """
    if KEY_FILE.exists():
        return KEY_FILE
    bucket = os.environ.get("R2_BUCKET_NAME") or "devchat-pdfs"
    if not os.environ.get("R2_ACCESS_KEY_ID"):
        return KEY_FILE
    from evaluation.usage_study import _r2

    body = _r2().get_object(Bucket=bucket, Key=KEY_OBJECT)["Body"].read()
    path = Path(tempfile.gettempdir()) / "recall_key.xlsx"
    path.write_bytes(body)
    print(f"key read from private storage: s3://{bucket}/{KEY_OBJECT}")
    return path


def num(value):
    if value is None:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", "").replace("\xa0", " "))
    return float(match.group()) if match else None


def key_values(path: Path = KEY_FILE) -> dict:
    """The hand-typed estimate and standard error of every study, by 8WR study id."""
    key = pd.ExcelFile(path).parse("Sheet1")
    key.columns = [str(c).replace("\xa0", " ").strip() for c in key.columns]
    key = key[key["StudyID"].notna()].copy()
    key["sid"] = key["StudyID"].astype(float).astype(int).astype(str)
    out: dict = {}
    for _, row in key.iterrows():
        entry = out.setdefault(row["sid"], {"estimate": [], "se": []})
        for column, field in (("Coeff reg", "estimate"), ("SE reg", "se")):
            value = num(row.get(column))
            if value is not None:
                entry[field].append(value)
    return out


def measure(path: Path = KEY_FILE) -> dict:
    """Matched, rounded, absent and total for estimates and standard errors."""
    sb = create_client(os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    key = key_values(path)
    names = [d["filename"] for d in
             sb.table("documents").select("filename").eq("rag_project_id", PROJECT).execute().data]
    mapping = {sid: hits[0] for sid in key for hits in [[n for n in names if sid in n]] if len(hits) == 1}
    out = {"studies": len(mapping), "mapped_of": len(key)}
    for label, field in (("estimate", "estimate"), ("se", "se")):
        counts = {"exact": 0, "rounded": 0, "absent": 0}
        for sid, name in mapping.items():
            rows = fetch_all(sb.table("effect_estimates")
                             .select("effect_size,standard_error")
                             .eq("rag_project_id", PROJECT).eq("doc_key", name).eq("source", "tables_v1"))
            stored = [r["effect_size"] for r in rows if r.get("effect_size") is not None] if field == "estimate" \
                else [r["standard_error"] for r in rows if r.get("standard_error") is not None]
            for value in key[sid][field]:
                verdict = classify_miss(value, stored)
                counts[verdict] += 1
        counts["matched"] = counts["exact"] + counts["rounded"]
        counts["total"] = counts["exact"] + counts["rounded"] + counts["absent"]
        out[label] = counts
    out["matched"] = out["estimate"]["matched"] + out["se"]["matched"]
    out["total"] = out["estimate"]["total"] + out["se"]["total"]
    return out


def main() -> int:
    path = key_path()
    if not path.exists():
        # The repository is public and the hand-typed key is 3ie's own coding, so `data/` is not in it.
        # The gate compares wherever the key is present, locally or from private storage, and says so
        # plainly when it has neither rather than failing on a file it must not have.
        print(f"::notice::Recall gate skipped: {KEY_FILE.relative_to(ROOT)} is not present and the "
              "private storage credentials are not set. The key stays out of the public repository.")
        return 0
    current = measure(path)
    baseline = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else None
    if "--update-baseline" in sys.argv or baseline is None:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
        reason = "written" if baseline is None else "updated"
        print(f"baseline {reason} from the current numbers: {BASELINE.relative_to(ROOT)}")

    lines = [f"# Quality gate {date.today().isoformat()}", "",
             f"Studies mapped: {current['studies']} of {current['mapped_of']}.", ""]
    for label in ("estimate", "se"):
        counts = current[label]
        lines.append(f"- {label}: matched {counts['matched']} of {counts['total']} "
                     f"({counts['exact']} exact, {counts['rounded']} at printed precision, "
                     f"{counts['absent']} absent)")
    lines.append(f"- combined: {current['matched']} of {current['total']}")

    failures = []
    if baseline is not None and "--update-baseline" not in sys.argv:
        for label in ("estimate", "se"):
            was, now = baseline[label]["matched"], current[label]["matched"]
            if now < was:
                failures.append(f"{label} matched fell from {was} to {now}")
            elif now > was:
                lines.append(f"- {label} improved from {was} to {now}; update the baseline when the "
                             "change is understood (`--update-baseline`)")
    if failures:
        lines += ["", "## Failed", ""] + [f"- {reason}" for reason in failures]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    for reason in failures:
        print(f"FAIL: {reason}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
