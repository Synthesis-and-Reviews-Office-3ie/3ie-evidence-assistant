"""Build study cards for a set of documents and write a readable review file.

One model call per document. Cards are saved beside the extraction output in R2 and to
data/study_cards/ (git-ignored). The review file at evaluation/results/study_cards_review.md is for Lucas.

    python scripts/build_study_cards.py --keys C:\\...\\never_used.json
    python scripts/build_study_cards.py --doc <doc_key>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import boto3
import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.extraction.store_estimates import DEFAULT_MODEL  # noqa: E402
from src.extraction.study_cards import build_card, document_text  # noqa: E402

PROJECT = "7efdc60e-e863-480c-929e-616574725e5f"
REVIEW = ROOT / "evaluation/results/study_cards_review.md"


def s3_client():
    return boto3.client(
        "s3", endpoint_url="https://" + os.environ["R2_ACCOUNT_ID"] + ".r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")


def load_content(s3, bucket, key):
    return json.loads(s3.get_object(Bucket=bucket, Key=f"rags/{PROJECT}/outputs/json/{key}.json")["Body"].read())


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keys", help="JSON file with a list of document keys")
    ap.add_argument("--doc", action="append", default=[], help="a document key (repeatable)")
    ap.add_argument("--out", default=str(REVIEW))
    args = ap.parse_args()

    keys = list(args.doc)
    if args.keys:
        keys += json.loads(Path(args.keys).read_text(encoding="utf-8"))
    keys = [k for k in dict.fromkeys(keys)]

    bucket = os.environ.get("R2_BUCKET_NAME", "devchat-pdfs")
    s3 = s3_client()
    out_dir = ROOT / "data/study_cards"
    out_dir.mkdir(parents=True, exist_ok=True)

    cards = []
    async with httpx.AsyncClient(timeout=300,
                                 headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"}) as client:
        for key in keys:
            try:
                content = load_content(s3, bucket, key).get("content_list") or []
            except Exception as exc:
                print(f"skip {key[:40]}: {type(exc).__name__}")
                continue
            title, text = document_text(content)
            card = await build_card(client, DEFAULT_MODEL, title, text)
            card["doc_key"], card["title"] = key, title
            cards.append(card)
            (out_dir / f"{key}.json").write_text(json.dumps(card, indent=1), encoding="utf-8")
            try:
                s3.put_object(Bucket=bucket, Key=f"rags/{PROJECT}/study_cards/{key}.json",
                              Body=json.dumps(card, indent=1).encode("utf-8"),
                              ContentType="application/json")
            except Exception as exc:
                print(f"  (R2 store failed for {key[:30]}: {type(exc).__name__})")
            n_main = sum(1 for t in card["tables"] if t["role"] == "main effect")
            print(f"{key[:44]:44s} methods={len(card['methods'])} arms={len(card['arms'])} "
                  f"rounds={len(card['rounds'])} tables={len(card['tables'])} main={n_main}", flush=True)

    lines = [f"# Study cards for review ({len(cards)} documents)", ""]
    for card in cards:
        lines += [f"## {card['title'] or card['doc_key']}", "",
                  f"`{card['doc_key']}`", "",
                  f"- Methods: {', '.join(card['methods']) or '(none)'}",
                  f"- Arms: {', '.join(card['arms']) or '(none)'}",
                  f"- Comparison group: {card['comparison_group'] or '(none)'}",
                  f"- Rounds: " + ("; ".join(
                      f"{r.get('name','')} ({r.get('dates','')}; {r.get('since_baseline','')})"
                      for r in card['rounds']) or "(none)"),
                  f"- Populations: {', '.join(card['populations']) or '(none)'}",
                  f"- Sign conventions and units: " + ("; ".join(card['sign_conventions']) or "(none)"), ""]
        if card["tables"]:
            lines += ["| Table | Page | Role | Evidence |", "| --- | --- | --- | --- |"]
            for t in card["tables"]:
                quote = str((t.get("evidence") or {}).get("quote") or "")[:60].replace("|", "/")
                lines.append(f"| {t['label']} | {t.get('page','')} | {t['role']} | {quote} |")
        else:
            lines.append("_No tables recorded._")
        lines.append("")
    Path(args.out).write_text("\n".join(lines), encoding="utf-8")
    print("wrote", args.out, "and", out_dir)


asyncio.run(main())
