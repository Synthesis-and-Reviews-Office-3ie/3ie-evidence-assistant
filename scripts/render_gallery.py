"""Render the table gallery: one crop per entry from the local PDF, and a review page.

Usage: python scripts/render_gallery.py [--entries evaluation/gallery/entries] [--pdfs "data/PDFs of included programs"]

Each entry JSON names its PDF (relative to --pdfs), page, bounding box in PDF points and a render rotation.
Crops go to <entries>/../images/ and the review page to <entries>/../review.html. Both are git-ignored:
crops of published pages are never committed, and can always be re-made from the JSON.
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

import fitz  # PyMuPDF

DPI = 200


def render(entry: dict, pdfs: Path, images: Path) -> str:
    src = entry["source"]
    page = fitz.open(pdfs / src["pdf"])[src["page"] - 1]
    clip = fitz.Rect(*src["bbox_points"]) if src.get("bbox_points") else None
    m = fitz.Matrix(DPI / 72, DPI / 72).prerotate(src.get("render_rotation", 0))
    out = images / f"{entry['id']}.png"
    page.get_pixmap(matrix=m, clip=clip).save(out)
    return out.name


def rows_table(rows: list[dict], cols: list[str]) -> str:
    head = "".join(f"<th>{html.escape(c)}</th>" for c in cols)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape('' if r.get(c) is None else str(r.get(c)))}</td>" for c in cols) + "</tr>"
        for r in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def card(entry: dict, img: str) -> str:
    t = entry["tags"]
    tags = " · ".join(t.get("method", []) + t.get("format", [])) + "<br>" + " · ".join(t.get("layout", []))
    stored = rows_table(entry["stored_rows"], ["outcome", "arm", "time_point", "subgroup_or_population",
                                               "value", "se", "effect_type"])
    skipped = rows_table(entry["not_stored"], ["cell", "reason"])
    pm = entry["tags"].get("picture_matters")
    src = entry["source"]
    return f"""
<section id="{html.escape(entry['id'])}">
  <h2>{html.escape(entry['id'])} <span class="st">{html.escape(entry.get('status', 'draft'))}</span></h2>
  <p class="src">{html.escape(src['pdf'])}, page {src['page']}, {html.escape(src.get('table_label', ''))}</p>
  <div class="grid">
    <div class="img"><img src="images/{img}" alt="{html.escape(src.get('table_label', ''))}"></div>
    <div class="ans">
      <p class="rule"><b>Rule.</b> {html.escape(entry['rule'])}</p>
      {f'<p class="pm"><b>Why the picture matters.</b> {html.escape(pm)}</p>' if pm else ''}
      <p class="ctx"><b>Context from the paper.</b> {html.escape(entry.get('context_needed', ''))}</p>
      <p class="tags">{tags}</p>
      <h3>Stored ({len(entry['stored_rows'])})</h3>{stored}
      <h3>Not stored</h3>{skipped}
    </div>
  </div>
</section>"""


CSS = """
:root{--bg:#fff;--fg:#1d1d1f;--mut:#666;--line:#ddd;--acc:#0b6e4f}
@media (prefers-color-scheme:dark){:root{--bg:#161616;--fg:#eee;--mut:#aaa;--line:#333;--acc:#5fd3a5}}
body{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;margin:0 16px 64px}
h1{font-size:20px}h2{font-size:16px;margin:0}h3{font-size:13px;margin:12px 0 4px}
section{border-top:2px solid var(--line);padding:16px 0}
.st{font-size:11px;color:var(--acc);border:1px solid var(--acc);border-radius:4px;padding:0 4px}
.src,.tags{color:var(--mut);font-size:12px}
.grid{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);gap:16px}
@media (max-width:900px){.grid{grid-template-columns:1fr}}
.img img{max-width:100%;border:1px solid var(--line);background:#fff}
table{border-collapse:collapse;width:100%;font-size:12px}
td,th{border-bottom:1px solid var(--line);padding:2px 4px;text-align:left;vertical-align:top}
.ans{max-height:80vh;overflow:auto}
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--entries", default="evaluation/gallery/entries")
    ap.add_argument("--pdfs", default="data/PDFs of included programs")
    a = ap.parse_args()
    entries_dir, pdfs = Path(a.entries), Path(a.pdfs)
    root = entries_dir.parent
    images = root / "images"
    images.mkdir(exist_ok=True)
    entries = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(entries_dir.glob("*.json"))]
    cards, toc = [], []
    for e in entries:
        try:
            img = render(e, pdfs, images)
        except Exception as exc:  # a missing PDF should not stop the page
            img = ""
            print(f"could not render {e['id']}: {exc}")
        cards.append(card(e, img))
        toc.append(f"<li><a href='#{html.escape(e['id'])}'>{html.escape(e['id'])}</a> ({e.get('status', 'draft')})</li>")
    page = (f"<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>Table gallery review</title><style>{CSS}</style><h1>Table gallery: {len(entries)} entries</h1>"
            f"<ol>{''.join(toc)}</ol>{''.join(cards)}")
    (root / "review.html").write_text(page, encoding="utf-8")
    print(f"{len(entries)} entries -> {root / 'review.html'}")


if __name__ == "__main__":
    main()
