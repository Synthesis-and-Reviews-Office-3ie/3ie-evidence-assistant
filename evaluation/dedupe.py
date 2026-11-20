"""Deterministic choice of which stored row to keep when several point to the same printed cell."""
import re


def _norm(text) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def keeper(rows):
    """The row to keep: an error if one has it, then an arm, then the longer outcome, then the lowest id.

    The longer outcome is preferred because it is usually the more specific label. The id breaks a tie
    so the choice is stable across runs.
    """
    return sorted(rows, key=lambda row: (
        0 if row.get("standard_error") is not None else 1,
        0 if str(row.get("treatment_arm") or "").strip() else 1,
        -len(str(row.get("outcome_name") or "")),
        str(row.get("id")),
    ))[0]


def combined_labels(labels) -> str:
    """The distinct labels joined with " - ", dropping one that is contained in a longer one.

    Two duplicates at one cell often carry different parts of the label: the table subject and the row
    subgroup. Combining keeps both. A label already contained in a longer label adds nothing, so it is
    dropped, which avoids "% of households: X - X".
    """
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
