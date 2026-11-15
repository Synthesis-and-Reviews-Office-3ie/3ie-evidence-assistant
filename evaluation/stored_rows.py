"""Read the stored estimates without losing rows, and compare them the way a reader would.

Two problems pushed the measured recall below the real one.

The PostgREST endpoint returns at most 1000 rows per request whatever `limit` says, so
`select(...).limit(5000)` quietly returned the first 1000. A document with 2,261 stored rows was
compared against a quarter of them, and `evaluation/error_report.py` and
`evaluation/missing_estimates_audit.py` both reported misses that were in the table.

The second is arithmetic. A paper prints `691.149` and the hand-typed key holds `691.179` from the
authors' own output; the printed `4.224`, `4.180` and `4.300` sit either side of a key value of
`4.24`. Those are not extraction failures and no extraction change recovers digits the paper does
not print, so a comparison has to allow for the precision the paper actually shows.

This module is the one place both rules live, for the audit scripts and for anything scheduled.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

PAGE = 1000  # PostgREST returns at most this many rows per request.


def fetch_all(query: Any, page: int = PAGE) -> list[dict[str, Any]]:
    """Every row the query matches, paged so a large document is not silently truncated.

    `query` is a supabase-py query builder, so this stays the same call chain the callers already
    use: `fetch_all(sb.table("effect_estimates").select(...).eq(...))`.
    """
    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        batch = query.range(start, start + page - 1).execute().data or []
        rows.extend(batch)
        if len(batch) < page:
            return rows
        start += page


def decimals(value: float) -> int:
    """How many decimal places the stored number carries.

    A whole number counts as none, so a table printing `6143` takes a key value of `6143.406`; a
    table printing `2.40` takes `2.404`. A table printing `691.149` does not take `691.179`, because
    the difference is larger than half of the last decimal printed, and that is a different number.
    """
    number = float(value)
    if number == int(number):
        return 0
    text = repr(number)
    if "e" in text or "E" in text:
        return 6
    return len(text.split(".")[1])


def tolerance(stored_value: float) -> float:
    """Half of the last decimal place a stored value was printed to."""
    return 0.5 * 10 ** -decimals(stored_value)


def matches(value: float, stored: Iterable[float]) -> bool:
    """True when a stored value is the same number as `value` at the precision it was printed."""
    return any(other is not None and abs(value - other) <= tolerance(other) for other in stored)


def classify_miss(value: float, stored: Sequence[float]) -> str:
    """Why a hand-typed value did not match, or `exact` / `rounded` when it did.

    `rounded` and `exact` are matches, and the caller reports `rounded` separately so printed
    precision is never counted as a gap in the extractor. `wrong_value` means the outcome is stored
    at a different number, which is the arm or panel attribution case. `absent` means no stored value
    stands in for it at printed precision.
    """
    if any(value == other for other in stored if other is not None):
        return "exact"
    if matches(value, stored):
        return "rounded"
    return "absent"
