"""Which studies cannot be scored against the document we hold, and what to fetch.

Two papers in the collection are not the paper the hand-typed key was coded from. 121766336 is the
12-page Bab Amal policy brief, whose results are figures and which holds no table named "Policy Brief
Estimates for Primary Outcomes", and 121295229's held document is a 16-page journal article whose key
cites journal page 479. A recall denominator that counts their values as extractor failures makes the
extractor look worse than it is and hides the real task, which is retrieving a document.

This runs over the mapped studies, gives each document a verdict, and writes the queue. It reads only
and calls no model.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import pandas as pd  # noqa: E402

from evaluation.stored_rows import (  # noqa: E402
    classify_miss,
    corrected,
    documents_for,
    fetch_all,
    load_errata,  # noqa: E402
    load_overrides,
)
from evaluation.usage_study import load_content  # noqa: E402
from src.extraction.provenance import looks_like_review, looks_like_wrong_version  # noqa: E402
from supabase import create_client  # noqa: E402

PROJECT = os.environ.get("RAG_PROJECT_ID") or "7efdc60e-e863-480c-929e-616574725e5f"
KEY_FILE = ROOT / "data" / "8WR QEX Combined.xlsx"
QUEUE = ROOT / "evaluation" / "results" / f"retrieval_queue_{date.today().isoformat()}.md"
MAX_PAGE_GAP = 50      # a key page number far beyond the document means another document


def num(value):
    if value is None:
        return None
    text = str(value).replace(",", "").replace("\xa0", " ").replace("\u2212", "-").replace("\u2013", "-").replace("\u2014", "-")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group()) if match else None


def key_values() -> dict:
    """The hand-typed estimate and standard error of every study, by 8WR study id."""
    key = pd.ExcelFile(KEY_FILE).parse("Sheet1")
    key.columns = [str(c).replace("\xa0", " ").strip() for c in key.columns]
    key = key[key["StudyID"].notna()].copy()
    key["sid"] = key["StudyID"].astype(float).astype(int).astype(str)
    out: dict = {}
    for _, row in key.iterrows():
        entry = out.setdefault(row["sid"], {"estimate": [], "se": [], "pages": []})
        if num(row.get("Coeff reg")) is not None:
            entry["estimate"].append(num(row.get("Coeff reg")))
        if num(row.get("SE reg")) is not None:
            entry["se"].append(num(row.get("SE reg")))
        page = num(row.get("Page"))
        if page is None:
            match = re.search(r"page[s]?\s*[:.]?\s*(\d+)", str(row.get("Source") or ""), re.I)
            page = float(match.group(1)) if match else None
        if page:
            entry["pages"].append(int(page))
    return out


def verdict(content: list) -> str:
    """Why the held document cannot be scored, or "" when it can.

    Only the document's own shape is read here. A key page number far beyond the document is
    supporting evidence and is applied by the caller, because a published article numbers its pages
    from its journal, and three studies here cite such pages while every value was found in the text.
    """
    text = " ".join(str(item.get("text") or "") for item in content)
    title = next((str(item.get("text") or "") for item in content if item.get("type") == "title"), "")
    tables = sum(1 for item in content if item.get("type") == "table")
    if looks_like_review(text, title):
        return "document is a review"
    if looks_like_wrong_version(text, tables):
        return "document is a summary, not the study"
    return ""


def main() -> None:
    sb = create_client(os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    key = key_values()
    names = [d["filename"] for d in
             sb.table("documents").select("filename").eq("rag_project_id", PROJECT).execute().data]
    # A study may have more than one document, such as a brief and the analytic note behind it.
    overrides = load_overrides()
    mapping = {sid: documents_for(sid, names, overrides) for sid in key}
    mapping = {sid: docs for sid, docs in mapping.items() if docs}

    errata = load_errata()
    # One pass over the project's rows, grouped by document: the small Supabase instance budgets disk IO.
    stored: dict[str, list] = {}
    for row in fetch_all(sb.table("effect_estimates").select("doc_key,effect_size,standard_error")
                         .eq("rag_project_id", PROJECT).eq("source", "tables_v1")):
        stored.setdefault(row.get("doc_key"), []).append(row)
    matched = total = 0
    flagged_values = 0
    queue = []
    mapping_notes = []
    for sid, docs in sorted(mapping.items()):
        name = docs[0]
        try:
            content = load_content(PROJECT, name, ROOT / "evaluation" / "results" / "usage_study" / PROJECT / "content")
        except Exception:
            content = []
        document_pages = max(((item.get("page_idx") or 0) + 1 for item in content), default=0)
        why = verdict(content)
        rows = []
        for doc in docs:
            rows += stored.get(doc, [])
        estimates = [r["effect_size"] for r in rows if r.get("effect_size") is not None]
        errors = [r["standard_error"] for r in rows if r.get("standard_error") is not None]
        miss_e = [v for v in key[sid]["estimate"]
                  if classify_miss(corrected(sid, "estimate", v, errata), estimates) == "absent"]
        miss_s = [v for v in key[sid]["se"]
                  if classify_miss(corrected(sid, "se", v, errata), errors) == "absent"]
        pages_note = ""
        if not why and (miss_e or miss_s) and key[sid]["pages"] and document_pages:
            highest = max(key[sid]["pages"])
            if highest - document_pages >= MAX_PAGE_GAP:
                pages_note = (f"key cites page {highest} of a {document_pages}-page document, so its page "
                              "numbering is not the document's; check the text before retrieving")
        matched += (len(key[sid]["estimate"]) - len(miss_e)) + (len(key[sid]["se"]) - len(miss_s))
        total += len(key[sid]["estimate"]) + len(key[sid]["se"])
        if why and (miss_e or miss_s):
            # A document that is not the study at all, and values that no document of the study supplies:
            # those cannot be reached here, so they are set aside and the study goes to the retrieval queue.
            # A study whose second document supplies everything is not queued, even if its first is a summary.
            flagged_values += len(miss_e) + len(miss_s)
            queue.append((sid, name, why, len(miss_e), len(miss_s)))
        elif pages_note:
            # The values may well be in the document; the page numbering differs, so the text is
            # checked before anything is retrieved. These stay in the denominator as misses.
            mapping_notes.append((sid, name, pages_note, len(miss_e), len(miss_s)))

    lines = ["# Retrieval queue", "",
             f"Studies scored against a document that is not the one the key was coded from: {len(queue)} "
             f"of {len(mapping)}. The {flagged_values} hand-typed values below are set aside, which is what "
             "makes the attainable recall in the last line higher than the measured one.", ""]
    for sid, name, why, miss_e, miss_s in queue:
        lines.append(f"- **{sid}** ({name[:52]}): {why}; {miss_e} estimates and {miss_s} standard errors not found")
    if mapping_notes:
        lines += ["", f"Studies that cite a page their document does not have: {len(mapping_notes)}. Their "
                      "values stay in the denominator, because the text may hold them and only the page "
                      "numbering differs.", ""]
        for sid, name, note, miss_e, miss_s in mapping_notes:
            lines.append(f"- {sid} ({name[:52]}): {note}; {miss_e} estimate(s) and {miss_s} standard error(s) not found")
    lines += ["", f"Recall as measured: {matched} of {total}. "
                  f"Attainable recall: {matched} of {total - flagged_values}."]
    QUEUE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert matched <= total
    print(f"studies {len(mapping)} | flagged {len(queue)} | values set aside {flagged_values}")
    print(f"measured recall {matched}/{total} ({100 * matched / max(1, total):.0f}%) | "
          f"attainable {matched}/{total - flagged_values} ({100 * matched / max(1, total - flagged_values):.0f}%)")
    print(f"queue written to {QUEUE.relative_to(ROOT)}")
    for sid, _name, why, miss_e, miss_s in queue:
        print(f"  {sid}: {why} (est {miss_e}, se {miss_s})")


if __name__ == "__main__":
    main()

