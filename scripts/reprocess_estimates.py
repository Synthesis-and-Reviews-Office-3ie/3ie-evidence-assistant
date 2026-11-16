"""Re-extract documents in paced batches, resuming where the last batch stopped.

Re-extraction is the IO-sensitive part: every document is a read of its rows, a replace, and an insert of
rows that carry 1536-dimension vectors. The batch size and a pause between documents are the throttle, and
a marker file records what has been done so a later batch does not repeat work.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\LucasSempe\OneDrive - International Initiative for Impact Evaluation\Desktop\Gen AI tools\apps\devchat")
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from src.extraction.store_estimates import extract_and_store  # noqa: E402
from supabase import create_client  # noqa: E402

PROJECT = "7efdc60e-e863-480c-929e-616574725e5f"
MARKER = ROOT / ".cache" / "reprocess_done.json"
BATCH = int(sys.argv[1]) if len(sys.argv) > 1 else 8
PAUSE = int(os.environ.get("DOC_PAUSE_SECONDS") or 15)

sb = create_client(os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_ROLE_KEY"])
names = [d["filename"] for d in
         sb.table("documents").select("filename").eq("rag_project_id", PROJECT).order("filename").execute().data]
done = set(json.loads(MARKER.read_text(encoding="utf-8"))) if MARKER.exists() else set()
todo = [n for n in names if n not in done][:BATCH]
print(f"documents {len(names)} | already done {len(done)} | this batch {len(todo)}")
for name in todo:
    print("  ", name[:80])

if todo:
    totals = asyncio.run(extract_and_store(PROJECT, doc_keys=todo, log=print))
    done.update(todo)
    MARKER.parent.mkdir(parents=True, exist_ok=True)
    MARKER.write_text(json.dumps(sorted(done), indent=1), encoding="utf-8")
    print("batch totals:", totals)
    print(f"remaining after this batch: {len(names) - len(done)}")
else:
    print("nothing left to re-extract")
