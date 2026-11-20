"""
Label the two axes of a table cell, so a later step can tell a programme effect from a description.

The reader keeps every printed estimate. This module adds a decision per cell without removing any:
each cell is given a row role and a column role, and a boolean that says whether the two axes make it a
programme effect. The rule fails open. A cell is marked as not an effect only when one of its axes is
explicitly named as a control, a covariate, a fixed effect, a dummy, a comparison before the programme,
or some other non-effect. Anything unfamiliar is kept.

The two axes are judged separately, because the same table can put the programme on either one: one axis
must be `outcome` and the other `programme_effect`. A period such as "between X and Y" or "X over Y" says
when an effect was measured and is not, on its own, a comparison before the programme.

Nothing here drops a row. `keep_effect` is stored as a flag; the drop threshold is set later.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

OUTCOME = "outcome"
SUBGROUP = "subgroup"
PROGRAMME_EFFECT = "programme_effect"
CONTROL = "control_or_covariate"
FIXED_EFFECT = "fixed_effect_or_dummy"
BEFORE = "comparison_before_programme"
NOT_AN_EFFECT = "not_an_effect"

ROLES = (OUTCOME, SUBGROUP, PROGRAMME_EFFECT, CONTROL, FIXED_EFFECT, BEFORE, NOT_AN_EFFECT)

# The axis that pairs with the programme effect to make a cell an effect. A subgroup is one: a row split
# by age group, gender or region names who the effect is for, not something other than an effect.
EFFECT_PARTNERS = frozenset({OUTCOME, SUBGROUP})

# An axis named with one of these makes the cell a non-effect. The test fails open on anything else.
DROP_ROLES = frozenset({CONTROL, FIXED_EFFECT, BEFORE, NOT_AN_EFFECT})

ROLE_PROMPT = """You label the two axes of a cell in a table from an impact evaluation, so a reader can
tell a programme effect from a description. You are not asked for values, only for the role of each row
label and each column header.

Roles:
- outcome: the axis names what is being measured (consumption, income, enrollment, a test score).
- subgroup: the axis names who the effect is for, or under what grouping it is estimated: an age group
  ("6-11 mo"), a gender, a region, a wealth quintile, "non-poor households". A subgroup is part of the
  effect, not a description, so it pairs with the programme effect exactly as outcome does. A row split by
  an age group, a gender or a region is a subgroup, never not_an_effect.
- programme_effect: the axis names the programme's effect, such as a treatment-versus-comparison
  difference, a difference-in-differences, a coefficient on a treatment term, a marginal effect, or a
  change in the effect between rounds. An effect-size column (a standardised mean difference, Cohen's d,
  a Hedges' g) and an odds-ratio column are programme_effect: they report the size of the effect.
- control_or_covariate: the axis names a control-group statistic, a baseline level, or a covariate that
  is held constant rather than the programme.
- fixed_effect_or_dummy: the axis names a fixed effect or an indicator dummy used as a control.
- comparison_before_programme: the axis names a comparison made before the programme began, between the
  groups as they already were.
- not_an_effect: the axis is a statistic, a test, a count, a cost, a ratio that is not an effect size, or
  a descriptive figure.

Rules:
- The columns of one table often name an estimation method (PSM, propensity score, kernel, nearest
  neighbour, regression adjustment, OLS, IV, ITT, coarsened exact matching). Such a column estimates the
  programme by that method and is a programme_effect.
- A mediation, pathway or indirect-effect estimate is a programme_effect.
- A change in the effect between rounds ("difference between impacts in 2005 and 2008", "change in
  impact") is a programme_effect, labelled as a change over time.
- A standardised effect-size column (Cohen's d, Hedges' g, a standardised mean difference) is a
  programme_effect; its sign follows the mean difference. An odds-ratio column is a programme_effect.
- A subgroup row (an age group, a gender, a region, a wealth quintile) is a subgroup, not
  not_an_effect, and pairs with the programme effect.
- A period such as "between X and Y" or "X over Y" says when an effect was measured. It is a comparison
  before the programme only when both dates fall before the programme began.
- Some tables have both a plain follow-up treatment-minus-comparison difference and a difference-in-
  differences. In those tables the follow-up difference is descriptive and the DiD is the programme
  effect; decide this row by row, because a row whose DiD cell is blank keeps its follow-up difference.
- A cell is a programme effect only when one axis is programme_effect and the other is outcome or
  subgroup.

Examples (from documents outside any audit sample):
- 121058367: row "T1 x Poultry" is programme_effect; column "(1)" is outcome.
- 121328483: "Test of difference in mean characteristics" is not_an_effect.
- 121294841: a column headed "2002" that reports the groups as they already were is
  comparison_before_programme.

Return JSON only, with the exact labels as keys:
{{"rows": {{"<row label>": "<role>"}}, "columns": {{"<column header>": "<role>"}}}}

Caption: {caption}
Row labels: {rows}
Column headers: {columns}
Table:
{table}"""


def normalise(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def match_role(roles: Dict[str, str], label: str) -> str:
    """The role for a label, by exact key, then containment, then the largest shared word set."""
    if not roles:
        return ""
    key = normalise(label)
    if not key:
        return ""
    table = {normalise(k): str(v or "").strip().lower() for k, v in roles.items()}
    if key in table:
        return table[key]
    for candidate, value in table.items():
        if candidate and (key in candidate or candidate in key):
            return value
    shared = {k: len(set(k.split()) & set(key.split())) for k in table}
    best = max(shared, key=shared.get, default="")
    return table[best] if best and shared[best] else ""


def keep_effect(row_role: str, column_role: str) -> bool:
    """Fail open: a cell is not an effect only when an axis is explicitly a non-effect role.

    A subgroup partners the effect axis as outcome does, so a (subgroup, programme_effect) cell is kept.
    """
    return str(row_role or "").strip().lower() not in DROP_ROLES and \
        str(column_role or "").strip().lower() not in DROP_ROLES


def parse_roles(answer: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """The two axis maps from a model answer, tolerant of an absent or malformed axis."""
    rows = answer.get("rows") if isinstance(answer, dict) else None
    columns = answer.get("columns") if isinstance(answer, dict) else None
    return {"rows": rows if isinstance(rows, dict) else {},
            "columns": columns if isinstance(columns, dict) else {}}


def _parse_json(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    match = re.search(r"\{.*\}", text, re.S)
    import json

    return json.loads(match.group(0) if match else text)


def build_prompt(caption: str, row_labels: list, column_headers: list, table_text: str,
                 page_image: Optional[str] = None) -> Any:
    """The role prompt for one table. Returns a plain string, or a multimodal content list."""
    text = ROLE_PROMPT.replace("{caption}", str(caption or "")[:300]) \
        .replace("{rows}", str([str(r)[:80] for r in row_labels])[:4000]) \
        .replace("{columns}", str([str(c)[:80] for c in column_headers])[:2000]) \
        .replace("{table}", str(table_text or "")[:24000])
    if not page_image:
        return text
    return [{"type": "text", "text": text}, {"type": "image_url", "image_url": {"url": page_image}}]


async def label_roles(client: httpx.AsyncClient, model: str, caption: str, row_labels: list,
                      column_headers: list, table_text: str,
                      page_image: Optional[str] = None) -> Dict[str, Dict[str, str]]:
    """One table's axis roles. Returns empty maps on any failure, which the fail-open rule then keeps."""
    content = build_prompt(caption, row_labels, column_headers, table_text, page_image)
    body = {"model": model, "temperature": 0, "max_tokens": 4000,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": content}]}
    for attempt in range(2):
        try:
            response = await client.post(OPENROUTER_URL, json=body)
            if response.status_code >= 500 or response.status_code == 429:
                raise httpx.HTTPStatusError("retryable", request=response.request, response=response)
            response.raise_for_status()
            answer = _parse_json(response.json()["choices"][0]["message"]["content"] or "")
            return parse_roles(answer)
        except (httpx.HTTPError, KeyError, ValueError):
            if attempt == 1:
                return {"rows": {}, "columns": {}}
    return {"rows": {}, "columns": {}}


def role_for_cell(axis_roles: Dict[str, Dict[str, str]], row_label: str, column_label: str) -> tuple:
    """The (row role, column role, keep) for one cell, failing open when a role is unknown."""
    row_role = match_role(axis_roles.get("rows") or {}, row_label)
    column_role = match_role(axis_roles.get("columns") or {}, column_label)
    return row_role, column_role, keep_effect(row_role, column_role)
