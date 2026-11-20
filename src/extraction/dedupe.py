"""
Deduplicate extracted estimates.

The structure-aware reader finds more of a table, and the same estimate can then appear more than
once: a panel repeated, a table reproduced in an appendix, or the same row read from two overlapping
tables. Extracting more than once is safe, but the estimates the reader is shown are ranked by
similarity to the question, so duplicates take slots from other estimates. This removes exact repeats
without merging distinct outcomes.

A duplicate is the same outcome (after stripping a leading "(1)" or "Panel A:"), arm, subgroup and
values. When two duplicates differ only in what they recorded, the kept row is filled from the other,
so a standard error seen once is not lost.

The cell rule below is the second, stricter pass: the same table view, cell address and coefficient.
It combines a subgroup label with its table subject instead of dropping one.

Provenance: the idea matches TVET's `pipeline/dedupe_rules.yaml` and `dedupe_outcomes.py`, with a
stricter key here (exact values rather than cosine clustering) because a false merge loses evidence.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

_LEAD = re.compile(r"^\s*(panel\s*[a-z0-9]+\s*[:.\-]?|\(?\d{1,2}\)?\s*[:.\-]?|table\s*[a-z0-9]+\s*[:.\-]?)\s*", re.I)
_FILL = ("standard_error", "t_stat", "ci_low", "ci_high", "p_value", "sample_size")


def _norm(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def _outcome_key(text: Any) -> str:
    key = str(text or "").strip()
    previous = None
    while previous != key:  # strip stacked prefixes, e.g. "(1) Panel A: Consumption"
        previous = key
        key = _LEAD.sub("", key).strip()
    return _norm(key)


def _round(value: Any) -> Any:
    return round(float(value), 9) if isinstance(value, (int, float)) else value


def _identity(row: Dict[str, Any]) -> Tuple:
    """Outcome, arm, subgroup and estimate define the row; the rest may be missing in one copy."""
    return (
        _outcome_key(row.get("outcome")),
        _norm(row.get("arm")),
        _norm(row.get("subgroup")),
        _round(row.get("effect_size")),
    )


def _compatible(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    for field in ("standard_error", "t_stat", "ci_low", "ci_high", "p_value", "sample_size"):
        left, right = a.get(field), b.get(field)
        if left is not None and right is not None and left != right:
            return False
    return True


def dedupe_estimates(rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    """Keep one row per (outcome, arm, subgroup, estimate). Two rows merge when their other values
    agree or one lacks them; a gap in the kept row is filled from the other."""
    kept: List[Dict[str, Any]] = []
    groups: Dict[Tuple, List[Dict[str, Any]]] = {}
    dropped = 0
    for row in rows:
        base = _identity(row)
        target = next((candidate for candidate in groups.get(base, []) if _compatible(candidate, row)), None)
        if target is None:
            groups.setdefault(base, []).append(row)
            kept.append(row)
            continue
        dropped += 1
        for field in _FILL:
            if target.get(field) is None and row.get(field) is not None:
                target[field] = row[field]
    return kept, dropped


def combined_labels(labels) -> str:
    """The distinct labels joined with " - ", dropping one contained in a longer one."""
    clean = []
    for label in labels:
        text = str(label or "").strip()
        if text and text not in clean:
            clean.append(text)
    kept = [text for text in clean
            if not any(_norm(text) in _norm(other) and _norm(text) != _norm(other) for other in clean)]
    return " - ".join(kept)


def should_combine(labels) -> bool:
    """True when one label is a single word and another is a longer phrase.

    That is the shape of a subgroup label beside its table subject ("Delta Jobs" and "Industry"). Two long
    phrases are often different outcomes that happen to share a value, and combining them would be wrong.
    """
    lengths = [len(_norm(label).split()) for label in labels if _norm(label)]
    return any(length == 1 for length in lengths) and any(length >= 2 for length in lengths)


def keeper_rows(rows):
    """The row to keep: an error, then an arm, then the longer outcome, then the id or source text."""
    return sorted(rows, key=lambda row: (
        0 if row.get("standard_error") is not None else 1,
        0 if str(row.get("treatment_arm") or "").strip() else 1,
        -len(str(row.get("outcome_name") or "")),
        str(row.get("id") or row.get("text_position") or row.get("outcome_name") or ""),
    ))[0]


def dedupe_rows(rows):
    """One row per (view, cell, coefficient), with combined labels when the two labels complement."""
    groups, passthrough = {}, []
    for row in rows:
        key = (row.get("unit_index"), row.get("cell_row"), row.get("cell_column"), row.get("effect_size"))
        if key[0] is None or key[1] is None or key[2] is None or key[3] is None:
            passthrough.append(row)
        else:
            groups.setdefault(key, []).append(row)
    result = []
    for group in groups.values():
        keep = keeper_rows(group)
        if should_combine([row.get("outcome_name") for row in group]):
            keep = dict(keep)
            keep["outcome_name"] = combined_labels(
                [row.get("outcome_name") for row in group]) or keep.get("outcome_name")
            keep["treatment_arm"] = combined_labels(
                [row.get("treatment_arm") for row in group]) or keep.get("treatment_arm")
        result.append(keep)
    return result + passthrough
