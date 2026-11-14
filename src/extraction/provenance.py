"""
Tell a policy brief or summary from the paper behind it.

The collection holds a study id whose document is a 12-page policy brief, not the impact paper. Its
text has no tables and almost no results vocabulary, so the hand-typed numbers for that study cannot
be found in it. Counting them as extraction misses overstates the gap.

The signal is density, not presence: a results paper uses "table", "regression", "coefficient" and
"standard error" many times, while a brief mentions one of them in passing at most. A table-free,
short document with fewer than three of those mentions is treated as the wrong version of a study.
"""

from __future__ import annotations

_STRONG_WORDS = ("table", "regression", "coefficient", "standard error")


def looks_like_wrong_version(text: object, table_count: int, max_chars: int = 25000,
                             min_hits: int = 3) -> bool:
    """True when the document is too short, too table-free and too word-poor to be the results paper."""
    value = str(text or "")
    if table_count > 0:
        return False
    if len(value) > max_chars:
        return False
    lowered = value.lower()
    hits = sum(lowered.count(word) for word in _STRONG_WORDS)
    return hits < min_hits
