"""
Which documents need the vision pass.

Reads the parsed content lists already cached by the usage study and flags each document that either
has garbled table text or has no parsed tables at all. Those are the documents where the text path
cannot be trusted, and the ones an automatic-vision re-extraction would read from page images.

Read-only, no model calls. Writes a report to evaluation/results/vision_scan_<date>.md.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evaluation.usage_study import load_content  # noqa: E402
from src.extraction.page_vision import garbled_table_pages, table_image_pages  # noqa: E402
from src.extraction.provenance import looks_like_review, looks_like_wrong_version  # noqa: E402
from src.extraction.table_rules import looks_garbled  # noqa: E402

PROJ = "7efdc60e-e863-480c-929e-616574725e5f"
STUDY = ROOT / "evaluation" / "results" / "usage_study" / PROJ
REPORT = ROOT / "evaluation" / "results" / f"vision_scan_{date.today().isoformat()}.md"


def main() -> None:
    rows = []
    reasons = Counter()
    for label in sorted((STUDY / "labels").glob("*.json")):
        doc_key = json.loads(label.read_text(encoding="utf-8"))["doc_key"]
        try:
            content = load_content(PROJ, doc_key, STUDY / "content")
        except Exception:
            continue
        tables = [i for i in content if i.get("type") == "table"]
        images = [i for i in content if i.get("type") == "image"]
        garbled = sum(1 for t in tables if looks_garbled(t.get("text")))
        garbled_pages = garbled_table_pages(content)
        image_pages = table_image_pages(content)
        text = " ".join(str(i.get("text") or "") for i in content)
        title = next((str(i.get("text") or "") for i in content if i.get("type") == "title"), "")
        review = looks_like_review(text, title)
        wrong = looks_like_wrong_version(text, len(tables))
        needs = (bool(garbled_pages) or not tables) and not review
        if review:
            reason = "review, skip"
            reasons["review, skip"] += 1
        elif garbled_pages:
            reason = "garbled tables"
            reasons["garbled tables"] += 1
        elif not tables:
            reason = "no tables"
            reasons["no tables"] += 1
        else:
            reason = ""
        rows.append((needs, doc_key, len(tables), len(images), garbled, len(garbled_pages),
                     len(image_pages), len(text), wrong, reason))

    rows.sort(reverse=True)
    affected = [r for r in rows if r[0]]
    lines = [
        "# Documents that need the vision pass",
        "",
        f"Documents scanned: {len(rows)}. Need vision (garbled tables or no tables): {len(affected)}. "
        f"Garbled tables: {reasons['garbled tables']}; no tables: {reasons['no tables']}; "
        f"reviews skipped: {reasons['review, skip']}.",
        "",
        "| Document | Tables | Images | Garbled tables | Garbled pages | Image pages | Chars | Wrong version? | Reason |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for _, doc_key, tables, images, garbled, gpages, ipages, chars, wrong, reason in affected:
        lines.append(f"| {doc_key[:45]} | {tables} | {images} | {garbled} | {gpages} | {ipages} | "
                     f"{chars} | {'yes' if wrong else ''} | {reason} |")
    report = "\n".join(lines)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(report, encoding="utf-8")
    print(report.encode("ascii", "replace").decode("ascii"))
    print(f"\nwritten to {REPORT}")


if __name__ == "__main__":
    main()
