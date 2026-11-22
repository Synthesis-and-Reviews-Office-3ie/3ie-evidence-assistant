"""Check gallery entries for structure: required fields, numeric values, bounding boxes, unique ids.

Usage: python scripts/validate_gallery.py [--entries evaluation/gallery/entries] [--pdfs "data/PDFs of included programs"]
Exit code 1 if any entry has an error. Warnings do not fail.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REQUIRED = ["id", "status", "checked_against_page", "source", "tags", "snippet", "context_needed",
            "stored_rows", "not_stored", "rule"]
SOURCE = ["doc_key", "pdf", "page", "table_label", "bbox_points", "render_rotation"]
ROW = ["outcome", "arm", "time_point", "subgroup_or_population", "value", "se", "effect_type"]
NUMERIC = ["value", "se", "t_stat", "ci_lower", "ci_upper", "bound_lower", "bound_upper"]


def check(path: Path, pdfs: Path) -> tuple[list[str], list[str]]:
    err, warn = [], []
    try:
        e = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"invalid JSON: {exc}"], []
    for k in REQUIRED:
        if k not in e:
            err.append(f"missing field {k}")
    if e.get("id") and e["id"] != path.stem:
        err.append(f"id {e['id']} does not match file name")
    src = e.get("source", {})
    for k in SOURCE:
        if k not in src:
            err.append(f"source missing {k}")
    if src.get("pdf") and not (pdfs / src["pdf"]).exists():
        err.append(f"PDF not found: {src['pdf']}")
    bb = src.get("bbox_points")
    if bb and (len(bb) != 4 or bb[0] >= bb[2] or bb[1] >= bb[3]):
        err.append(f"bad bbox {bb}")
    if e.get("checked_against_page") is not True:
        warn.append("not yet checked against the page")
    for i, r in enumerate(e.get("stored_rows", [])):
        for k in ROW:
            if k not in r:
                err.append(f"row {i} missing {k}")
        for k in NUMERIC:
            v = r.get(k)
            if v is not None and not isinstance(v, (int, float)):
                err.append(f"row {i} {k} is not a number: {v!r}")
        if r.get("outcome") and r.get("arm") and r["outcome"].strip().lower() == r["arm"].strip().lower():
            err.append(f"row {i} outcome equals arm")
        if r.get("se") is not None and isinstance(r["se"], (int, float)) and r["se"] < 0:
            err.append(f"row {i} negative SE (a t-statistic?)")
    for i, n in enumerate(e.get("not_stored", [])):
        if not n.get("reason"):
            err.append(f"not_stored {i} has no reason")
    if not e.get("stored_rows") and not e.get("not_stored"):
        err.append("entry stores nothing and explains nothing")
    return err, warn


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--entries", default="evaluation/gallery/entries")
    ap.add_argument("--pdfs", default="data/PDFs of included programs")
    a = ap.parse_args()
    bad = 0
    for p in sorted(Path(a.entries).glob("*.json")):
        err, warn = check(p, Path(a.pdfs))
        status = "ERROR" if err else ("warn" if warn else "ok")
        print(f"{status:5} {p.stem}")
        for m in err + warn:
            print(f"      {m}")
        bad += bool(err)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
