"""Check a stored estimate against the arithmetic its own numbers must satisfy.

A row carries a coefficient, a standard error, and sometimes a t statistic, a p-value, a confidence interval or
arm counts. Those are not independent: t is the coefficient over its standard error, the p-value follows from t,
the interval is the coefficient plus or minus a multiple of the standard error, and the arm counts cannot exceed
the sample. Each check below is deterministic, needs no page, and can run at write time and over the collection.

The checks return a verdict and never guess a value. `flags` lists what failed, so a caller can drop a suspect
field, or leave the row alone and report it.
"""

from __future__ import annotations

import math
from typing import Dict, Optional


def _number(value) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def t_statistic(estimate, standard_error) -> Optional[float]:
    """The t statistic implied by a coefficient and its standard error, or None when undefined."""
    e, se = _number(estimate), _number(standard_error)
    if e is None or se in (None, 0):
        return None
    return e / se


def p_from_t(t, df: Optional[float] = None) -> Optional[float]:
    """The two-sided p-value for a t statistic, using the normal when the degrees of freedom are unknown."""
    value = _number(t)
    if value is None:
        return None
    z = abs(value)
    if df and df > 0:
        # A t distribution with many degrees of freedom is close to the normal; the approximation below is
        # deliberately conservative, because this check only separates a plausible p from an impossible one.
        z = z * (1 - 1 / (4 * df)) if df > 4 else z * 0.9
    return math.erfc(z / math.sqrt(2))


def check_t(estimate, standard_error, t, tolerance: float = 0.1) -> Dict[str, object]:
    """Does the stored t agree with the coefficient over the standard error?"""
    implied = t_statistic(estimate, standard_error)
    stored = _number(t)
    if implied is None or stored is None:
        return {"ok": True, "flags": []}
    allowed = max(abs(implied) * tolerance, 0.1)
    if abs(implied - stored) <= allowed:
        return {"ok": True, "flags": []}
    return {"ok": False, "flags": ["t does not equal estimate over standard error"]}


def check_p_value(t, p_value, df: Optional[float] = None, ratio: float = 2.0) -> Dict[str, object]:
    """Is the p-value consistent with t, allowing a factor of two either way for rounding and approximation?"""
    stored = _number(p_value)
    implied = p_from_t(t, df)
    if stored is None or implied is None:
        return {"ok": True, "flags": []}
    if stored <= 1 and implied <= 1 and implied / ratio - 0.01 <= stored <= implied * ratio + 0.01:
        return {"ok": True, "flags": []}
    return {"ok": False, "flags": ["p-value inconsistent with the t statistic"]}


def check_interval(estimate, standard_error, low, high, z_min: float = 1.4, z_max: float = 2.8) -> Dict[str, object]:
    """Does the interval sit around the coefficient at a plausible multiple of the standard error?"""
    e, se, lo, hi = _number(estimate), _number(standard_error), _number(low), _number(high)
    if None in (e, se, lo, hi) or se <= 0 or hi <= lo:
        return {"ok": True, "flags": []}
    width = hi - lo
    mid = (hi + lo) / 2
    implied = width / (2 * se)
    if abs(mid - e) > max(width * 0.25, abs(e) * 0.1):
        return {"ok": False, "flags": ["interval not centred on the estimate"]}
    if not (z_min <= implied <= z_max):
        return {"ok": False, "flags": [f"interval implies a multiplier of {implied:.2f}, not a usual one"]}
    return {"ok": True, "flags": []}


def check_counts(n_treatment, n_control, sample_size) -> Dict[str, object]:
    """Are the arm counts positive and compatible with a printed total?"""
    nt, nc, total = _number(n_treatment), _number(n_control), _number(sample_size)
    flags = []
    for label, value in (("n_treatment", nt), ("n_control", nc)):
        if value is not None and value <= 0:
            flags.append(f"{label} is not positive")
    if nt and nc and total and total < nt + nc:
        flags.append("sample size is smaller than the arms")
    return {"ok": not flags, "flags": flags}


def flags_for(row: Dict[str, object]) -> list:
    """Every consistency flag for one stored row."""
    df = None
    counts = [_number(row.get("n_treatment")), _number(row.get("n_control"))]
    if all(counts):
        df = counts[0] + counts[1] - 2
        if df <= 1:
            df = None
    flags = []
    flags += check_t(row.get("effect_size"), row.get("standard_error"), row.get("t_stat"))["flags"]
    flags += check_p_value(row.get("t_stat"), row.get("p_value"), df)["flags"]
    flags += check_interval(row.get("effect_size"), row.get("standard_error"),
                            row.get("ci_low"), row.get("ci_high"))["flags"]
    flags += check_counts(row.get("n_treatment"), row.get("n_control"), row.get("sample_size"))["flags"]
    return flags
