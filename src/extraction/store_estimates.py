"""
Extract effect estimates from processed documents and store them, embedded, in
effect_estimates (roadmap N6). Used by scripts/extract_estimates.py and by the Modal
pipeline after new documents are processed.

Needs SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, the R2_* variables, OPENROUTER_API_KEY
and COHERE_API_KEY. About 2.5 US cents per document with Haiku 5.5.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

import httpx

from src.extraction.consistency import flags_for
from src.extraction.dedupe import dedupe_rows
from src.extraction.effect_sizes import standardise
from src.extraction.identity import row_key
from src.extraction.table_estimates import extract_document
from src.extraction.table_rules import normalise_tables, reclassify_pipe_tables

SOURCE = "tables_v1"
DEFAULT_MODEL = "anthropic/claude-haiku-5.5"
DOC_CONCURRENCY = int(os.environ.get("DOC_CONCURRENCY") or 2)
INSERT_BATCH = 50  # rows carry 1536-d vectors, and the small Supabase instance drops large writes
ROOT = Path(__file__).resolve().parents[2]


def _load_gallery(root: Path) -> List[Dict[str, Any]]:
    """The worked gallery entries. Empty when the folder is absent, which leaves the reader unchanged."""
    folder = root / "evaluation" / "gallery" / "entries"
    entries = []
    if folder.exists():
        for path in sorted(folder.glob("*.json")):
            try:
                entries.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
    return entries


GALLERY = _load_gallery(ROOT)


def _load_card(s3, bucket: str, project_id: str, name: str, root: Path) -> Optional[Dict[str, Any]]:
    """The document's study card, from R2 beside the extraction output, else from data/study_cards."""
    try:
        return json.loads(s3.get_object(Bucket=bucket, Key=f"rags/{project_id}/study_cards/{name}.json")["Body"].read())
    except Exception:
        pass
    local = root / "data" / "study_cards" / f"{name}.json"
    if local.exists():
        try:
            return json.loads(local.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _finite(x: Any) -> Optional[float]:
    return x if isinstance(x, (int, float)) and math.isfinite(x) else None


def _clean(v: Any) -> Any:
    return v.replace("\x00", "") if isinstance(v, str) else v


def _int32(v: Any) -> Optional[int]:
    """An integer that fits a Postgres integer column, or None. Guards misread sample sizes."""
    n = _finite(v)
    return int(n) if n is not None and abs(n) < 2**31 and n == int(n) else None


def estimate_text(r: Dict[str, Any]) -> str:
    """The text embedded for an estimate: outcome, arm and subgroup."""
    parts = [r["outcome_name"]]
    if r.get("treatment_arm"):
        parts.append(f"arm: {r['treatment_arm']}")
    if r.get("subgroup"):
        parts.append(f"subgroup: {r['subgroup']}")
    return " | ".join(parts)


def rows_for(project_id: str, doc: Dict[str, Any], out: Dict[str, Any], model: str) -> List[Dict[str, Any]]:
    """Grounded estimates with a number, in the effect_estimates shape (without embeddings)."""
    rows = []
    for e in out["estimates"]:
        if not e["grounded"] or _finite(e["effect_size"]) is None:
            continue
        ci = f"[{e['ci_low']}, {e['ci_high']}]" if e["ci_low"] is not None else None
        p = _finite(e["p_value"])
        n = _finite(e["sample_size"])
        row = {
            "rag_project_id": project_id, "document_id": doc["id"], "doc_key": doc["filename"], "source": SOURCE,
            "table_number": e["table_label"][:120], "outcome_name": (e["outcome"] or e["row_label"] or "?")[:500],
            "treatment_arm": e["arm"] or None, "subgroup": e["subgroup"] or None,
            "estimation_method": e.get("estimation_method") or None,
            "time_point": e.get("time_point") or None,
            "population": e.get("population") or None,
            "effect_type": e.get("effect_type") or "main",
            "specification": e.get("specification") or None,
            "estimand": e.get("estimand") or None,
            "quantile": e.get("quantile") or None,
            "row_role": e.get("row_role") or None,
            "column_role": e.get("column_role") or None,
            "keep_effect": e.get("keep_effect", True),
            "effect_size": e["effect_size"], "standard_error": _finite(e["standard_error"]),
            "p_value": p if p is not None and 0 <= p <= 1 else None,
            "p_text": ("*" * e["stars"]) if e["stars"] else None, "ci_text": ci,
            "t_stat": _finite(e.get("t_stat")), "ci_low": _finite(e.get("ci_low")),
            "ci_high": _finite(e.get("ci_high")), "se_kind": e.get("se_kind") or None,
            "sample_size": _int32(n),
            "control_mean": e.get("control_mean"), "control_sd": e.get("control_sd"),
            "n_treatment": _int32(e.get("n_treatment")), "n_control": _int32(e.get("n_control")),
            "literal_text": (e["estimate_cell"] + (" " + e["se_cell"] if e["se_cell"] else ""))[:500],
            "text_position": f"{e['table_label']}, row '{e['row_label']}', column '{e['column_label']}'"[:500],
            "page": e["page"], "table_index": e.get("table_index"), "source_cell": e.get("source_cell") or None,
            "cell_row": e.get("cell_row"), "cell_column": e.get("cell_column"),
            "unit_index": e.get("unit_index"), "se_row": e.get("se_row"), "se_column": e.get("se_column"),
            "extraction_method": model,
        }
        # The numbers must agree with each other. A field that fails its check is dropped and the reason kept,
        # because a missing value is recoverable and a wrong one silently biases a pooled estimate.
        flags = flags_for(row) + [note for note in (e.get("notes") or []) if note]
        if "p-value inconsistent" in " ".join(flags):
            row["p_value"] = None
        if "interval not centred" in " ".join(flags) or "multiplier" in " ".join(flags):
            row["ci_low"] = row["ci_high"] = row["ci_text"] = None
        if "sample size is smaller" in " ".join(flags):
            row["n_treatment"] = row["n_control"] = None
        row["quality_flags"] = "; ".join(flags) or None
        # Standardised fields are written with the row, from the inputs it actually carries, and stay
        # null when control_sd or a per-arm count is missing rather than being guessed.
        standard = standardise(row)
        row.update({"effect_size_d": standard["d"] if standard else None,
                    "var_d": standard["var_d"] if standard else None,
                    "hedges_g": standard["yi"] if standard else None,
                    "var_g": standard["vi"] if standard else None,
                    "se_g": standard["se_g"] if standard else None})
        rows.append(row)
    return [{k: _clean(v) for k, v in r.items()} for r in rows]


def _r2():
    import boto3

    return boto3.client("s3", endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
                        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")


def _pdf_bytes(s3, bucket: str, project_id: str, doc: Dict[str, Any]) -> bytes:
    """The uploaded PDF, for the image-table fallback. Empty when the key is not found."""
    for key in (f"rags/{project_id}/input-pdfs/{doc['id']}.pdf",
                f"rags/{project_id}/input-pdfs/{doc['filename']}.pdf",
                f"rags/{project_id}/inputs/{doc['id']}.pdf"):
        try:
            return s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        except Exception:
            continue
    return b""


def unify_keys(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Give every row the stable identity and the same key set, filling absent fields with None.

    PostgREST rejects a batch whose objects differ in shape ("All object keys must match"), and the rows
    for one document come from three builders: the table reader, the vision reader and the prose reader.
    The identity is set here, for all three, so the database has one key per estimate whichever reader
    found it.
    """
    for row in rows:
        if not row.get("row_key"):
            row["row_key"] = row_key(row.get("source") or SOURCE, row.get("page"), row.get("outcome_name"),
                                     row.get("treatment_arm"), row.get("subgroup"), row.get("effect_size"),
                                     table_index=row.get("table_index"), cell_row=row.get("cell_row"),
                                     cell_column=row.get("cell_column"), effect_type=row.get("effect_type"),
                                     time_point=row.get("time_point"), specification=row.get("specification"),
                                     estimand=row.get("estimand"), quantile=row.get("quantile"))
    # The identity is unique in the table, so a run that returns the same estimate twice keeps one: a
    # repeated key would otherwise make the whole document's insert fail.
    unique, seen = [], set()
    for row in rows:
        if row["row_key"] in seen:
            continue
        seen.add(row["row_key"])
        unique.append(row)
    keys = set().union(*(row.keys() for row in unique)) if unique else set()
    for row in unique:
        # The vision and prose readers do not label roles, so their rows arrive without the flag. It
        # fails open: an unlabelled row is kept. A None here would break the not-null column and lose
        # the whole document's insert.
        if row.get("keep_effect") is None:
            row["keep_effect"] = True
    return [{key: row.get(key) for key in keys} for row in unique]


async def _post(db: httpx.AsyncClient, rows: List[Dict[str, Any]]) -> Optional[str]:
    """Insert with retries. Returns an error message, or None.

    Transport failures here are not always `httpx.TransportError`: a bad TLS record surfaces as
    `ssl.SSLError`, which once aborted a whole re-extraction. Catch any exception and retry.
    """
    last = ""
    for attempt in range(5):
        try:
            r = await db.post("/effect_estimates", json=rows, headers={"Prefer": "return=minimal"})
            if r.status_code < 400:
                return None
            last = f"insert {r.status_code}: {r.text[:300]}"
            if r.status_code < 500:
                return last
        except Exception as e:
            last = f"{type(e).__name__}: {e}"[:200]
        await asyncio.sleep(5 * (attempt + 1))
    return last


async def _upsert(db: httpx.AsyncClient, rows: List[Dict[str, Any]]) -> Optional[str]:
    """Upsert on the natural row key, with retries. Returns an error message, or None.

    New rows go into place before old rows are removed, so a document is never left empty: a row whose
    row_key is unchanged is updated, a new row is inserted, and only afterwards are the old rows the run did
    not reproduce deleted by id.
    """
    last = ""
    for attempt in range(5):
        try:
            r = await db.post("/effect_estimates", json=rows,
                              params={"on_conflict": "rag_project_id,doc_key,row_key"},
                              headers={"Prefer": "resolution=merge-duplicates,return=minimal"})
            if r.status_code < 400:
                return None
            last = f"upsert {r.status_code}: {r.text[:300]}"
            if r.status_code < 500:
                return last
        except Exception as e:
            last = f"{type(e).__name__}: {e}"[:200]
        await asyncio.sleep(5 * (attempt + 1))
    return last


def should_skip_replace(rows: List[Dict[str, Any]]) -> bool:
    """A run that stores nothing must not empty a document: the stored rows are kept."""
    return not rows


def stale_row_ids(previous: List[Dict[str, Any]], new_row_keys: set) -> List[str]:
    """The ids of stored rows the new run did not reproduce. These are deleted after the insert."""
    return [row["id"] for row in previous if row.get("row_key") not in new_row_keys]


def shrink_flag(new_count: int, stored_count: int, floor: float = 0.7) -> bool:
    """True when a run stores many fewer rows than before, so the document needs review.

    Replacement used to carry forward every stored value the new run did not reproduce. That kept a
    sign-lost +0.005 beside the corrected -0.005, and kept covariate rows after the reader learned to skip
    them, for ever. With prune on, the stored rows are exactly what the current reader produces; a run that
    loses a large share of a document is flagged for a person to look at, not silently patched.
    """
    return stored_count > 0 and new_count < floor * stored_count


async def _stored_rows(db: httpx.AsyncClient, project_id: str, name: str) -> List[Dict[str, Any]]:
    """The document's stored rows, paged, so a replacement can keep the values it did not reproduce."""
    rows, offset = [], 0
    while True:
        r = await db.get("/effect_estimates", params={
            "select": "*", "rag_project_id": f"eq.{project_id}", "doc_key": f"eq.{name}",
            "source": f"eq.{SOURCE}", "limit": "1000", "offset": str(offset), "order": "id"})
        if r.status_code >= 400:
            return rows
        batch = r.json() or []
        rows.extend(batch)
        if len(batch) < 1000:
            return rows
        offset += 1000


async def extract_and_store(
    project_id: str,
    doc_keys: Optional[Iterable[str]] = None,
    model: str = DEFAULT_MODEL,
    skip_done: bool = False,
    vision: Optional[bool] = None,
    prune: bool = False,
    cost_cap_usd: Optional[float] = None,
    log: Callable[[str], None] = print,
) -> Dict[str, int]:
    """
    Extract, embed and store estimates for a project's completed documents (all of them,
    or only `doc_keys`).

    Each run replaces the document's rows with exactly what the reader produced. A run that stores many
    fewer rows than the document held before is flagged in the log for review, rather than keeping the old
    rows. A failed insert is still restored, so a document is never left with nothing.
    """
    from src.retrieval.study_cards import embed_documents

    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1"
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    bucket, s3 = os.environ.get("R2_BUCKET_NAME", "devchat-pdfs"), _r2()
    wanted = set(doc_keys) if doc_keys is not None else None
    totals = {"docs": 0, "estimates": 0, "kept": 0, "results_tables": 0, "tables": 0, "errors": 0, "second_pass_units": 0, "second_pass_rows": 0, "reduced": 0, "restored": 0,
              "vision_pages": 0, "vision_rows": 0, "outcome_misses": 0, "prose_rows": 0, "role_disagreements": 0, "cost_usd": 0.0}

    async with httpx.AsyncClient(base_url=url, headers=headers, timeout=120) as db:
        docs = (await db.get("/documents", params={
            "select": "id,filename", "rag_project_id": f"eq.{project_id}", "status": "eq.completed"})).json()
        if wanted is not None:
            docs = [d for d in docs if d["filename"] in wanted]
        if skip_done:
            have = (await db.get("/effect_estimates", params={
                "select": "doc_key", "rag_project_id": f"eq.{project_id}", "source": f"eq.{SOURCE}",
                "limit": "100000"})).json()
            done = {h["doc_key"] for h in have}
            docs = [d for d in docs if d["filename"] not in done]
        log(f"Estimates: {len(docs)} documents to extract")
        sem = asyncio.Semaphore(DOC_CONCURRENCY)

        async def one(doc: Dict[str, Any]) -> None:
            async with sem:
                t0 = time.time()
                name = doc["filename"]
                if cost_cap_usd is not None and totals["cost_usd"] >= cost_cap_usd:
                    log(f"    skip {name[:50]}: cost cap ${cost_cap_usd:.2f} reached (spent ${totals['cost_usd']:.4f})")
                    return
                try:
                    obj = await asyncio.to_thread(
                        s3.get_object, Bucket=bucket, Key=f"rags/{project_id}/outputs/json/{name}.json")
                    content = json.loads(obj["Body"].read()).get("content_list") or []
                    content = normalise_tables(content)
                    content = reclassify_pipe_tables(content)
                    state = {"pdf": None, "loaded": False}

                    async def load_pdf() -> bytes:
                        if not state["loaded"]:
                            state["pdf"] = await asyncio.to_thread(_pdf_bytes, s3, bucket, project_id, doc)
                            state["loaded"] = True
                        return state["pdf"]

                    async def page_image(page: int):
                        from src.extraction.page_vision import page_data_url

                        pdf = await load_pdf()
                        return await asyncio.to_thread(page_data_url, pdf, page) if pdf else None

                    context_mode = os.environ.get("READER_CONTEXT", "full")
                    # full = card + gallery; gallery = reader D (gallery only, no card); off = neither.
                    card = _load_card(s3, bucket, project_id, name, ROOT) if context_mode in ("full", "card") else None
                    gallery = GALLERY if context_mode in ("full", "gallery") else None
                    out = await extract_document(content, model, os.environ["OPENROUTER_API_KEY"],
                                                 page_image=page_image, read_roles=True,
                                                 card=card, gallery_entries=gallery)
                    totals["cost_usd"] = max(totals["cost_usd"], float(out.get("cost_usd") or 0.0))
                    role_notes = out.get("role_disagreements") or []
                    if role_notes:
                        totals["role_disagreements"] += len(role_notes)
                        for note in role_notes[:3]:
                            log(f"    role disagreement: {note}")
                    rows = rows_for(project_id, doc, out, model)
                    risky = False
                    if vision is not False:
                        # vision None is the automatic decision: image pages when some table text is
                        # garbled or the parser found no table at all. True forces it, False disables.
                        from src.extraction.page_vision import (
                            auto_vision_pages,
                            extract_pages,
                            label_vision_roles,
                            page_count,
                            vision_pages,
                        )

                        pdf = await load_pdf()
                        pdf_pages = page_count(pdf) if pdf else None
                        pages = vision_pages(content, pdf_pages) if vision else auto_vision_pages(content, pdf_pages)
                        if pdf and pages:
                            vclient = httpx.AsyncClient(
                                base_url="https://openrouter.ai/api/v1",
                                headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
                                timeout=300)
                            try:
                                vout = await extract_pages(
                                    pdf, pages, model, os.environ["OPENROUTER_API_KEY"],
                                    project_id, doc, client=vclient)
                                # The page-read rows carry no roles from the text path, so label them from
                                # the same page image, or the flag would be blind on odd-PDF documents.
                                if vout["rows"]:
                                    await label_vision_roles(vout["rows"], vout.get("images") or {}, model,
                                                             os.environ["OPENROUTER_API_KEY"], client=vclient)
                                rows.extend(vout["rows"])
                                totals["vision_pages"] += len(vout["pages"])
                                totals["vision_rows"] += len(vout["rows"])
                                risky = True
                            finally:
                                await vclient.aclose()
                    has_tables = any(item.get("type") == "table" for item in content)
                    repaired = any(item.get("repaired") for item in content)
                    if not has_tables and not repaired:
                        # No table text at all: results, if any, are in sentences. Read the prose once.
                        # A document whose only tables were repaired is left to the vision pass, which
                        # reads those pages, so the prose reader is not run over the transcriptions too.
                        try:
                            from src.extraction.prose_estimates import build_rows as prose_rows
                            from src.extraction.prose_estimates import extract_prose
                            from src.extraction.provenance import looks_like_review

                            title = next((str(item.get("text") or "") for item in content
                                          if item.get("type") == "title"), "")
                            doc_text = " ".join(str(item.get("text") or "") for item in content
                                                if item.get("type") in ("text", "title"))
                            if doc_text.strip() and not looks_like_review(doc_text, title):
                                async with httpx.AsyncClient(
                                        base_url="https://openrouter.ai/api/v1",
                                        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
                                        timeout=180) as pclient:
                                    prose_data = await extract_prose(
                                        doc_text, model, os.environ["OPENROUTER_API_KEY"], client=pclient)
                                prose = prose_rows(project_id, doc, content, doc_text, prose_data, model)
                                rows.extend(prose)
                                totals["prose_rows"] += len(prose)
                                risky = True
                        except Exception as e:
                            log(f"  ! {name[:60]}: prose extraction failed: {type(e).__name__}")
                    if risky or any(item.get("type") == "table" for item in content):
                        # Confirm the outcomes the paper says it reports are in the rows. Cheap, and it
                        # catches a headline result that sat in a figure, a sentence or a skipped table.
                        # A missing outcome then drives the bounded second pass below.
                        try:
                            from src.extraction.outcome_confirmation import (
                                confirm_outcomes,
                                missing_outcomes,
                            )

                            text = " ".join(str(item.get("text") or "") for item in content
                                            if item.get("type") in ("text", "title"))
                            async with httpx.AsyncClient(
                                    base_url="https://openrouter.ai/api/v1",
                                    headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
                                    timeout=180) as cclient:
                                confirmation = await confirm_outcomes(
                                    text, model, os.environ["OPENROUTER_API_KEY"], client=cclient)
                            misses = missing_outcomes(
                                confirmation, [str(r.get("outcome_name") or "") for r in rows])
                            totals["outcome_misses"] += len(misses)
                            if misses:
                                log(f"  ! {name[:60]}: not extracted: "
                                    + ", ".join(m["name"] for m in misses[:4]))
                                # Second pass, bounded to the units that mention a missing outcome.
                                try:
                                    from src.extraction.second_pass import merge_rows, run_second_pass

                                    second = await run_second_pass(
                                        content, [m["name"] for m in misses], model,
                                        os.environ["OPENROUTER_API_KEY"], project_id=project_id, doc=doc)
                                    extra = rows_for(project_id, doc, {"estimates": second["estimates"],
                                                                       "tables": []}, model)
                                    rows, added = merge_rows(rows, extra)
                                    if second.get("rows"):
                                        rows, more = merge_rows(rows, second["rows"])
                                        added += more
                                    totals["second_pass_units"] += second.get("units", 0)
                                    totals["second_pass_rows"] += added
                                    log(f"    second pass: {second.get('units', 0)} unit(s), +{added} row(s)")
                                except Exception as e:
                                    log(f"  ! {name[:60]}: second pass failed: {type(e).__name__}")
                        except Exception as e:
                            log(f"  ! {name[:60]}: outcome confirmation failed: {type(e).__name__}")
                    rows = dedupe_rows(rows)
                    if rows:
                        vectors = await asyncio.to_thread(embed_documents, [estimate_text(r) for r in rows])
                        for r, v in zip(rows, vectors):
                            r["embedding"] = [float(x) for x in v]
                except Exception as e:
                    totals["errors"] += 1
                    log(f"  ✗ {name[:60]}: {type(e).__name__}: {str(e)[:120]}")
                    return
                try:
                    previous = await _stored_rows(db, project_id, name)
                    # No carry-forward: the stored rows must be exactly what the reader produced.
                    if shrink_flag(len(rows), len(previous)):
                        totals["reduced"] += 1
                        log(f"    ! {name[:50]}: new run stores {len(rows)} rows against "
                            f"{len(previous)} before; review")
                    rows = unify_keys(rows)
                    # A gateway timeout on one document used to lose the whole document's write and need a
                    # manual re-run. Retry the write as a unit, with a pause, before giving up on it.
                    # Insert (upsert) the new rows first, so the document is never left empty, then remove
                    # only the old rows this run did not reproduce, by id. A run that stores nothing keeps the
                    # stored rows, so a reader failure cannot empty a document.
                    if should_skip_replace(rows):
                        totals["reduced"] += 1
                        log(f"    ! {name[:50]}: new run stores 0 rows; keeping the stored rows for review")
                        return
                    new_keys = {row["row_key"] for row in rows}
                    stale_ids = stale_row_ids(previous, new_keys)
                    for attempt in range(2):
                        try:
                            for i in range(0, len(rows), INSERT_BATCH):
                                err = await _upsert(db, rows[i:i + INSERT_BATCH])
                                if err:
                                    raise RuntimeError(err)
                            for i in range(0, len(stale_ids), 100):
                                batch = stale_ids[i:i + 100]
                                r = await db.delete("/effect_estimates", params={
                                    "rag_project_id": f"eq.{project_id}",
                                    "id": f"in.({','.join(batch)})"})
                                if r.status_code >= 400:
                                    raise RuntimeError(f"delete {r.status_code}: {r.text[:200]}")
                            break
                        except Exception:
                            if attempt == 1:
                                raise
                            log(f"    retrying the write for {name[:50]} after a pause")
                            await asyncio.sleep(30)
                except Exception as e:
                    totals["errors"] += 1
                    log(f"  ✗ {name[:60]}: {type(e).__name__}: {str(e)[:120]}")
                    if prune and previous:
                        # Insert-first means the document is not empty; this restores any old row a partial
                        # delete removed, and never conflicts with a row the new run already upserted.
                        restored = unify_keys([{k: v for k, v in row.items() if k not in ("id", "created_at")}
                                               for row in previous])
                        for i in range(0, len(restored), INSERT_BATCH):
                            if await _upsert(db, restored[i:i + INSERT_BATCH]) is None:
                                totals["restored"] += len(restored[i:i + INSERT_BATCH])
                        log(f"    restored {totals.get('restored', 0)} row(s) after the failed write")
                    return
                results = sum(t["results_table"] for t in out["tables"])
                totals["docs"] += 1
                totals["estimates"] += len(out["estimates"])
                totals["kept"] += len(rows)
                totals["tables"] += len(out["tables"])
                totals["results_tables"] += results
                log(f"  {name[:60]:60} tables {len(out['tables']):3} results {results:3} "
                    f"kept {len(rows):4} ({time.time() - t0:.0f}s)")

        await asyncio.gather(*(one(d) for d in docs), return_exceptions=True)
    return totals
