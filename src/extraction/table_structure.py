"""
Interpret the structure of a parsed table: what each column means before its values are trusted.

Tables arrive as Markdown, one item per parsed table, so the same logical table can be split across
pages and the column meaning is carried by headers and notes that use inconsistent words. This module
recovers that structure deterministically:

- `parse_markdown_table` turns Markdown into header rows, body rows and non-table note lines.
- `parse_conventions` reads the notes ("standard errors in parentheses", "*** p<0.01", "95% CI").
- `infer_columns` assigns a role to each column from the header, the notes and the value profile, and
  uses arithmetic consistency (estimate / SE = t, estimate ± 1.96 SE = CI) to resolve the rest.
- `stitch_units` joins a table that continues on the next page into one grid.

Every role carries the evidence that produced it and every interpretation carries a confidence, so a
low-confidence table can be flagged for review instead of being silently trusted. This module only
interprets structure; it does not call a model or read values.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from src.extraction.table_estimates import parse_number

ESTIMATE = "estimate"
SE = "se"
T = "t"
P = "p"
CI_LOW = "ci_low"
CI_HIGH = "ci_high"
N = "n"
MEAN = "mean"
SD = "sd"
STARS = "stars"
UNKNOWN = "unknown"

# Two layouts cover most economics tables: statistics in columns (one column per statistic) and
# statistics in rows (one row per statistic, one column per outcome or model).
LAYOUT_COLUMNS = "roles_in_columns"
LAYOUT_ROWS = "roles_in_rows"

_HEADER_ROLES: List[Tuple[str, Tuple[str, ...]]] = [
    (ESTIMATE, ("coefficient", "coef", "estimate", "beta", "point estimate", "treatment effect",
                "att", "ate", "itt", "impact", "effect size", "marginal effect", "dy/dx",
                "odds ratio", "hazard ratio", "exp(b)",
                # Spanish, Portuguese, French
                "efecto", "impacto", "coeficiente", "estimacion", "efeito", "effet")),
    (CI_LOW, ("ci lower", "ci_low", "lower bound", "lower ci", "ll", "lb", "ci lb", "2.5%", "low",
              "confidence interval lower", "confidence interval low",
              "intervalo de confianza inferior", "limite inferior", "ic inferior",
              "intervalo de confianca inferior")),
    (CI_HIGH, ("ci upper", "ci_up", "upper bound", "upper ci", "ul", "ub", "ci ub", "97.5%", "high",
               "confidence interval upper", "confidence interval high",
               "intervalo de confianza superior", "limite superior", "ic superior",
               "intervalo de confianca superior")),
    (SE, ("std err", "std. err", "standard error", "robust se", "clustered se", "s.e.", "s.e", "se",
          "error estandar", "erro padrao", "erreur standard", "ee")),
    (T, ("t-stat", "t stat", "t statistic", "tstat", "z-stat", "z stat", "z statistic", "zscore",
         "z-score", "t value", "t-value", "z value", "estadistico t", "estatistica t", "statistique t")),
    (P, ("p-value", "p value", "pvalue", "pval", "prob", "significance level", "sig",
         "valor p", "p valor", "p-valor", "significancia", "probabilidad", "probabilidade", "probabilite")),
    (N, ("observations", "n obs", "num obs", "sample size", "number of observations", "clusters",
         "cluster", "n", "observaciones", "observacoes", "numero de observaciones")),
    (MEAN, ("control mean", "mean", "average", "avg", "baseline mean", "media", "promedio", "moyenne")),
    (SD, ("std dev", "std. dev", "standard deviation", "sigma", "sd",
          "desviacion estandar", "desvio padrao", "ecart type")),
]

_NOTES = {
    "se_in_parens": re.compile(r"(standard errors?|std\.? errs?|s\.?e\.?s?)[^.]{0,20}(\(|parenth)", re.I),
    "t_in_parens": re.compile(r"(t|z)[- ]?stat[^.]{0,40}(\(|parenth|bracket)", re.I),
    "ci": re.compile(r"(confidence interval|95%\s*ci|\bci\b)", re.I),
    "clustered": re.compile(r"cluster", re.I),
    "percent": re.compile(r"percent|%", re.I),
}
_STAR_NOTE = re.compile(r"(\*{1,3})\s*(?:for|:|=)?\s*(?:p\s*[<>=]?\s*)?0?\.(\d+)", re.I)
# "0.15*** (0.05)" or "[0.31] (0.10)": an estimate with stars and its standard error in one cell.
COMBINED_CELL = re.compile(
    r"^\s*[-−–]?\d[\d.,]*\s*(?:\*{1,3}|†{1,2})?\s*[(\[]\s*[-−–]?\d[\d.,]*\s*[)\]]\s*$"
)

# Header and label abbreviations expanded before matching, so "ATT" and "s.e." read as phrases.
_ABBREV = {
    "att": "treatment effect on the treated", "ate": "average treatment effect",
    "itt": "intention to treat effect", "tot": "treatment on the treated",
    "late": "local average treatment effect", "te": "treatment effect",
    "coef": "coefficient", "coeff": "coefficient", "coef.": "coefficient",
    "se": "standard error", "s.e.": "standard error", "std err": "standard error",
    "obs": "observations", "nobs": "observations", "n obs": "observations",
    "pval": "p value", "p-val": "p value", "sig": "significance",
    "pp": "percentage points", "sd": "standard deviation", "d": "effect size",
    "diff": "difference", "delta": "difference",
}


def expand_abbreviations(text: str) -> str:
    tokens = _norm(text).split()
    expanded = []
    for i, token in enumerate(tokens):
        pair = f"{tokens[i - 1]} {token}" if i else ""
        if pair in _ABBREV:
            expanded.append(_ABBREV[pair])
        elif token in _ABBREV:
            expanded.append(_ABBREV[token])
        else:
            expanded.append(token)
    return " ".join(expanded)


def _fold(text: object) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(text or "")) if not unicodedata.combining(c))


def _flat(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _norm(text: object) -> str:
    return re.sub(r"[^a-z0-9%./]+", " ", _fold(text).lower()).strip()


@dataclass
class TableGrid:
    headers: List[List[str]]
    body: List[List[str]]
    notes: List[str] = field(default_factory=list)

    @property
    def ncols(self) -> int:
        rows = self.headers + self.body
        return max((len(r) for r in rows), default=0)

    def column(self, index: int) -> List[str]:
        return [row[index] for row in self.body if index < len(row)]


@dataclass
class Column:
    index: int
    header: str
    role: str
    evidence: str
    profile: Dict[str, float] = field(default_factory=dict)


@dataclass
class Interpretation:
    roles: List[Column]
    estimate: Optional[int]
    se: Optional[int]
    t: Optional[int]
    p: Optional[int]
    ci_low: Optional[int]
    ci_high: Optional[int]
    combined: bool
    conventions: Dict[str, bool]
    stars_map: Dict[int, float]
    confidence: float
    warnings: List[str] = field(default_factory=list)
    layout: str = LAYOUT_COLUMNS
    row_roles: Dict[str, int] = field(default_factory=dict)
    # Non-role column headers, when the columns name outcomes and the rows are treatment arms with
    # a standard-error row beneath each ("Tot | logTot | Food", arms TUP*2014 down the first column).
    outcome_columns: List[str] = field(default_factory=list)
    # Method prefixes when the columns repeat a coefficient, standard error and p-value block, as in
    # "No adjustment - coef. | No adjustment - s.e. | Matching & regression - coef. | ...".
    stat_blocks: List[str] = field(default_factory=list)


def _split_row(line: str) -> List[str]:
    cells = line.strip().strip("|").split("|")
    return [_flat(c) for c in cells]


def parse_markdown_table(text: str) -> TableGrid:
    """Header rows, body rows and note lines from a Markdown table."""
    rows: List[List[str]] = []
    separator_at: Optional[int] = None
    notes: List[str] = []
    for line in str(text or "").splitlines():
        if "|" in line:
            cells = _split_row(line)
            if re.fullmatch(r"[:\-\s|]+", line.strip()) and "-" in line:
                separator_at = len(rows) if separator_at is None else separator_at
                continue
            rows.append(cells)
        elif line.strip() and re.match(r"(note|notes|source|standard errors?|t-?stat|\*|†|cluster)", line.strip(), re.I):
            notes.append(_flat(line))
    if not rows:
        return TableGrid([], [], notes)
    if separator_at is not None:
        headers = rows[:separator_at] or rows[:1]
        body = rows[separator_at:]
    else:
        # No separator: the first row is the header unless it is mostly numeric.
        numeric = sum(1 for c in rows[0] if parse_number(c) is not None)
        headers = rows[:1] if numeric <= max(0, len(rows[0]) // 2) else []
        body = rows[len(headers):]
    return TableGrid(headers, body, notes)


def parse_conventions(notes: str) -> Tuple[Dict[str, bool], Dict[int, float]]:
    text = _flat(notes)
    conventions = {name: bool(pattern.search(text)) for name, pattern in _NOTES.items()}
    stars: Dict[int, float] = {}
    for stars_count, value in _STAR_NOTE.findall(text):
        stars[len(stars_count)] = float(f"0.{value}")
    return conventions, stars


def _statistic_header(header: str) -> bool:
    """True when the header names a statistic rather than a column of estimates.

    Anchored on purpose: "Lower Bounds - (2) - 0.25 SD" describes a sensitivity bound and is a column of
    estimates, but a substring test sees "SD" and drops it, which is how paper 121058369's appendix lost
    five of its seven columns.
    """
    text = _flat(header).lower().strip(" :-")
    if not text or len(text) > 24:
        return False
    return bool(re.match(r"^(se|s\.e\.?|std\.?\s*(err|error|dev)\.?|standard (error|deviation)|"
                         r"t|t[- ]?stat(istic)?|p|p[- ]?value|sd|s\.d\.?|prob|observations?|n|mean|average)\b",
                         text))


def _star_only(values: Sequence[str]) -> bool:
    present = [str(v).strip() for v in values if str(v).strip()]
    return bool(present) and all(re.fullmatch(r"[*†‡]{1,3}", v) for v in present)


def _role_from_header(header: str) -> Tuple[Optional[str], str]:
    key = expand_abbreviations(header)
    if not key:
        return None, ""
    for role, phrases in _HEADER_ROLES:
        for phrase in phrases:
            if "." in phrase:
                matched = phrase in key
            elif len(phrase) <= 4:
                # Short forms such as ATT, ATE, SE, N, mean must be whole words, so "att" does not
                # match "attrition" and "ate" does not match "rate".
                matched = bool(re.search(rf"\b{re.escape(phrase)}s?\b", key))
            else:
                matched = key == phrase or key.startswith(phrase) or f" {phrase}" in f" {key}"
            if matched:
                return role, f"header '{_flat(header)}'"
    return None, ""


def _profile(values: Sequence[str]) -> Dict[str, float]:
    nums = [v for v in (parse_number(x) for x in values) if v is not None]
    if not nums:
        return {"n": 0.0}
    n = len(nums)
    return {
        "n": float(n),
        "min": min(nums),
        "max": max(nums),
        "share_unit_interval": sum(1 for v in nums if 0 <= v <= 1) / n,
        "share_integer": sum(1 for v in nums if float(v).is_integer()) / n,
        "share_small": sum(1 for v in nums if abs(v) <= 10) / n,
    }


def _profile_hint(profile: Dict[str, float]) -> Tuple[Optional[str], str]:
    n = profile.get("n", 0)
    if n < 3:
        return None, ""
    if profile["share_integer"] >= 0.9 and profile["min"] >= 20:
        return N, "value profile: whole counts"
    # A small decimal column could be a p-value, an SE, a coefficient or an elasticity, so the
    # value profile alone does not decide it. Leave it unknown for header, notes or arithmetic.
    return None, ""


def _combined_share(values: Sequence[str]) -> float:
    present = [v for v in values if str(v).strip()]
    if not present:
        return 0.0
    return sum(1 for v in present if COMBINED_CELL.match(str(v))) / len(present)


def infer_columns(grid: TableGrid, notes: str = "") -> List[Column]:
    conventions, _ = parse_conventions(notes)
    headers = [_flat(c) for c in (grid.headers[-1] if grid.headers else [])]
    columns: List[Column] = []
    for index in range(grid.ncols):
        header = headers[index] if index < len(headers) else ""
        role, evidence = _role_from_header(header)
        values = grid.column(index)
        if role is None and conventions["se_in_parens"] and _looks_like_estimate_column(values):
            role, evidence = SE, "notes: standard errors in parentheses"
        if role is None and _combined_share(values) >= 0.5:
            # Outcomes in columns, each cell "estimate*** (SE)" with no role labels at all. Half the
            # rows are enough, because one row may print "[p] estimate" instead of "estimate (SE)".
            role, evidence = ESTIMATE, "cells look like an estimate with its standard error"
        if role is None:
            hint, why = _profile_hint(_profile(values))
            if hint:
                role, evidence = hint, why
        columns.append(Column(index, header, role or UNKNOWN, evidence or "no evidence", _profile(values)))
    return columns


def _looks_like_estimate_column(values: Sequence[str]) -> bool:
    return any(re.search(r"[-−–]?\d[\d.,]*\s*(\(|\*+|†)", str(v)) for v in values)


def resolve_consistency(columns: List[Column], grid: TableGrid) -> Tuple[List[Column], List[str]]:
    """Resolve an unlabelled numeric column by arithmetic: estimate / SE = t and estimate ± 1.96 SE = CI."""
    warnings: List[str] = []
    estimate = next((c for c in columns if c.role == ESTIMATE), None)
    if estimate is None:
        return columns, warnings
    est_vals = [parse_number(x) for x in grid.column(estimate.index)]
    labelled = {c.role for c in columns if c.role != UNKNOWN}
    unknown = [c for c in columns if c.role == UNKNOWN and c.profile.get("n", 0) >= 2]
    has_t = T in labelled
    if unknown and not has_t:
        best, best_score = None, 0.0
        for cand in unknown:
            vals = [parse_number(x) for x in grid.column(cand.index)]
            pairs = [(e, v) for e, v in zip(est_vals, vals) if e not in (None, 0) and v not in (None, 0)]
            if not pairs:
                continue
            ratios = [abs(e / v) for e, v in pairs]
            consistent = sum(1 for r in ratios if 0.5 <= r <= 20 and abs(r - round(r)) < 0.05) / len(ratios)
            if consistent > best_score:
                best, best_score = cand, consistent
        if best is not None and best_score >= 0.5:
            best.role = SE
            best.evidence = f"consistency: estimate / column is a whole t-like ratio in {best_score:.0%} of rows"
            warnings.append("SE column has no header; inferred from arithmetic, check a sample")
    return columns, warnings


_PAREN_ONLY = re.compile(r"^\s*[(\[]\s*[-−–]?\d[\d.,]*\s*[)\]]\s*$")


def _all_parenthesised(cells: Sequence[str]) -> bool:
    present = [c for c in cells if str(c).strip()]
    return bool(present) and all(_PAREN_ONLY.match(str(c)) for c in present)


MAX_SPLIT_COLUMNS = 16


def _starred(value: object) -> bool:
    return bool(re.search(r"[-−–]?\d[\d.,]*\s*[*†‡]", str(value)))


# A whole cell that is a number: optional stars, then any parenthesised or bracketed statistics beside it.
# "0.106* (0.060) [0.206]" is data, not a column name, and the bracket must not hide that.
_DATA_CELL = re.compile(r"^\s*[-−–]?\d[\d.,]*\s*[*†‡]*\s*(?:\s*[\(\[][^)\]]*[\)\]])*\s*$")


def estimate_columns(grid: TableGrid, limit: int = MAX_SPLIT_COLUMNS) -> List[int]:
    """Body columns that carry estimates rather than a statistic about them.

    Column 0 is the label column and is skipped. A column qualifies when at least one cell is a
    starred number, or when two of its numbers have a parenthesised cell directly beneath them, which
    is the coefficient row with its standard error below. A column whose header names a statistic
    (standard error, t, p, confidence interval, count, mean) is left out, and so is one that is
    nothing but parenthesised numbers, the standard-error column.
    """
    headers = grid.headers[-1] if grid.headers else []
    out: List[int] = []
    for index in range(1, grid.ncols):
        header = headers[index] if index < len(headers) else ""
        if _statistic_header(header):
            continue
        values = [str(v) for v in grid.column(index)]
        if not any(v.strip() for v in values) or _all_parenthesised(values):
            continue
        starred = sum(1 for v in values if _starred(v))
        beneath = sum(1 for k, v in enumerate(values[:-1])
                      if parse_number(v) is not None and _PAREN_ONLY.match(values[k + 1] or ""))
        # A cell such as "-398 (-0.82)" is an estimate with its t statistic and no stars at all. Paper
        # 122182716's third panel column is entirely like this, and requiring stars or an SE row beneath
        # left the whole column unread.
        shaped = _looks_like_estimate_column(values)
        # Some tables print the significance stars in the column beside the value, so "-81.6" arrives
        # without its stars and the column looks empty of estimates.
        stars_beside = (index + 1 < grid.ncols and _star_only(grid.column(index + 1))
                        and any(parse_number(v) is not None for v in values))
        if starred or shaped or beneath >= 2 or stars_beside:
            out.append(index)
        if len(out) >= limit:
            break
    return out


_SUBGROUP_ROW = re.compile(
    r"\b(age|gender|sex|male|female|boys?|girls?|men|women|members?|children|household size|cohort|"
    r"young|old|elderly|literate|educated|married|widow)", re.I)
_STAT_HEADER = re.compile(r"^(\(?\d+\)?|model\b|coef|c\.o\.e|s\.?e\.?\b|t[- ]?stat|p[- ]?value|p\b|"
                          r"treatment\b|control\b|t\d)", re.I)


def subgroup_rows_layout(grid: TableGrid) -> bool:
    """Rows define subgroups and the columns are outcomes, as in a heterogeneity table.

    Paper 121354848's page 33 is the shape: "Household under 5 members" and "Household over 5 members"
    down the rows, "Per capita consumption" across the columns. A regression table that puts covariates in
    the rows is excluded, because its columns are models, coefficients or statistics rather than outcomes.
    """
    labels = [str(row[0]).strip() for row in grid.body if row and str(row[0]).strip()]
    if len(labels) < 2:
        return False
    if sum(1 for label in labels if _SUBGROUP_ROW.search(label)) / len(labels) < 0.6:
        return False
    headers = [str(cell).strip() for cell in (grid.headers[-1] if grid.headers else [])][1:]
    named = [header for header in headers if header]
    if len(named) < 2:
        return False
    return not any(_STAT_HEADER.match(header) for header in named)


_ARM_ROW = re.compile(r"^\s*(treatment|treated|control|untreated|placebo|comparison|programme|program"
                        r"|intervention|arm|full|half|t\d+|sup|nsup)\b", re.I)

# Rows that name a treatment or a regressor, for a table whose columns are outcomes. "control" is absent
# on purpose: "Control over earnings" is an outcome, and a bare "control" cannot tell the two apart.
_ROLE_ROW = re.compile(
    r"^\s*(treatment|treated|programme|program|intervention|arm|full|half|t\d+|sup|nsup|"
    r"received|intensive|extension|phase|one year|year\s*\d|waves?\b|round\b|follow[- ]?up|baseline|"
    r"\b(19|20)\d{2}\b)", re.I)
# The arm test is wider than the layout test: a spillover arm or an ITT row is a role for the arm, but
# widening _ROLE_ROW itself changes the table interpretation the reader already relies on.
_ARM_ROLE = re.compile(
    r"^\s*(treatment|treated|programme|program|intervention|arm|full|half|t\d+|sup|nsup|"
    r"received|intensive|extension|phase|one year|year\s*\d|waves?\b|round\b|follow[- ]?up|baseline|"
    r"spillover|itt|\b(19|20)\d{2}\b)", re.I)
_ORDINAL = re.compile(r"^\s*\(\d+\)\s*[-–]?\s*|\s*\(\d+\)\s*$")
# Headers that name a position, a period or a fragment, not an outcome.
_BAD_HEADER = re.compile(
    r"^\s*(column\s+\d+|of\b|and\b|the\b|"
    r"\d+\s*(months?|years?|weeks?|days?)|"
    r"(last|this|next|previous)\s+\w+(\s+\w+)?\s+(season|year|month)|"
    r"(baseline|endline|midline|follow[- ]?up|round\s+\d+|wave\s+\d+))\s*$", re.I)


def header_name(text: str) -> str:
    """A column header without the leading or trailing panel ordinal, such as "(2) GVAO" to "GVAO"."""
    return _ORDINAL.sub("", str(text or "")).strip()


def _role_norm(text) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


_METHOD = re.compile(
    r"(ridge|lasso|dr ?did|\bpsm\b|propensity|2sls|\biv\b|\bols\b|\batt\b|kernel|"
    r"nearest neighbo|hierarchy|coef\s*/|\bs\.\s?e\.|p ?value|specification)", re.I)
_SUBGROUP_WORDS = {"male", "female", "girls", "boys", "girl", "boy", "industry", "industries",
                   "services", "service", "agriculture", "agricultural", "traditional", "wealth",
                   "rural", "urban", "age", "religion", "married", "widow", "total"}


def method_label(text) -> str:
    """The label when it names an estimation method, else an empty string."""
    return str(text or "").strip() if _METHOD.search(str(text or "")) else ""


def subgroup_label(text) -> str:
    """The label when it is a short subgroup category (one or two words), else an empty string."""
    words = re.findall(r"[a-z]+", str(text or "").lower())
    return str(text or "").strip() if len(words) <= 2 and any(w in _SUBGROUP_WORDS for w in words) else ""


def is_role(label) -> bool:
    return bool(_ARM_ROLE.match(str(label or "")))


def fixed_arm(outcome, arm, row_label, column_header, panel="") -> str:
    """The arm to store: the row label when the arm merely repeats the header or the outcome.

    A subgroup row is not an arm, and a row that is already the outcome is left alone so the layout swap
    is not masked by copying the row label into the arm.
    """
    if not _role_norm(arm) or not (_role_norm(arm) == _role_norm(column_header)
                                   or _role_norm(arm) == _role_norm(outcome)):
        return arm
    if _role_norm(outcome) == _role_norm(row_label):
        return arm
    if is_role(row_label):
        return str(row_label).strip()
    if panel:
        return str(panel).strip()
    return arm


def assign_roles(outcome, arm, row_label, column_header, panel="", subgroup="", raw_arm=""):
    """Move a method or a subgroup out of the outcome or arm into its own field.

    A method in the arm clears the arm and takes the row label when the row is a treatment. A subgroup in
    the outcome or arm clears that field and takes the row label when it is a usable outcome. A method in
    the outcome is tagged but kept, because the table subject is not known from the cell alone. `raw_arm`
    is the model's arm before an outcome-in-columns swap, so a method it named is not lost.
    """
    method = ""
    from_arm = method_label(arm)
    if from_arm:
        method = from_arm
        arm = str(row_label).strip() if is_role(row_label) else ""
    elif method_label(raw_arm):
        method = method_label(raw_arm)
    if not subgroup:
        from_arm = subgroup_label(arm) or subgroup_label(raw_arm)
        if from_arm:
            subgroup = from_arm
            arm = str(row_label).strip() if is_role(row_label) else ""
        else:
            from_outcome = subgroup_label(outcome)
            if from_outcome and row_label and not subgroup_label(row_label) and not method_label(row_label):
                subgroup = from_outcome
                outcome = str(row_label).strip()
    arm = fixed_arm(outcome, arm, row_label, column_header, panel)
    # An arm copied into the outcome field is not an outcome. When the two are the same label, the outcome
    # is the row label; a study that names its treatment "Treatment X 2009" must not store that as what it
    # measured.
    if row_label and outcome and arm and _role_norm(outcome) == _role_norm(arm) \
            and _role_norm(row_label) != _role_norm(outcome):
        outcome = str(row_label).strip()
    return outcome, arm, method, subgroup


_PERIOD = re.compile(
    r"between\s+(?:19|20)\d{2}\s+and\s+(?:19|20)\d{2}|(?:19|20)\d{2}\s*[-–]\s*(?:19|20)\d{2}|"
    r"(?:in|during)\s+(?:19|20)\d{2}", re.I)
# A time point printed as a panel or column heading ("after 2 years", "year 7", "endline 2").
_TIME = re.compile(
    r"after\s+\d+\s+(?:year|month|week)s?|\b(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+"
    r"years?\s+(?:later|after|in)\b|year\s+\d+|endline\s*\d*|midline|follow[- ]?up", re.I)
# The population a spillover or secondary effect is estimated on, named in the title ("other poor women").
_POPULATION = re.compile(
    r"other\s+(?:poor|ultra[- ]?poor|non[- ]?poor)\s+(?:women|men|households|participants)|"
    r"non[- ]?participant\s+(?:households|women|men)|spillover", re.I)
_PANEL = re.compile(r"panel\s+[a-z0-9]+", re.I)
_SHOCK = re.compile(r"house\s*damage|em\s*died|illness|flood|drought|shock|death", re.I)
_PATHWAY = re.compile(r"pathway", re.I)


def derive_subgroup(row_label, column_header, caption, existing="", outcome="") -> str:
    """Keep a panel, period, shock type or pathway as a qualifier, never discard it.

    The model's subgroup is kept first, then any such qualifier found in the row label, column header,
    caption or the (possibly swapped) outcome is appended, without repeating an identical one.

    A row carries one time point. When the row label, its column or its outcome names one, that is the
    row's own: a time on the model's subgroup that names a different point belongs to another panel and is
    dropped, so "Programme effect after 2 years" is not stored as "after 2 years - after 4 years".
    """
    texts = [str(t or "") for t in (row_label, column_header, outcome, caption)]
    row_time, row_time_key = "", ""
    for text in texts:
        match = _TIME.search(text)
        if match:
            row_time, row_time_key = match.group(0).strip(), _role_norm(match.group(0))
            break
    found = []
    for item in str(existing or "").split(" - "):
        item = item.strip()
        if not item:
            continue
        match = _TIME.search(item)
        if match and row_time_key and _role_norm(match.group(0)) != row_time_key:
            continue
        found.append(item)
    if row_time and all(_role_norm(item) != row_time_key for item in found):
        found.append(row_time)
    for text in texts:
        for pattern in (_PERIOD, _POPULATION, _PANEL, _SHOCK, _PATHWAY):
            match = pattern.search(text)
            if match:
                found.append(match.group(0).strip())
    out = []
    keys = set()
    own = _role_norm(f"{row_label} {outcome}")
    for item in found:
        key = _role_norm(item)
        if not item or key in keys:
            continue
        # Drop a period the row's own label already carries inside it: "Measured economy in 2005" does not
        # also need "in 2005" appended (audit 2026-11-20, the stray "in 2005"). A label that IS the
        # qualifier ("between 2002 and 2004", "House damage"), or the row's own time point, is left alone.
        if key != row_time_key and key in own and key != _role_norm(outcome) and key != _role_norm(row_label):
            continue
        out.append(item)
        keys.add(key)
    return " - ".join(out)


def outcome_in_columns(row_label: str, header: str) -> bool:
    """True when the row names a treatment or regressor and the column header names the outcome."""
    label = str(row_label or "").strip()
    head = str(header or "").strip()
    if not label or not head or not _ROLE_ROW.match(label) or _ARM_ROW.match(header_name(head)):
        return False
    if _BAD_HEADER.match(head) or head.count(")") > head.count("("):
        return False
    return True


_OBS_ROW = re.compile(r"^\s*(observations?|obs\.?|no\.? of observations|number of observations|n|"
                      r"sample size|n obs)\s*$", re.I)


def observation_counts(grid: TableGrid) -> Optional[List[Optional[float]]]:
    """The per-column observation counts, when the table prints a row of them that varies by column.

    A row of equal counts is a pooled figure repeated across the columns, not a count per arm, and is
    returned as None so it is never mistaken for one.
    """
    for row in grid.body:
        if not row or not _OBS_ROW.match(str(row[0])):
            continue
        counts = []
        for cell in row[1:]:
            value = re.sub(r"[^\d]", "", str(cell))
            counts.append(float(value) if value else None)
        present = [count for count in counts if count]
        if len(present) >= 2 and len(set(present)) > 1:
            return counts
        return None
    return None


_CONTROL_HEADER = re.compile(r"control|comparison|placebo|untreated|non-?beneficiar|\bnsup\b", re.I)


def control_count(grid: TableGrid) -> Optional[float]:
    """The observation count of the control column, when the table prints one per column.

    A control column usually carries no stars, so it is never one of the estimate views; its count has to be
    taken from the header instead, and it applies to every effect row of the same table.
    """
    counts = observation_counts(grid)
    if not counts:
        return None
    headers = grid.headers[-1] if grid.headers else []
    for index in range(1, grid.ncols):
        name = headers[index] if index < len(headers) else ""
        if _CONTROL_HEADER.search(str(name)) and index - 1 < len(counts) and counts[index - 1]:
            return counts[index - 1]
    return None


def arm_row_label(grid: TableGrid) -> Optional[str]:
    """The row that names the arm, when the columns of the table are outcomes.

    Paper 121378494 page 6 prints one body row, "Treatment", with the outcomes across the columns. The model
    labels each estimate with the column heading as its arm, so the row label is the arm and must be used.
    """
    labelled = [row for row in grid.body if row and str(row[0]).strip()]
    if not labelled or not _ARM_ROW.match(str(labelled[0][0])):
        return None
    outcomes = [row for row in labelled if not _ARM_ROW.match(str(row[0]))
                and not _OBS_ROW.match(str(row[0]))]
    if len(outcomes) <= 1:
        return str(labelled[0][0]).strip()
    return None


def carry_merged_labels(text: str) -> str:
    """Fill an empty first-column cell with the label above it, when the row carries an estimate.

    A table that merges one label across several rows gives the later rows an empty first cell, so their
    values arrive with no outcome name and the reader cannot store them. Eight cells in the collection were
    lost this way. A row that holds only a parenthesised standard error is a continuation of the row above
    and is left alone, so the error is not turned into an outcome of its own.
    """
    grid = parse_markdown_table(text)
    if not grid.body or grid.ncols < 2:
        return text
    last = ""
    changed = False
    body = [list(row) for row in grid.body]
    for row in body:
        if not row:
            continue
        label = str(row[0]).strip()
        if label:
            last = label
            continue
        rest = [str(cell).strip() for cell in row[1:] if str(cell).strip()]
        carries_estimate = any(re.search(r"\d", cell) and not _PAREN_ONLY.match(cell) for cell in rest)
        if last and carries_estimate:
            row[0] = last
            changed = True
    if not changed:
        return text
    lines = ["| " + " | ".join(row) + " |" for row in grid.headers]
    lines.append("| " + " | ".join(["---"] * grid.ncols) + " |")
    lines += ["| " + " | ".join(row) + " |" for row in body]
    lines += grid.notes
    return "\n".join(lines)


def split_estimate_columns(text: str, limit: int = MAX_SPLIT_COLUMNS, min_columns: int = 2) -> List[Dict[str, str]]:
    """One narrow table per estimate column, so a wide table is read one column at a time.

    A row such as `Cash savings (BDT) | 278*** (3.40) | -10 | -153 | 1664*** (10.57) | 196*** | ...` is
    the shape a reader reads across, but one model call over the whole width returns the first column
    and stops. Each entry here is the label column with a single estimate column and that column's
    header, which the caller passes to the model as the arm. An empty list means the table has fewer
    than two estimate columns and is read whole as before.

    Two shapes need care. A grouped header such as `(2) | Panel regression results (equation 1)`
    repeats the same words across columns, so the group number is kept in the name, and a continuation
    table whose first row is data rather than a header is named by position and that row is kept in the
    body where it belongs.
    """
    grid = parse_markdown_table(text)
    if grid.ncols < 3 or not grid.body:
        return []
    # A table whose only row is an arm ("Treatment", "Full cost") and whose columns are outcomes must be
    # read whole: a column view would mistake an outcome for an arm. Paper 121378494 page 6 is that shape.
    labelled = [row for row in grid.body if row and str(row[0]).strip()]
    if labelled and _ARM_ROW.match(str(labelled[0][0])):
        outcomes = [row for row in labelled if not _ARM_ROW.match(str(row[0]))
                    and not _OBS_ROW.match(str(row[0]))]
        if len(outcomes) <= 1:
            return []
    columns = estimate_columns(grid, limit)
    if len(columns) < min_columns:
        return []
    header_rows = grid.headers or []

    def header_label(index: int) -> Tuple[str, bool]:
        cells = [str(row[index]) for row in header_rows if index < len(row) and str(row[index]).strip()]
        joined = " ".join(cells).strip()
        # A cell is a header unless the whole cell is a number, with stars or a parenthesised
        # statistic: "Year8*Treatment" is a label even though it contains a digit, "278*** (3.40)"
        # is data that arrived in the header row of a continuation table.
        if joined and not _DATA_CELL.match(joined):
            return joined, False
        return "", bool(cells)

    names: List[Tuple[int, str, bool]] = []
    for ordinal, index in enumerate(columns, start=1):
        label, data_in_header = header_label(index)
        names.append((index, label or f"column {ordinal}", data_in_header))
    repeats = Counter(name for _, name, _ in names)
    counts = observation_counts(grid)
    label_head = header_rows[0][0] if header_rows and header_rows[0] else "Outcome"
    units: List[Dict[str, str]] = []
    for ordinal, (index, name, data_in_header) in enumerate(names, start=1):
        if repeats[name] > 1:
            name = f"{name} ({ordinal})"
        body = list(grid.body) + ([header_rows[-1]] if data_in_header else [])
        beside = index + 1 < grid.ncols and _star_only(grid.column(index + 1))
        lines = [f"| {label_head or 'Outcome'} | {name} |", "| --- | --- |"]
        for row in body:
            label_cell = row[0] if row else ""
            value = row[index] if index < len(row) else ""
            if beside and index + 1 < len(row) and parse_number(value) is not None:
                stars = str(row[index + 1]).strip()
                if stars:
                    value = f"{str(value).strip()} {stars}"
            if not str(label_cell).strip() and not str(value).strip():
                continue
            lines.append(f"| {label_cell} | {value} |")
        units.append({"header": name, "text": "\n".join(lines),
                      "n_hint": counts[index - 1] if counts and 0 < index <= len(counts) else None})
    return units


def _row_roles(grid: TableGrid) -> Dict[str, int]:
    """Roles carried by the first column, for the statistics-in-rows layout."""
    roles: Dict[str, int] = {}
    for i, row in enumerate(grid.body):
        label = row[0] if row else ""
        role, _ = _role_from_header(label)
        key = _norm(label)
        if role is None and key in ("treatment", "treat", "program", "programme", "impact", "effect"):
            role = ESTIMATE
        if role is None and ESTIMATE in roles and SE not in roles and _all_parenthesised(row[1:]):
            # The row under the coefficient row prints only "(SE)" in each outcome column.
            role = SE
        if role in (ESTIMATE, SE, T, P, N, CI_LOW, CI_HIGH) and role not in roles:
            roles[role] = i
    return roles


def interpret_table(text: str, notes: str = "") -> Interpretation:
    grid = parse_markdown_table(text)
    note_text = " ".join([notes] + grid.notes) if notes else " ".join(grid.notes)
    conventions, stars_map = parse_conventions(note_text)
    columns = infer_columns(grid, note_text)
    columns, warnings = resolve_consistency(columns, grid)
    row_roles = _row_roles(grid)
    layout = LAYOUT_ROWS if ESTIMATE in row_roles and len(row_roles) >= 2 else LAYOUT_COLUMNS
    se_rows = sum(1 for row in grid.body if _all_parenthesised(row[1:]))
    unnamed_headers = [_flat(c) for c in (grid.headers[-1] if grid.headers else [])
                       if _flat(c) and _role_from_header(_flat(c))[0] is None]
    outcome_columns = unnamed_headers if len(unnamed_headers) >= 2 and se_rows >= 2 else []
    estimate_headers = [_flat(c) for c in (grid.headers[-1] if grid.headers else [])
                        if _flat(c) and _role_from_header(_flat(c))[0] == ESTIMATE]
    prefixes: List[str] = []
    for header in estimate_headers:
        prefix = re.split(r"\s*[-–—]\s*", header)[0].strip()
        if prefix and prefix.lower() not in (p.lower() for p in prefixes):
            prefixes.append(prefix)
    stat_blocks = prefixes if len(prefixes) >= 2 else []

    def index_of(role: str) -> Optional[int]:
        return next((c.index for c in columns if c.role == role), None)

    estimate = index_of(ESTIMATE)
    if estimate is None:
        estimate = index_of(MEAN)
    combined = bool(estimate is not None and _looks_like_estimate_column(grid.column(estimate)))
    confidence = 0.4
    for col in columns:
        if col.role != UNKNOWN:
            confidence += 0.12
        if "consistency" in col.evidence:
            confidence += 0.15
    if conventions.get("se_in_parens") or conventions.get("ci"):
        confidence += 0.1
    if layout == LAYOUT_ROWS:
        confidence += 0.2
        warnings.append("statistics in rows: outcomes or models are columns, roles are rows")
    if estimate is None and layout == LAYOUT_COLUMNS:
        warnings.append("no estimate column identified")
    return Interpretation(
        roles=columns,
        estimate=estimate,
        se=index_of(SE),
        t=index_of(T),
        p=index_of(P),
        ci_low=index_of(CI_LOW),
        ci_high=index_of(CI_HIGH),
        combined=combined,
        conventions=conventions,
        stars_map=stars_map,
        confidence=min(0.95, confidence),
        warnings=warnings,
        layout=layout,
        row_roles=row_roles,
        outcome_columns=outcome_columns,
        stat_blocks=stat_blocks,
    )


def stitch_units(units: Sequence[Dict[str, object]]) -> List[Dict[str, object]]:
    """Merge a table continued on the next page into one unit.

    A unit is merged when it starts with the same header cells as the previous one (the header is
    repeated on the new page) or when its caption marks a continuation, and its page is at most one
    page after. The repeated header row is dropped and the bodies are concatenated.
    """
    merged: List[Dict[str, object]] = []
    for unit in units:
        if not merged:
            merged.append(dict(unit))
            continue
        prev = merged[-1]
        prev_grid = parse_markdown_table(str(prev.get("text") or ""))
        grid = parse_markdown_table(str(unit.get("text") or ""))
        same_header = bool(prev_grid.headers and grid.headers and prev_grid.headers[-1] == grid.headers[-1])
        caption = _flat(unit.get("caption")).lower()
        continued = "continued" in caption or "cont." in caption
        adjacent = (unit.get("page") is None or prev.get("page") is None
                    or int(unit["page"]) - int(prev["page"]) <= 1)
        if (same_header or continued) and adjacent:
            body = prev_grid.body + grid.body
            header = prev_grid.headers
            text = "\n".join("| " + " | ".join(r) + " |" for r in header + body)
            prev["text"] = text
            prev["page_end"] = unit.get("page")
            continue
        merged.append(dict(unit))
    return merged
