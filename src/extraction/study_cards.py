"""
A study card: one reading of a paper, made once, that the table reader consults.

The table reader sees only a caption and two nearby text items, but most label faults in the audits (the
arm, the time point, the population, a reversed sign) are defined elsewhere in the paper. One model call per
document reads the abstract, the methods and data sections and the results text, and writes the card. The
card fixes what the table reader must not guess:

- the outcome label is the table's own row-header text, taken by code, so the card does not write it;
- the arm, the time point, the population and the subgroup are chosen only from the card's lists, or
  reported as not on the card;
- the card decides, once per document, which tables hold results, so the table reader does not re-decide.

The card never copies a finding the paper reports from another study.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

TABLE_ROLES = ("main effect", "heterogeneity", "robustness", "balance", "first stage", "descriptive", "cost")

CARD_PROMPT = """Read one impact-evaluation paper and write a study card the table reader will use. The
card records the paper's own definitions, so the reader never guesses an arm, a time point, a population or
a sign. It must not copy a finding the paper reports from another study.

Answer with JSON only, no explanation, using exactly these keys:
- "title": the authors and year as "Author (Year)", never a section heading or the journal name.
- "methods": every evaluation method the paper uses, each as a short string (e.g. "randomised controlled
  trial with ITT", "difference-in-differences", "propensity score matching", "IV/2SLS", "bounds"). Read the
  methods and data sections, not only the abstract.
- "arms": every treatment or comparison group, named as the paper prints it (e.g. "grants only", "hybrid",
  "control"). Include the comparison group.
- "rounds": every survey round, each {"name": "...", "dates": "...", "since_baseline": "..."}.
- "comparison_group": the group the effects are measured against, as printed.
- "sign_conventions": every convention the authors define, each a short string. Take each one from a table's
  column headers, that table's notes, or the methods text, and give its page and a quote in "evidence". For
  every table whose header subtracts two groups, such as "A-B" or "Control - Program", record a convention
  that names the two groups and the direction: the header "Benefit attributable to program (%) A-B", with
  A = Control and B = Program, defines the benefit as comparison minus programme. Never take a convention from
  a sentence that reports a result: Raza 2018 Table 2 prints -0.125 for a wasting reduction, so a prose
  sentence calling it "12.5pp" must not become a convention that flips signs. Include units the authors
  define.
- "populations": every spillover or subgroup population the paper studies, each a short string (e.g. "other
  poor women", "non-poor households").
- "tables": every table that holds an estimate, each {"label": "...", "page": <int 1-based>,
  "role": one of {roles}, "evidence": {"page": <int>, "quote": "<a short quote>"}}. Use the TABLE LIST to name
  them all, including tables late in a long document. A table whose numbers are means, balance, attrition or
  counts is "balance" or "descriptive", not "main effect". A plain follow-up difference (a means table with a
  difference column) is "descriptive" when the paper estimates the same outcomes with a model, such as a
  regression or a difference-in-differences, in another table.
- "evidence": a page and a short quote for methods, for arms, for rounds and for sign_conventions, each
  {"page": <int>, "quote": "<short quote>"}.

Title: {title}
Text:
{text}"""


def _parse_json(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    match = re.search(r"\{.*\}", text, re.S)
    return json.loads(match.group(0) if match else text)


def document_text(content_list: List[Dict[str, Any]], limit: int = 120000) -> tuple:
    """The title and the reading material of a document: its table list, headings and running text.

    The table list and the headings come first, so a long document does not lose its later tables to a cut:
    Jalal 2009 is a 143-page thesis and its Table 3.10 sits at page 70. The running text follows.
    """
    title = next((str(i.get("text") or "") for i in content_list if i.get("type") == "title"), "")
    labels = []
    for idx, item in enumerate(content_list):
        if item.get("type") != "table":
            continue
        label = ""
        for prior in reversed(content_list[:idx]):
            text = str(prior.get("text") or "").strip()
            if text:
                label = text.splitlines()[0][:120]
                break
        labels.append(f"{label or '(no label)'} (page {item.get('page_idx', 0) + 1})")
    headings = [str(i.get("text") or "").strip() for i in content_list
                if i.get("type") == "section_header" and str(i.get("text") or "").strip()]
    body = "\n".join(str(i.get("text") or "") for i in content_list
                     if i.get("type") in ("text", "title", "section_header"))
    digest = ("TABLE LIST:\n" + "\n".join(labels[:400])
              + "\n\nHEADINGS:\n" + "\n".join(headings[:300])
              + "\n\nTEXT:\n" + body)
    return title, digest[:limit]


_AUTHOR_YEAR = re.compile(r"_([A-Za-z][A-Za-z'\-]+)_\((\d{4})\)")


def author_year(doc_key: str) -> str:
    """The author and year from a document key, such as "Roy (2015)". Empty when the key has neither."""
    match = _AUTHOR_YEAR.search(str(doc_key or ""))
    return f"{match.group(1)} ({match.group(2)})" if match else ""


def empty_card() -> Dict[str, Any]:
    return {"title": "", "methods": [], "arms": [], "rounds": [], "comparison_group": "",
            "sign_conventions": [], "populations": [], "tables": [], "evidence": {}}


def normalise_card(card: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only the fields the reader relies on, with the right shape."""
    out = empty_card()
    if not isinstance(card, dict):
        return out
    out["title"] = str(card.get("title") or "").strip()
    for key in ("methods", "arms", "populations"):
        value = card.get(key)
        if isinstance(value, list):
            out[key] = [str(x).strip() for x in value if str(x).strip()]
    conventions = []
    for item in card.get("sign_conventions") or []:
        if isinstance(item, dict):
            text = str(item.get("convention") or item.get("text") or "").strip()
            if text:
                conventions.append({"convention": text,
                                    "evidence": item.get("evidence") if isinstance(item.get("evidence"), dict) else {}})
        elif str(item).strip():
            conventions.append({"convention": str(item).strip(), "evidence": {}})
    out["sign_conventions"] = conventions
    out["comparison_group"] = str(card.get("comparison_group") or "").strip()
    rounds = card.get("rounds")
    if isinstance(rounds, list):
        out["rounds"] = [r for r in rounds if isinstance(r, dict)]
    tables = card.get("tables")
    if isinstance(tables, list):
        for t in tables:
            if not isinstance(t, dict):
                continue
            role = str(t.get("role") or "").strip().lower()
            out["tables"].append({"label": str(t.get("label") or "").strip(),
                                  "page": t.get("page"), "role": role,
                                  "evidence": t.get("evidence") if isinstance(t.get("evidence"), dict) else {}})
    if isinstance(card.get("evidence"), dict):
        out["evidence"] = card["evidence"]
    return out


async def build_card(client: httpx.AsyncClient, model: str, title: str, text: str,
                     max_tokens: int = 8000) -> Dict[str, Any]:
    """One study-card reading of a document. Returns an empty card on failure, which keeps the reader open."""
    prompt = CARD_PROMPT.replace("{roles}", ", ".join(f'"{r}"' for r in TABLE_ROLES)) \
        .replace("{title}", str(title or "")[:300]).replace("{text}", str(text or ""))
    body = {"model": model, "temperature": 0, "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": prompt}]}
    for attempt in range(3):
        try:
            response = await client.post(OPENROUTER_URL, json=body)
            if response.status_code == 429 or response.status_code >= 500:
                raise httpx.HTTPStatusError("retryable", request=response.request, response=response)
            response.raise_for_status()
            payload = response.json()
            choices = payload.get("choices") or []
            if not choices or not choices[0]["message"].get("content"):
                raise ValueError("no content")
            return normalise_card(_parse_json(choices[0]["message"]["content"]))
        except Exception:
            if attempt == 2:
                return empty_card()
    return empty_card()


def role_of_table(card: Dict[str, Any], page: Optional[int], label: str = "") -> str:
    """The role the card gives a table, matched by page first and by label second. "" when unknown."""
    tables = (card or {}).get("tables") or []
    key = re.sub(r"[^a-z0-9]+", "", str(label or "").lower())
    for t in tables:
        if t.get("page") is not None and page is not None and int(t["page"]) == int(page):
            return str(t.get("role") or "")
    for t in tables:
        other = re.sub(r"[^a-z0-9]+", "", str(t.get("label") or "").lower())
        if key and other and (key in other or other in key):
            return str(t.get("role") or "")
    return ""


def card_lists(card: Dict[str, Any]) -> Dict[str, List[str]]:
    """The lists the table reader may choose from: arms, time points and populations."""
    rounds = [str(r.get("name") or "").strip() for r in (card or {}).get("rounds") or []]
    since = [str(r.get("since_baseline") or "").strip() for r in (card or {}).get("rounds") or []]
    return {"arms": list(card.get("arms") or []) + [card.get("comparison_group") or ""],
            "time_points": [x for x in rounds + since if x],
            "populations": list(card.get("populations") or [])}
