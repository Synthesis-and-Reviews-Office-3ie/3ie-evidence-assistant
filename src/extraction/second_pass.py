"""A second, bounded read of the outcomes the first pass did not store.

The first pass reads every table once. It can still miss a value: a wide table where a column was not
followed, a value printed in a sentence rather than in a cell, or a table the classifier skipped. The
outcome confirmation already says which outcomes the paper leads with and which of them no stored row
carries, so the units that mention those outcomes are re-read with the missing names in the prompt and
nothing else is.

Why bounded: re-reading the whole document costs the same as the first pass, on every document that has
a missing outcome, which is most of them. Only the units that mention a missing name are read, and
`max_units` caps them.

Provenance: the shape is the one used by the error-repair runs, where the missing values are known before
the second read; the difference here is that the list comes from the paper's own outcome confirmation
rather than from a hand-typed key, so it works in production.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
from typing import Any

STOP = {"the", "and", "for", "per", "of", "in", "on", "a", "an", "to", "at", "by", "total", "value",
        "number", "average", "mean", "monthly", "annual", "rate", "index", "change"}
MAX_UNITS = 8
MAX_SNIPPET = 4000


def _words(text: object) -> set:
    return {word for word in "".join(c if c.isalnum() else " " for c in str(text or "").lower()).split()
            if word and word not in STOP and len(word) > 2}


def mentions(text: object, names: Sequence[str], share: float = 0.5) -> list[str]:
    """The missing outcome names that `text` is about.

    A paper names the same outcome differently in a table and in its prose, so the rule is that half the
    name's words are present and the longest of them is among them. "Household expenditure" is found by
    a table row labelled "Expenditure" and not by one about "Household size".
    """
    haystack = _words(text)
    if not haystack:
        return []
    hits = []
    for name in names:
        wanted = _words(name)
        if not wanted:
            continue
        longest = max(wanted, key=len)
        if longest in haystack and len(wanted & haystack) / len(wanted) >= share:
            hits.append(name)
    return hits


def select_units(content_list: Sequence[dict[str, Any]], names: Sequence[str],
                 max_units: int = MAX_UNITS) -> dict[str, list[dict[str, Any]]]:
    """The tables and text spans that mention a missing outcome, most mentions first.

    A table is read as a whole again (the same call the first pass makes) and only when its text or
    caption mentions a missing name. A text item is read with the prose reader on its own text, which is
    how a value printed in a sentence is reached; the first pass only reads prose when a document has no
    tables at all.
    """
    from src.extraction.table_estimates import table_units

    tables = []
    for unit in table_units(list(content_list)):
        hits = mentions(f"{unit.get('caption') or ''} {unit.get('text') or ''}", names)
        if hits:
            tables.append({**unit, "hits": hits})
    texts = []
    for index, item in enumerate(content_list):
        if item.get("type") not in ("text", "title"):
            continue
        body = str(item.get("text") or "")
        # A sentence and a table name an outcome differently, so a span is selected on the outcome's
        # distinctive word alone: the confirmation calls it "Consumption (per capita) treatment effect
        # at years seven and ten" and the sentence says "consumption".
        hits = mentions(body, names, share=0.0)
        if hits:
            texts.append({"index": index, "page": (item.get("page_idx") or 0) + 1,
                          "text": body[:MAX_SNIPPET], "hits": hits})
    tables.sort(key=lambda u: -len(u["hits"]))
    texts.sort(key=lambda u: -len(u["hits"]))
    # The cap is per kind. A single shared budget was tried first, and a document whose missing
    # outcome appears in eight tables spent it all on tables, leaving one sentence read and the value
    # printed in a sentence unreached.
    return {"tables": tables[:max_units], "texts": texts[:max_units]}


def _finalise(estimates: list[Any], content_list: Sequence[dict[str, Any]]) -> list[Any]:
    """Check each second-pass error against the printed cell, as the first pass does.

    The second pass builds estimates from the same table units, so the same rule applies: an error is
    kept only when the addressed cell, the cell below it, or the cell to its right prints it. Without
    this step a second-pass error reaches the store on the model's word alone.
    """
    from src.extraction.table_estimates import finalise_addresses, table_units

    finalise_addresses(estimates, table_units(list(content_list)))
    return estimates


async def run_second_pass(content_list: Sequence[dict[str, Any]], names: Sequence[str], model: str,
                          api_key: str, project_id: str = "", doc: dict[str, Any] | None = None,
                          max_units: int = MAX_UNITS) -> dict[str, Any]:
    """Re-read the units that mention a missing outcome and return what they yield.

    `estimates` are in the first pass's table shape, so the caller builds database rows from them the
    same way. `rows` are database rows already, because the prose reader produces them directly. One
    unit that fails does not stop the others, and a unit the model still does not read adds nothing, so
    this is additive: the caller merges what it returns with the rows it already has.
    """
    import httpx

    from src.extraction.table_estimates import (
        PROMPT,
        _chat,
        _drop_non_outcome_rows,
        _parse_json,
        _structure_hint,
        _table_analysis,
        locate_by_value,
        locate_cell_position,
        to_estimate,
    )

    selected = select_units(content_list, names, max_units)
    estimates: list[Any] = []
    prose: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    if not selected["tables"] and not selected["texts"]:
        return {"estimates": [], "rows": [], "tables": [], "units": 0}
    hint = ("The paper reports these outcomes and no stored row carries them: "
            + "; ".join(names[:8]) + ". Find their estimates in this unit.")
    async with httpx.AsyncClient(timeout=300, headers={"Authorization": f"Bearer {api_key}"}) as client:
        for unit in selected["tables"]:
            kind, result, _ = _table_analysis(unit)
            prompt = PROMPT.format(context=(unit["caption"] + "\n" + unit["context"]).strip()[:4000] or "(none)",
                                   table=unit["text"], page=unit["page"] if unit["page"] is not None else "?",
                                   structure=_structure_hint(result) or "(none)",
                                   view="the whole table. " + hint)
            label = str(unit.get("caption") or "")[:40] or f"table at item {unit['index']}"
            try:
                data = _parse_json(await _chat(client, model, prompt))
            except Exception as exc:  # a failed unit must not stop the rest
                tables.append({"table": label, "page": unit["page"], "error": f"{type(exc).__name__}"})
                continue
            raw = (data.get("estimates") or []) if data.get("results_table") else []
            raw, _ = _drop_non_outcome_rows(raw)
            rows = [to_estimate(r, label, unit["page"], unit["text"], unit.get("arm_hint") or "",
                                unit_index=unit.get("unit_index"))
                    for r in raw if isinstance(r, dict)]
            # The model's own row and column are optional, so the same two fallbacks the first pass uses
            # are applied here; without them the row has a unit but still no cell.
            for estimate in rows:
                if estimate.cell_row is None:
                    estimate.cell_row, estimate.cell_column = locate_cell_position(
                        unit["text"], estimate.estimate_cell)
                if estimate.cell_row is None:
                    estimate.cell_row, estimate.cell_column = locate_by_value(
                        unit["text"], estimate.effect_size,
                        estimate.row_label or estimate.outcome, estimate.column_label, estimate.arm)
            estimates += rows
            tables.append({"table": label, "page": unit["page"], "estimates": len(rows), "second_pass": True})
    from src.extraction.prose_estimates import build_rows as prose_rows
    from src.extraction.prose_estimates import extract_prose

    for unit in selected["texts"]:
        try:
            async with httpx.AsyncClient(base_url="https://openrouter.ai/api/v1",
                                         headers={"Authorization": f"Bearer {api_key}"},
                                         timeout=180) as client:
                data = await extract_prose(f"{hint}\n\n{unit['text']}", model, api_key, client=client)
        except Exception as exc:
            tables.append({"table": f"text at item {unit['index']}", "page": unit["page"],
                           "error": f"{type(exc).__name__}"})
            continue
        data = dict(data or {})
        # The prose reader grounds each quote against the text it was given, which here is the span
        # that mentions the outcome, and pages the row from the content list it is handed.
        span = [{"type": "text", "page_idx": unit["page"] - 1, "text": unit["text"]}]
        try:
            rows = prose_rows(project_id, doc or {"id": None, "filename": ""}, span, unit["text"], data, model)
        except Exception:
            rows = []
        prose.extend(rows)
        tables.append({"table": f"text at item {unit['index']}", "page": unit["page"],
                       "prose_rows": len(rows), "second_pass": True})
    _finalise(estimates, content_list)
    return {"estimates": [asdict(e) for e in estimates], "rows": prose, "tables": tables,
            "units": len(selected["tables"]) + len(selected["texts"])}


def merge_rows(rows: list[dict[str, Any]], extra: list[dict[str, Any]]) -> tuple:
    """Add `extra` to `rows`, dropping a row that repeats an outcome, arm and estimate.

    The second pass overlaps the first, so an exact repeat is expected. A repeat is dropped, and a gap
    in the kept row is filled from the copy that has it, which is the rule `dedupe_estimates` applies to
    the first pass's own rows.
    """
    def key(row: dict[str, Any]) -> tuple:
        return (str(row.get("outcome_name") or "").lower().strip(),
                str(row.get("treatment_arm") or "").lower().strip(),
                row.get("effect_size"))

    seen: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        seen.setdefault(key(row), row)
    added = 0
    for row in extra:
        current = seen.get(key(row))
        if current is None:
            seen[key(row)] = row
            rows.append(row)
            added += 1
            continue
        for field in ("standard_error", "p_value", "ci_text", "sample_size", "literal_text", "text_position"):
            if current.get(field) in (None, "") and row.get(field) not in (None, ""):
                current[field] = row[field]
        # The address travels as one piece with the unit it belongs to, never a cell from another view.
        if current.get("unit_index") is None and row.get("unit_index") is not None:
            for field in ("unit_index", "cell_row", "cell_column", "se_row", "se_column", "source_cell"):
                if row.get(field) is not None:
                    current[field] = row[field]
    return rows, added
