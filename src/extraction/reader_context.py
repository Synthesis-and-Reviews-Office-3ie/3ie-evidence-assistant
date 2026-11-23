"""
Context for the table reader: the study card's lists and a few worked gallery examples.

The card is read once per document (see study_cards.py). It fixes what the model may put in arm, time
point, population and subgroup, and it decides which tables hold results. The gallery supplies two or three
worked tables with the correct answer, chosen by tags.

Tags are made by code first, from the caption and the table itself; a model call is only a fallback when the
code finds nothing.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional

METHOD_TAGS = {
    "DiD and triple differences": r"difference[- ]in[- ]difference|\bDiD\b|\bDD\b|triple[- ]diff",
    "IV/2SLS (first stage vs second stage)": r"\bIV\b|2SLS|instrument|first[- ]stage",
    "matching/PSM/IPW": r"propensity|PSM|matching|IPW|inverse probability",
    "regression discontinuity": r"discontinuity|\bRDD\b",
    "quantile regression": r"quantile",
    "bounds (Lee, Manski)": r"Lee\s*\(?2009\)?|Manski|bounds?\b",
    "cost-effectiveness": r"cost[- ]effect|cost per|benefit[- ]cost",
    "multiple-testing adjusted (q-values, FWER)": r"q-value|q value|false discovery|FWER|Bonferroni|sharpened",
    "event study": r"event[- ]study|event[- ]time",
    "panel fixed effects": r"fixed effect|fixed-effect",
    "heterogeneity by interaction terms": r"interaction|heterogen",
    "RCT (ITT, TOT/LATE, ANCOVA)": r"\bITT\b|\bTOT\b|\bLATE\b|randomi[sz]ed|control mean|ANCOVA|treatment effect",
}
FORMAT_TAGS = {
    "odds ratio, risk ratio, hazard ratio": r"odds ratio|\bOR\b|hazard ratio|risk ratio|\bRR\b",
    "standardised effect size (d, g, SD units)": r"Cohen|Hedges|standardi[sz]ed|effect size|standard deviation units|\bSD\b",
    "percentage change or % of control mean": r"percent(age)? of|%\s*of|as a percentage",
    "mean difference": r"difference in means|mean difference|difference between means",
    "change in effect between rounds": r"change in (the )?(treatment )?effect|difference between impacts",
    "comparison minus programme or other reversed convention": r"\bA\s*[-−]\s*B\b|benefit attributable|control minus",
    "marginal effect from logit or probit": r"marginal effect|\blogit\b|\bprobit\b",
}
LAYOUT_TAGS = {
    "SE, t or CI in brackets below or beside": r"\(\s*[-−]?\.?\d|\[\s*[-−]?\.?\d",
    "p-values in their own column": r"\bp[- ]?value|\bp\s*[<>=]",
    "stars only, no SE": r"\*{1,3}",
    "Panel A/B stacks": r"panel\s+[aab]\b|panel\s+[12]\b",
    "several arms": r"arm|treatment\s*[123]|grants?|hybrid|control",
    "several rounds": r"(?:19|20)\d{2}.*(?:19|20)\d{2}|round\s*[123]|endline|baseline|follow[- ]?up",
    "subgroup columns or rows": r"male|female|boys|girls|urban|rural|quintile|poor|age group|\bmen\b|\bwomen\b",
    "covariate rows": r"covariate|controls?:|age of|education|household size",
    "control-mean and N rows": r"control mean|\bN\b|observations",
    "transposed (outcomes in columns)": r"\btot\b|\blogTot\b|food|savings",
}


def _hits(text: str, table: Dict[str, str]) -> List[str]:
    return [tag for tag, pattern in table.items() if re.search(pattern, text, re.I | re.S)]


def table_tags(caption: str, text: str) -> Dict[str, List[str]]:
    """Tags from the caption and the table itself, by keyword and layout signal."""
    blob = f"{caption}\n{text}"
    methods = _hits(blob, METHOD_TAGS)[:2]
    formats = _hits(blob, FORMAT_TAGS)[:2]
    layouts = _hits(blob, LAYOUT_TAGS)
    if not formats:
        formats = ["coefficient"]
    return {"method": methods, "format": formats, "layout": layouts}


def _norm_tag(tag: str) -> set:
    return set(re.sub(r"[^a-z0-9]+", " ", str(tag).lower()).split())


def pick_entries(tags: Dict[str, List[str]], entries: List[Dict[str, Any]], k: int = 3) -> List[Dict[str, Any]]:
    """The k closest entries by shared tag words, method weighted above layout."""
    want_method = set().union(*[_norm_tag(t) for t in tags.get("method", [])]) if tags.get("method") else set()
    want_format = set().union(*[_norm_tag(t) for t in tags.get("format", [])]) if tags.get("format") else set()
    want_layout = set().union(*[_norm_tag(t) for t in tags.get("layout", [])]) if tags.get("layout") else set()

    def score(entry):
        et = entry.get("tags") or {}
        em = set().union(*[_norm_tag(t) for t in et.get("method", [])]) if et.get("method") else set()
        ef = set().union(*[_norm_tag(t) for t in et.get("format", [])]) if et.get("format") else set()
        el = set().union(*[_norm_tag(t) for t in et.get("layout", [])]) if et.get("layout") else set()
        return 3 * len(want_method & em) + 2 * len(want_format & ef) + len(want_layout & el)

    ranked = sorted(entries, key=score, reverse=True)
    return [e for e in ranked[:k] if score(e) > 0] or ranked[:2]


def entry_text(entry: Dict[str, Any]) -> str:
    """A worked example as prompt text: the table, the rows to store, the cells not to store, the rule."""
    stored = entry.get("stored_rows") or []
    lines = [f"EXAMPLE {entry.get('id', '')}", "TABLE:",
             str(entry.get("snippet") or "")[:2500], "STORE (the correct rows):"]
    for row in stored[:40]:
        lines.append("- " + json.dumps({k: row.get(k) for k in
                                        ("outcome", "arm", "time_point", "subgroup_or_population", "value",
                                         "se", "effect_type") if row.get(k) not in (None, "")},
                                       ensure_ascii=False))
    lines.append("DO NOT STORE:")
    for item in (entry.get("not_stored") or [])[:20]:
        lines.append(f"- {item.get('cell', '')}: {item.get('reason', '')}")
    lines.append(f"RULE: {entry.get('rule', '')}")
    return "\n".join(lines)


def examples_block(entries: Iterable[Dict[str, Any]]) -> str:
    return "\n\n".join(entry_text(e) for e in entries) or "(none)"


def card_block(card: Optional[Dict[str, Any]]) -> str:
    """The card's lists, as the only allowed values for arm, time point, population and subgroup."""
    if not card:
        return "(no card)"
    arms = [a for a in card.get("arms") or [] if a]
    rounds = [r.get("since_baseline") or r.get("name") or "" for r in card.get("rounds") or []]
    rounds = [r for r in rounds if r]
    pops = [p for p in card.get("populations") or [] if p]
    conventions = [c.get("convention") if isinstance(c, dict) else c for c in card.get("sign_conventions") or []]
    lines = ["Arms (use one of these, or 'not on card'):", "; ".join(arms) or "(none)",
             "Time points (use one of these, or 'not on card'):", "; ".join(rounds) or "(none)",
             "Populations (use one of these, or 'not on card'):", "; ".join(pops) or "(none)",
             "Sign conventions (do not flip a sign except as these say):",
             "; ".join(str(c) for c in conventions if c) or "(none)"]
    return "\n".join(lines)


def on_card(value: str, options: List[str]) -> bool:
    """True when value is one of the card's options, by normalised containment either way."""
    if not value or not options:
        return not value
    v = re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()
    for option in options:
        o = re.sub(r"[^a-z0-9]+", " ", str(option).lower()).strip()
        if v and o and (v in o or o in v):
            return True
    return False


def validate_labels(row: Dict[str, Any], card: Optional[Dict[str, Any]]) -> List[str]:
    """Replace a label the card does not carry with 'not on card', and return what was changed."""
    if not card:
        return []
    arms = [a for a in card.get("arms") or []] + [card.get("comparison_group") or ""]
    rounds = [(r.get("since_baseline") or r.get("name") or "") for r in card.get("rounds") or []]
    pops = list(card.get("populations") or [])
    changed = []
    for key, options in (("arm", arms), ("time_point", rounds), ("subgroup_or_population", pops)):
        value = row.get(key)
        if value and options and not on_card(value, options):
            row[key] = "not on card"
            changed.append(key)
    return changed
