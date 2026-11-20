"""Deterministic choice of which stored row to keep when several point to the same printed cell."""

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
