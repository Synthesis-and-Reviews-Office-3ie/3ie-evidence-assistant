"""
Extract effect estimates a paper states in prose.

Some documents report results only in sentences and figures: paper 121058361 is a SPIR learning brief
with 24 figures and no tables ("poultry ownership rose by 4 percentage points"). The table reader and
the page-image reader cannot see a number that exists only in a sentence.

This module reads the text once and extracts estimates that are stated in words, with a strict
grounding rule: the quoted sentence must appear in the paper text, or the row is dropped. Prose
numbers often lack a standard error, so the unit is kept in `literal_text` and the row is marked with
`extraction_method` ending in "prose" so the rest of the system can treat it differently.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence

from src.extraction.table_estimates import parse_number

PROSE_PROMPT = """You are given the text of one research paper. Extract the effect estimates the paper
reports in prose, in sentences rather than tables.

For each, return the outcome, the treatment arm or group, the exact sentence that states the result,
the effect as printed (a number and its unit kept separately), and any standard error, confidence
interval, p-value or sample size that the sentence states.

Only this study's own results. Ignore results it reports from other studies ("Banerjee et al. found",
"earlier evaluations show"). Only report numbers printed in the text; never compute or estimate.

Return JSON only:
{"estimates": [{
  "outcome": "<what is measured>",
  "arm": "<treatment group, or empty>",
  "subgroup": "<subgroup, or empty>",
  "quote": "<the exact sentence from the text>",
  "effect": <number>,
  "effect_unit": "<percent | percentage points | SD | currency | count | other>",
  "standard_error": <number or null>,
  "ci_low": <number or null>,
  "ci_high": <number or null>,
  "p_value": <number or null>,
  "sample_size": <number or null>
}]}"""


def _flat(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _norm(text: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _flat(text).lower()).strip()


def quote_in_text(quote: str, text: str) -> bool:
    """True when the quoted sentence is (nearly) present in the text."""
    needle = _norm(quote)
    if len(needle) < 20:
        return False
    return needle in _norm(text)


def page_for_quote(quote: str, content_list: Sequence[Dict[str, Any]]) -> Optional[int]:
    """The page of the text item that contains the quote, so a prose row can still be located."""
    needle = _norm(quote)
    if len(needle) < 20:
        return None
    for item in content_list:
        if item.get("type") not in ("text", "title"):
            continue
        if needle in _norm(item.get("text")):
            try:
                return int(item.get("page_idx")) + 1
            except (TypeError, ValueError):
                return None
    return None


_EFFECT_CUES = re.compile(
    r"increas|decreas|reduc|rais|higher|lower|more than|less than|relative to|compared (to|with)|"
    r"impact|effect of|difference (between|in)|treatment effect|percentage points?|p\s*[<=]\s*0?\.0?[15]",
    re.I)
_SHARE_LEVEL = re.compile(r"\b\d+(?:\.\d+)?\s*%\s+of\b", re.I)
_CHANGE_BEFORE = re.compile(r"increas|decreas|reduc|rises?|falls?|raises?|lowers?", re.I)


def states_an_effect(sentence: object) -> bool:
    """True when a sentence reports a difference rather than a level.

    "The probability of owning poultry increases by about 40 percentage points" is an effect; "88% of
    respondents use a VESA" is a level. A cue word alone is not enough, because a level sentence can say
    "compared to" or "more than": a share written as "N% of households" is rejected unless a change word
    stands immediately before it.
    """
    text = str(sentence or "")
    if not _EFFECT_CUES.search(text):
        return False
    for match in _SHARE_LEVEL.finditer(text):
        before = text[max(0, match.start() - 45):match.start()].lower()
        if not _CHANGE_BEFORE.search(before):
            return False
    return True


def build_rows(project_id: str, doc: Dict[str, Any], content_list: Sequence[Dict[str, Any]],
               text: str, data: Dict[str, Any], model: str) -> List[Dict[str, Any]]:
    """Rows in the `effect_estimates` shape, keeping only quotes that appear in the paper text."""
    if not isinstance(data, dict):
        return []
    rows = []
    for raw in data.get("estimates") or []:
        if not isinstance(raw, dict):
            continue
        value = parse_number(raw.get("effect"))
        quote = _flat(raw.get("quote"))
        if value is None or not quote_in_text(quote, text):
            continue
        if not states_an_effect(quote):
            # A sentence that reports a level ("88% of respondents use a VESA") is not a treatment effect,
            # and paper 121058361 lost half its rows to that shape before this rule.
            continue
        se = parse_number(raw.get("standard_error"))
        p = raw.get("p_value") if isinstance(raw.get("p_value"), (int, float)) else None
        n = parse_number(raw.get("sample_size"))
        rows.append({
            "rag_project_id": project_id, "document_id": doc["id"], "doc_key": doc["filename"],
            "source": "tables_v1",
            "table_number": "prose"[:120],
            "outcome_name": str(raw.get("outcome") or "?")[:500],
            "treatment_arm": (str(raw.get("arm"))[:200] if raw.get("arm") else None),
            "subgroup": (str(raw.get("subgroup"))[:200] if raw.get("subgroup") else None),
            "effect_size": value,
            "standard_error": se,
            "p_value": p if p is not None and 0 <= p <= 1 else None,
            "p_text": None,
            "ci_text": (f"[{raw.get('ci_low')}, {raw.get('ci_high')}]"
                        if raw.get("ci_low") is not None and raw.get("ci_high") is not None else None),
            "sample_size": int(n) if n is not None and abs(n) < 2 ** 31 and n == int(n) else None,
            "literal_text": (quote + f" ({raw.get('effect_unit')})")[:500],
            "text_position": "prose read",
            "page": page_for_quote(quote, content_list), "extraction_method": f"{model} prose",
        })
    return rows


async def extract_prose(text: str, model: str, api_key: str, client=None) -> Dict[str, Any]:
    """One model call: estimates the paper states in prose."""
    import httpx

    own = client is None
    client = client or httpx.AsyncClient(timeout=180, headers={"Authorization": f"Bearer {api_key}"})
    try:
        response = await client.post("/chat/completions", json={
            "model": model,
            "messages": [{"role": "user", "content": PROSE_PROMPT + "\n\nTEXT:\n" + str(text)[:24000]}],
            "response_format": {"type": "json_object"},
        })
        content = str(response.json()["choices"][0]["message"]["content"])
        match = re.search(r"\{.*\}", content, re.S)
        return json.loads(match.group(0)) if match else {}
    finally:
        if own:
            await client.aclose()
