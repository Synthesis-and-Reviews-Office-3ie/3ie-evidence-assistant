"""Why each remaining cell is unstored, checked against every stored row of the study.

The triage compares a cell with the rows on its own page. That is too strict for three reasons, and this pass
separates them: the value may be stored on another page of the same document, in another document of the same
study, or at a different printed precision. What is left after those tests is the real gap, and it is split
again by whether the page was read at all or only partly.

Reads the estimates once and the parsed content of the documents that still have unexplained cells.
"""

import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from evaluation.stored_rows import documents_for, fetch_all, load_overrides, matches  # noqa: E402
from evaluation.table_coverage import cell_values  # noqa: E402
from evaluation.usage_study import load_content  # noqa: E402
from supabase import create_client  # noqa: E402

PROJECT = os.environ.get("RAG_PROJECT_ID") or "7efdc60e-e863-480c-929e-616574725e5f"
CACHE = ROOT / "evaluation" / "results" / "usage_study" / PROJECT / "content"
CELLS = ROOT / "evaluation" / "results" / f"coverage_unexplained_{date.today().isoformat()}.json"
REPORT = ROOT / "evaluation" / "results" / f"coverage_deep_{date.today().isoformat()}.md"


def main() -> None:
    cells = json.loads(CELLS.read_text(encoding="utf-8"))
    sb = create_client(os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    names = [d["filename"] for d in
             sb.table("documents").select("filename").eq("rag_project_id", PROJECT).execute().data]
    overrides = load_overrides()

    stored_by_doc: dict = defaultdict(lambda: defaultdict(list))
    for row in fetch_all(sb.table("effect_estimates").select("doc_key,page,effect_size,standard_error")
                         .eq("rag_project_id", PROJECT).eq("source", "tables_v1")):
        for field in ("effect_size", "standard_error"):
            if row.get(field) is not None:
                stored_by_doc[row["doc_key"]][row.get("page")].append(row[field])

    buckets: Counter = Counter()
    by_doc: Counter = Counter()
    real_by_doc: Counter = Counter()
    examples: dict = defaultdict(list)
    page_count: dict = {}
    for cell in cells:
        doc = cell["doc"]
        if doc not in page_count:
            try:
                content = load_content(PROJECT, doc, CACHE)
                page_count[doc] = max(((i.get("page_idx") or 0) + 1 for i in content), default=0)
            except Exception:
                page_count[doc] = 0
        values = cell_values(cell["cell"]) or []
        page = cell["page"]
        on_page = stored_by_doc[doc].get(page, [])
        same_doc = [v for rows in stored_by_doc[doc].values() for v in rows]
        # Every document of the same study, found by the study id embedded in the document name when present.
        sid = next((s for s in re.findall(r"\d{9}", doc)), "")
        sibling = [value for name in (documents_for(sid, names, overrides) if sid else [])
                   for rows in stored_by_doc[name].values() for value in rows]

        if any(matches(v, on_page) for v in values):
            bucket = "on the page at a different precision"
        elif any(matches(v, same_doc) for v in values):
            bucket = "stored elsewhere in the same document"
        elif any(matches(v, sibling) for v in values):
            bucket = "stored in another document of the study"
        elif on_page:
            bucket = "table read but this cell omitted"
        else:
            bucket = "page has no stored rows"
        buckets[bucket] += 1
        by_doc[doc] += 1
        if bucket in ("table read but this cell omitted", "page has no stored rows"):
            real_by_doc[doc] += 1
        if len(examples[bucket]) < 4:
            examples[bucket].append(f"{doc[:30]} p{page}: row '{cell['row'][:30]}', cell {cell['cell'][:16]}")

    total = sum(buckets.values())
    real = sum(real_by_doc.values())
    lines = [f"# Why the remaining {total} cells are unstored", "",
             f"{total - real} of the {total} are stored somewhere in the study; the real gap is {real} cells, "
             f"in {len(real_by_doc)} documents.", "",
             "| Reason | Cells |", "| --- | --- |"]
    for bucket, count in buckets.most_common():
        lines.append(f"| {bucket} | {count} |")
    lines += ["", "Largest real gaps:", ""]
    for doc, count in real_by_doc.most_common(8):
        lines.append(f"- {count}: {doc[:72]}")
    lines += ["", "Examples:", ""]
    for bucket, items in examples.items():
        lines.append(f"**{bucket}**")
        for example in items:
            lines.append(f"- {example}")
        lines.append("")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"cells {total} across {len(by_doc)} documents")
    for bucket, count in buckets.most_common():
        print(f"  {bucket:42} {count}")
    print(f"report {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
