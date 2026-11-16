"""A stable identity for a stored estimate, so a re-run can add and update but never silently drop.

Extraction replaces a document's rows, which made recall depend on a stochastic read: a run that did not
reproduce a row lost it. The identity here is what the database upserts on. It is built from what defines
the estimate rather than from what the model wrote about it: the page, the outcome as printed, the arm,
the subgroup and the value. A re-run that finds the same estimate therefore updates it in place, and one
that finds it with a better standard error fills the gap.

The same formula is written in `supabase/migrations/20261116000100_effect_estimates_row_key.sql` for the
rows that already exist, so old and new rows share one identity scheme.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

# A leading table, panel or column marker, and a trailing bare column number. A run may call the same
# outcome "Per capita consumption" and "Per capita consumption (2)" on two passes of one table, and the
# two must be one row, or every re-run adds a near-duplicate.
_LEAD = re.compile(r"^\s*(?:panel\s+[a-z0-9]+\s*[:.\-]?|\(\d{1,2}\)\s*[:.\-]?|table\s+[a-z0-9]+\s*[:.\-]?)\s*",
                   re.I)
_TRAIL = re.compile(r"\s*\(\s*(?:\d{1,2}|[ivx]{1,3})\s*\)\s*$", re.I)


def _part(value: Any) -> str:
    return " ".join(str(value or "").lower().split()).strip()


def _outcome(value: Any) -> str:
    text = _LEAD.sub("", _part(value))
    text = _TRAIL.sub("", text)
    return text.strip(" .:;-")


def _size(value: Any) -> str:
    """The estimate as an integer in units of 1e-9, so Python and Postgres agree exactly.

    Rendering a float as text does not agree across the two for small numbers (`1e-05` against
    `0.00001`); multiplying by a billion and rounding gives one integer both sides compute the same way.
    """
    if value is None:
        return ""
    return str(int(round(float(value) * 1_000_000_000)))


def row_key(source: str, page: int | None, outcome: Any, arm: Any, subgroup: Any,
            effect_size: Any) -> str:
    """The hex identity of one stored estimate.

    The database uses md5 of the same pipe-joined string, with the estimate rounded to nine decimals on
    both sides so a float rendered by Python and by Postgres gives the same key.
    """
    payload = "|".join([_part(source), "" if page is None else str(int(page)), _outcome(outcome),
                        _part(arm), _part(subgroup), _size(effect_size)])
    return hashlib.md5(payload.encode("utf-8")).hexdigest()
