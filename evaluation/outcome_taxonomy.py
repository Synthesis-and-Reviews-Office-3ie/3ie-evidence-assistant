"""A small canonical outcome taxonomy for matching hand-typed labels to extracted labels.

The hand key and the extractor name the same outcome differently, and the extractor's
labels are often raw table row fragments. Mapping both to a fixed set of categories makes
the comparison about whether the estimate was found, not about wording.

`categories` returns a set, because one label can name two constructs ("consumption and
income"). Matching requires the categories to intersect and the value to agree, which is
stricter than comparing values anywhere in the document.
"""

from __future__ import annotations

import re

# Order matters only for readability; every rule is tested and the union is returned, so a
# label that mentions two constructs lands in both categories.
RULES = (
    ("poverty", r"\bpoverty\b|\bpoor\b|\bmpi\b|multidimensional poverty|poverty (line|gap|headcount)"),
    ("food_security", r"food (security|insecure|consumption|expenditure|spending)|hunger|diet|nutrition|"
                      r"calorie|hfas|fies|dietary diversity|stunting"),
    ("livestock", r"livestock|\btlu\b|cattle|goat|sheep|poultry|chicken|\begg\b|\bherd\b|\bmilk\b|"
                  r"\banimals?\b"),
    ("agriculture", r"\bcrop|harvest|agricultur|\bfarm|seed|fertiliz|irrigat|planting"),
    ("savings_finance", r"saving|tontine|\bavec\b|\bbank|credit|\bloan|borrow|financial inclusion|"
                        r"insurance|microfinance"),
    ("assets", r"\basset|durable|property|land owner|land ownership|productive asset"),
    ("housing", r"housing|house quality|roof|toilet|electricity|water access|sanitation"),
    ("income", r"\bincome|earning|\bwage|revenue|\bprofit|salary|remittance|transfer"),
    ("consumption", r"consumption|expenditure|spending|\bspend"),
    ("employment", r"employ|labour|labor|\bwork|hours|\bjob|unemploy|self employ"),
    ("business", r"business|enterprise|microenterprise|\bfirm|\bshop\b|\btrade"),
    ("empowerment", r"empower|decision making|bargaining|autonomy|\bagency\b|gender|\bwomen\b|female"),
    ("health", r"\bhealth|illness|\bsick|mental|depress|anxiety|\bstress|wellbeing|well being|"
               r"\bbmi\b|anthropometr|\bheight\b|\bweight\b"),
    ("education", r"educat|school|literacy|enrol|attend|learning|test score|cognitive|child development"),
    ("social", r"social capital|cohesion|cooperation|\btrust|network|group member|community"),
    ("psychosocial", r"aspiration|\bhope\b|locus of control|self esteem|psychosocial|happiness|"
                     r"life satisfaction"),
    ("migration", r"migrat|remittance"),
    ("resilience", r"resilien|\bshock|coping|drought|flood|recovery"),
    ("fertility_children", r"fertility|\bbirth|number of children|\bchildren\b"),
)

_COMPILED = tuple((name, re.compile(pattern)) for name, pattern in RULES)

# A key category accepts its descendants. Livestock is a kind of asset (Lucas's call, 20 November 2026,
# after reviewing the misses on the 49 study documents). Stored rows keep their own category; only the
# key side is widened. Do not add another pair without asking.
DESCENDANTS = {"assets": {"livestock"}}


def accepts(key_categories: set) -> set:
    """The key categories plus their descendants, for matching a key label to stored labels."""
    widened = set(key_categories)
    for category in key_categories:
        widened.update(DESCENDANTS.get(category, ()))
    return widened


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def is_noise(label: str) -> bool:
    """True for a label with no usable words, such as a bare number or bracketed value."""
    words = [w for w in _norm(label).split() if len(w) >= 2 and not w.isdigit()]
    return not words


def categories(label: str) -> set:
    """Canonical outcome categories for a label. Returns ``{"noise"}`` for unusable labels."""
    text = _norm(label)
    if is_noise(label):
        return {"noise"}
    found = {name for name, pattern in _COMPILED if pattern.search(text)}
    return found or {"other"}
