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
from typing import Any, Callable, Dict, Iterable, List, Optional

import httpx

from src.extraction.effect_sizes import standardise
from src.extraction.identity import row_key
from src.extraction.table_estimates import extract_document
from src.extraction.table_rules import reclassify_pipe_tables

SOURCE = "tables_v1"
DEFAULT_MODEL = "anthropic/claude-haiku-5.5"
DOC_CONCURRENCY = int(os.environ.get("DOC_CONCURRENCY") or 2)
INSERT_BATCH = 50  # rows carry 1536-d vectors, and the small Supabase instance drops large writes


def _finite(x: Any) -> Optional[float]:
    return x if isinstance(x, (int, float)) and math.isfinite(x) else None


def _clean(v: Any) -> Any:
    return v.replace("\x00", "") if isinstance(v, str) else v


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
            "effect_size": e["effect_size"], "standard_error": _finite(e["standard_error"]),
            "p_value": p if p is not None and 0 <= p <= 1 else None,
            "p_text": ("*" * e["stars"]) if e["stars"] else None, "ci_text": ci,
            "sample_size": int(n) if n is not None and abs(n) < 2**31 and n == int(n) else None,
            "control_mean": e.get("control_mean"), "control_sd": e.get("control_sd"),
            "n_treatment": e.get("n_treatment"), "n_control": e.get("n_control"),
            "literal_text": (e["estimate_cell"] + (" " + e["se_cell"] if e["se_cell"] else ""))[:500],
            "text_position": f"{e['table_label']}, row '{e['row_label']}', column '{e['column_label']}'"[:500],
            "page": e["page"], "extraction_method": model,
        }
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
                                     row.get("treatment_arm"), row.get("subgroup"), row.get("effect_size"))
    # The identity is unique in the table, so a run that returns the same estimate twice keeps one: a
    # repeated key would otherwise make the whole document's insert fail.
    unique, seen = [], set()
    for row in rows:
        if row["row_key"] in seen:
            continue
        seen.add(row["row_key"])
        unique.append(row)
    keys = set().union(*(row.keys() for row in unique)) if unique else set()
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


def carried_forward(new_rows: List[Dict[str, Any]], stored: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Stored rows whose value the new run did not produce, so replacing the document cannot lose them.

    The identity of an estimate for this purpose is the page and the value, not the label: a run may word
    an outcome differently and still have read the same estimate. Anything stored that is absent by that
    test is kept, which makes a replacement run unable to shrink what was found before.
    """
    by_page: Dict[Any, List[float]] = {}
    for row in new_rows:
        value = row.get("effect_size")
        if value is not None:
            by_page.setdefault(row.get("page"), []).append(float(value))
    keep = []
    for row in stored:
        value = row.get("effect_size")
        if value is None:
            continue
        same = any(abs(float(value) - other) <= max(1e-9, abs(float(value)) * 1e-9)
                   for other in by_page.get(row.get("page"), []))
        if not same:
            keep.append(row)
    return keep


async def _stored_rows(db: httpx.AsyncClient, project_id: str, name: str) -> List[Dict[str, Any]]:
    """The document's stored rows, paged, so a replacement can keep the values it did not reproduce."""
    rows, offset = [], 0
    while True:
        r = await db.get("/effect_estimates", params={
            "select": "*", "rag_project_id": f"eq.{project_id}", "doc_key": f"eq.{name}",
            "source": f"eq.{SOURCE}", "limit": "1000", "offset": str(offset)})
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
    log: Callable[[str], None] = print,
) -> Dict[str, int]:
    """
    Extract, embed and store estimates for a project's completed documents (all of them,
    or only `doc_keys`).

    Each run replaces the document's rows, but a stored row whose page and value the new run did not
    produce is carried forward, so a replacement cannot lose a value the previous run found. `prune=True`
    replaces without carrying forward, for a deliberate clean-up after a change.
    """
    from src.retrieval.study_cards import embed_documents

    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1"
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    bucket, s3 = os.environ.get("R2_BUCKET_NAME", "devchat-pdfs"), _r2()
    wanted = set(doc_keys) if doc_keys is not None else None
    totals = {"docs": 0, "estimates": 0, "kept": 0, "results_tables": 0, "tables": 0, "errors": 0, "second_pass_units": 0, "second_pass_rows": 0, "carried": 0,
              "vision_pages": 0, "vision_rows": 0, "outcome_misses": 0, "prose_rows": 0}

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
                try:
                    obj = await asyncio.to_thread(
                        s3.get_object, Bucket=bucket, Key=f"rags/{project_id}/outputs/json/{name}.json")
                    content = json.loads(obj["Body"].read()).get("content_list") or []
                    content = reclassify_pipe_tables(content)
                    out = await extract_document(content, model, os.environ["OPENROUTER_API_KEY"])
                    rows = rows_for(project_id, doc, out, model)
                    risky = False
                    if vision is not False:
                        # vision None is the automatic decision: image pages when some table text is
                        # garbled or the parser found no table at all. True forces it, False disables.
                        from src.extraction.page_vision import (
                            auto_vision_pages,
                            extract_pages,
                            page_count,
                            vision_pages,
                        )

                        pdf = await asyncio.to_thread(_pdf_bytes, s3, bucket, project_id, doc)
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
                    if rows:
                        vectors = await asyncio.to_thread(embed_documents, [estimate_text(r) for r in rows])
                        for r, v in zip(rows, vectors):
                            r["embedding"] = [float(x) for x in v]
                except Exception as e:
                    totals["errors"] += 1
                    log(f"  ✗ {name[:60]}: {type(e).__name__}: {str(e)[:120]}")
                    return
                try:
                    carried = 0
                    if not prune:
                        previous = await _stored_rows(db, project_id, name)
                        keep = carried_forward(rows, previous)
                        # Server-managed columns are not part of an insert payload.
                        rows.extend({k: v for k, v in row.items() if k not in ("id", "created_at")}
                                    for row in keep)
                        carried = len(keep)
                    rows = unify_keys(rows)
                    # A gateway timeout on one document used to lose the whole document's write and need a
                    # manual re-run. Retry the write as a unit, with a pause, before giving up on it.
                    for attempt in range(2):
                        try:
                            await db.delete("/effect_estimates", params={
                                "rag_project_id": f"eq.{project_id}", "doc_key": f"eq.{name}",
                                "source": f"eq.{SOURCE}"})
                            for i in range(0, len(rows), INSERT_BATCH):
                                err = await _post(db, rows[i:i + INSERT_BATCH])
                                if err:
                                    raise RuntimeError(err)
                            break
                        except Exception:
                            if attempt == 1:
                                raise
                            log(f"    retrying the write for {name[:50]} after a pause")
                            await asyncio.sleep(30)
                    totals["carried"] += carried
                    if carried:
                        log(f"    kept {carried} stored row(s) this run did not reproduce")
                except Exception as e:
                    totals["errors"] += 1
                    log(f"  ✗ {name[:60]}: {type(e).__name__}: {str(e)[:120]}")
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
