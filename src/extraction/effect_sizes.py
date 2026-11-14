"""
Standardised effect sizes for pooling.

A raw coefficient is not comparable across studies: it is in the units of its outcome. The human key
standardises each estimate to Hedge's g and carries `d`, `var(d)`, `yi`, `vi` and `se(g)`. This module
does the same arithmetic, from the inputs a row actually has, and returns nothing when an input is
missing rather than guessing.

Formulas (standard meta-analysis):
- `d = estimate / sd`, and `var(d) = se^2 / sd^2` when the coefficient's standard error is known.
- `g = J * d` with `J = 1 - 3 / (4 * df - 1)` and `df = n_treat + n_control - 2`, so `g` is the
  small-sample-corrected `d`.
- `var(g) = J^2 * var(d)`, `se(g) = sqrt(var(g))`, and `yi`/`vi` are `g`/`var(g)` for a single study.

The 8WR sheet records a `Formula Used` code (5 and 6). Its exact definitions are not documented in the
repo, so this module writes a descriptive formula name instead of a code; reproducing the 8WR codes
needs those definitions.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def hedges_correction(n_treat: float, n_control: float) -> Optional[float]:
    df = n_treat + n_control - 2
    if df <= 1:
        return None
    return 1 - 3 / (4 * df - 1)


def d_from_coefficient(estimate: Any, standard_error: Any, sd: Any) -> Optional[Dict[str, float]]:
    """`d` and `var(d)` from a coefficient, its standard error and the outcome's standard deviation."""
    e, se, s = _finite(estimate), _finite(standard_error), _finite(sd)
    if e is None or s is None or s == 0:
        return None
    d = e / s
    if se is None:
        return None
    return {"d": d, "var_d": (se / s) ** 2}


def standardise(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Standardised fields for one estimate, or None when `sd` or the sample sizes are missing."""
    base = d_from_coefficient(row.get("effect_size"), row.get("standard_error"), row.get("control_sd"))
    n_treat, n_control = _finite(row.get("n_treatment")), _finite(row.get("n_control"))
    j = hedges_correction(n_treat, n_control) if n_treat and n_control else None
    if base is None or j is None:
        return None
    d, var_d = base["d"], base["var_d"]
    g = j * d
    var_g = (j ** 2) * var_d
    return {
        "d": d, "var_d": var_d, "yi": g, "vi": var_g, "se_g": math.sqrt(var_g),
        "formula_used": "d = estimate / control_sd; g = J * d",
    }
