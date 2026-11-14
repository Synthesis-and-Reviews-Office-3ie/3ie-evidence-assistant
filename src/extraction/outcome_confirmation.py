"""
Confirm that the outcomes the paper says it reports are actually in the extracted rows.

A table extraction can miss the paper's headline outcome: the result may sit in a figure, in a
footnote, or in a table the reader skipped. Reading the abstract and results text tells us which
outcomes the paper itself calls primary and secondary, and comparing that list with the extracted
outcome names tells us what is missing, without a human key.

`missing_outcomes` is pure and tested. `confirm_outcomes` makes one model call per document.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Sequence

OUTCOME_PROMPT = """You are given the text of one research paper. List the outcomes the paper reports
as its primary result, and up to four that it reports as secondary results. For each, give the
outcome as the paper names it and a short exact quote from the text.

Return JSON only:
{"primary": [{"name": "<outcome>", "quote": "<exact quote>"}],
 "secondary": [{"name": "<outcome>", "quote": "<exact quote>"}]}

Use only the text given. If the paper states no primary outcome, leave the list empty."""

_STOP = {"the", "and", "for", "with", "from", "that", "this", "of", "on", "in", "to", "a", "an"}


def _tokens(text: object) -> set:
    words = re.findall(r"[a-z0-9]+", str(text or "").lower())
    return {w for w in words if len(w) > 2 and w not in _STOP}


def _matches(confirmed: str, extracted: Sequence[str], threshold: float = 0.6) -> bool:
    target = _tokens(confirmed)
    if not target:
        return True
    for name in extracted:
        other = _tokens(name)
        if other and len(target & other) / len(target) >= threshold:
            return True
    return False


def missing_outcomes(confirmation: Dict[str, Any], extracted_names: Sequence[str]) -> List[Dict[str, str]]:
    """Confirmed primary and secondary outcomes with no matching extracted outcome name."""
    misses: List[Dict[str, str]] = []
    for role in ("primary", "secondary"):
        for outcome in confirmation.get(role) or []:
            if not isinstance(outcome, dict):
                continue
            name = str(outcome.get("name") or "").strip()
            if name and not _matches(name, extracted_names):
                misses.append({"role": role, "name": name, "quote": str(outcome.get("quote") or "")[:200]})
    return misses


async def confirm_outcomes(text: str, model: str, api_key: str, client=None) -> Dict[str, Any]:
    """One model call: the primary and secondary outcomes the paper itself reports."""
    import httpx

    own = client is None
    client = client or httpx.AsyncClient(timeout=180, headers={"Authorization": f"Bearer {api_key}"})
    try:
        response = await client.post("/chat/completions", json={
            "model": model,
            "messages": [{"role": "user", "content": OUTCOME_PROMPT + "\n\nTEXT:\n" + str(text)[:20000]}],
            "response_format": {"type": "json_object"},
        })
        content = str(response.json()["choices"][0]["message"]["content"])
        match = re.search(r"\{.*\}", content, re.S)
        return json.loads(match.group(0)) if match else {}
    finally:
        if own:
            await client.aclose()
