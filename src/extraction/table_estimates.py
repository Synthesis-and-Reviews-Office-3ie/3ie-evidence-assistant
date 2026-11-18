"""
Extract treatment-effect estimates from a document's tables (roadmap N6 step 2).

Works on the parser output saved for every document (Docling `content_list`: each
table as Markdown with its page and caption). Per table, one model call decides
whether it is a results table and, if so, lists its estimates with the cells copied
verbatim. Numbers are then parsed from those cells by tested code (parse_number,
parse_estimate_cell), and a row is kept only if its cells appear in the table, so a
figure the model did not read from the table cannot get in.

Why not reuse what exists: the graduation review's 2025 extraction found 8 and the
repo's rule-based V6 pipeline 9 of the review's 20 hand-extracted estimates
(evaluation/check_estimates_vs_human.py), failing on different studies.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
CONTEXT_ITEMS = 2          # text items before and after a table that travel with it
MAX_TABLE_CHARS = 24000
TABLE_CONCURRENCY = 8
# A call on a table with several labelled rows sometimes stops early. When it returns clearly fewer
# estimates than the table has rows, one more call asks for the rest; the budget bounds the cost per
# document, because a long appendix can hold hundreds of tables.
RETRY_MIN_ROWS = 4
RETRIES_PER_DOC = 12


def _p_value_for(cell, stars: int):
    """The printed p-value, dropped when it contradicts the stars beside the estimate.

    The stars sit with the coefficient, so a p-value in another column that disagrees with them belongs to a
    different test; paper offsets were cleared this way.
    """
    value = parse_number(cell) if cell else None
    limit = {1: 0.10, 2: 0.05, 3: 0.01}.get(stars)
    if value is not None and limit is not None and value > limit + 1e-9:
        return None
    return value


def _outcome_key(estimate: "Estimate") -> str:
    return re.sub(r"[^a-z0-9 ]", " ", str(estimate.outcome or estimate.row_label or "").lower()).strip()


def attach_document_statistics(estimates: List["Estimate"]) -> int:
    """Fill an effect row's control SD and arm counts from the document's descriptive tables.

    An effect table rarely prints the outcome's standard deviation, and a descriptive or balance table never
    prints an effect, so the two are joined by the outcome's name within the document. The match is exact on
    the normalised name, because a loose match could attach one outcome's deviation to another's estimate.
    Returns how many rows were completed.
    """
    sd_by_outcome: Dict[str, float] = {}
    counts_by_outcome: Dict[str, tuple] = {}
    for estimate in estimates:
        key = _outcome_key(estimate)
        if not key:
            continue
        if estimate.control_sd is not None:
            sd_by_outcome.setdefault(key, estimate.control_sd)
        if estimate.n_treatment and estimate.n_control:
            counts_by_outcome.setdefault(key, (estimate.n_treatment, estimate.n_control))
    filled = 0
    for estimate in estimates:
        if estimate.effect_size is None:
            continue
        key = _outcome_key(estimate)
        changed = False
        if estimate.control_sd is None and key in sd_by_outcome:
            estimate.control_sd = sd_by_outcome[key]
            changed = True
        if not (estimate.n_treatment and estimate.n_control) and key in counts_by_outcome:
            estimate.n_treatment, estimate.n_control = counts_by_outcome[key]
            changed = True
        filled += changed
    return filled


def pair_arm_counts(estimates: List["Estimate"]) -> None:
    """Give each estimate both arm counts, when the table supplied them one column at a time.

    A column view holds one arm, so its observation count is one side of the comparison. The two sides are
    joined per page and outcome, which is what the standardised effect needs.
    """
    paired: Dict[tuple, List["Estimate"]] = {}
    for estimate in estimates:
        key = (estimate.page, (estimate.outcome or estimate.row_label).strip().lower())
        paired.setdefault(key, []).append(estimate)
    for rows in paired.values():
        treated = next((row.n_treatment for row in rows if row.n_treatment), None)
        control = next((row.n_control for row in rows if row.n_control), None)
        if treated and control:
            for row in rows:
                row.n_treatment = row.n_treatment or treated
                row.n_control = row.n_control or control


def locate_source_cell(unit_text: str, row_label: str, column_label: str, arm: str) -> str:
    """The printed cell the estimate came from, or "" when the lookup is not unique.

    The row and column are found by the labels the model named, compared on normalised text, and only an
    unambiguous match is accepted. A page can hold several tables and a panel repeats its row labels, so a
    guessed cell would be worse than none: an empty value is reported as unverifiable.
    """
    from src.extraction.table_structure import parse_markdown_table

    grid = parse_markdown_table(unit_text)
    headers = grid.headers[-1] if grid.headers else []

    def pick(label: str):
        options = [(i, _merge_outcome(cell)) for i, cell in enumerate(headers) if str(cell).strip()]
        if not options or not label:
            return None
        exact = [i for i, name in options if name == label]
        if len(exact) == 1:
            return exact[0]
        near = sorted((abs(len(name) - len(label)), i) for i, name in options
                      if name and (name in label or label in name))
        if not near or (len(near) > 1 and near[0][0] == near[1][0]):
            return None
        return near[0][1]

    column = pick(_merge_outcome(column_label)) if column_label else None
    if column is None and arm:
        column = pick(_merge_outcome(arm))
    if column is None:
        return ""
    rows = [row for row in grid.body
            if row and str(row[0]).strip() and row_label and
            (_merge_outcome(row[0]) in row_label or row_label in _merge_outcome(row[0]))]
    if len(rows) != 1 or column >= len(rows[0]):
        return ""
    return str(rows[0][column]).strip()


def locate_cell_position(unit_text: str, estimate_cell: str):
    """Row and column of the printed cell, when the cell's text identifies exactly one place in the table.

    A label repeats across panels and wraps across lines, but the cell's own text usually does not. Matching it
    against the parsed grid gives a position that needs no label, and a repeated text yields nothing rather
    than a guess.
    """
    from src.extraction.table_structure import parse_markdown_table

    target = re.sub(r"\s+", "", str(estimate_cell or "")).lower()
    if not target:
        return None, None
    grid = parse_markdown_table(unit_text)
    hits = [(row_index, column_index)
            for row_index, row in enumerate(grid.body)
            for column_index, cell in enumerate(row)
            if column_index > 0 and re.sub(r"\s+", "", str(cell)).lower() == target]
    return hits[0] if len(hits) == 1 else (None, None)


def _labelled_rows(text: str) -> int:
    """How many data rows the table has, by the count of rows with a label in the first column."""
    from src.extraction.table_structure import parse_markdown_table

    grid = parse_markdown_table(text)
    return sum(1 for row in grid.body if row and str(row[0]).strip())


_ESTIMATE_CELL = re.compile(
    r"^\s*[-−–]?\d[\d,]*(?:\.\d+)?\s*"
    r"(?:[*†‡]+(?:\s*[(\[]\s*[-−–]?\d[\d,]*(?:\.\d+)?\s*[)\]])?"
    r"|[(\[]\s*[-−–]?\d[\d,]*(?:\.\d+)?\s*[)\]])")


def _estimate_cells(text: str) -> int:
    """How many cells in the table look like estimates: a value with stars or a bracketed statistic.

    Counting rows is not enough: a call can return every row and still leave a row's unstarred cell
    out, which is how the non-significant estimates in the tail go missing. Counting cells catches that.
    """
    from src.extraction.table_structure import parse_markdown_table

    grid = parse_markdown_table(text)
    return sum(1 for row in grid.body for cell in row[1:] if _ESTIMATE_CELL.match(str(cell)))


def _has_starred_cell(text: str) -> bool:
    """True when any body cell carries significance stars, which makes the table one of estimates."""
    from src.extraction.table_structure import parse_markdown_table

    grid = parse_markdown_table(text)
    return any(re.search(r"\d[\d,]*\.?\d*\s*[*†‡]", str(cell)) for row in grid.body for cell in row[1:])


def _unique_estimates(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One entry per outcome, arm, subgroup and printed cell, for the two answers to one table."""
    seen, out = set(), []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        key = (str(entry.get("outcome") or "").strip().lower(),
               str(entry.get("arm") or "").strip().lower(),
               str(entry.get("subgroup") or "").strip().lower(),
               str(entry.get("estimate_cell") or "").strip())
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
    return out

PROMPT = """You extract treatment-effect estimates from one table of an impact evaluation.

TEXT AROUND THE TABLE (caption, notes, nearby paragraphs):
{context}

TABLE (Markdown, page {page}):
{table}

INFERRED STRUCTURE (from the headers, notes and arithmetic; may be empty or wrong, and the table itself wins):
{structure}

VIEW: {view}

If the column headers name outcomes (Tot, logTot, Food, Savings) and the first column names
treatment arms (for example TUP*2014), return one estimate for each arm and column, and read the
standard error from the row printed directly beneath that arm in parentheses. Use the arm exactly as
printed, including a year or interaction (TUP*2014 and TUP*2015 are different arms).

If the columns repeat a coefficient, standard error and p-value block per method ("No adjustment -
coef.", "No adjustment - s.e.", "Matching & regression - coef.", ...), return one estimate for each
row and method, with the method as the arm and the standard error from the same block.

If the rows name subgroups ("Gender of child", "Household under 5 members", "Cohort 2", "Old (>65
years)") and the column headers name outcomes ("Farm work", "Total labor hours", "Per capita
consumption"), then the row is the subgroup and the column is the outcome: put the column heading in
outcome and the row label in subgroup. Those are heterogeneity results and they count as estimates.

First decide: does this table report estimated effects of a programme or treatment, such as
regression coefficients, differences between treatment and control (or before and after),
impact estimates or marginal effects? Descriptive statistics, sample descriptions, balance
tests, attrition tables and lists of variables are NOT results tables.

If it is a results table, list every estimate of a treatment effect on an outcome. For each:
- outcome: the outcome as the table names it (row or column label), with units if given
- arm: the treatment or comparison the estimate refers to (e.g. "Full graduation package",
  "TUP vs control", "Endline"); "" if there is only one
- subgroup: the subgroup if the estimate is for one (e.g. "Women", "Bangladesh"); "" otherwise
- row_label and column_label: exactly as printed
- row_number and column_number: where that cell sits in the table shown, counting rows from 1 on the
  first data row and columns from 1 on the first column (the label column is 1). The pipeline opens this
  address to check the cell, so a wrong number is wasted.
- estimate_cell: the cell holding the estimate, copied EXACTLY as printed (keep stars, commas,
  signs and spacing)
- se_cell: the cell holding its standard error, t-statistic or confidence interval, copied
  exactly ("" if none). Often the next row, in parentheses or brackets.
- se_kind: "se", "t", "ci" or "" (from the notes; parentheses are usually SEs)
- p_cell: an exact p-value cell if the table has one, else ""
- n: the number of observations for the estimate if the table gives it, else "". When this view is
  one arm's column and the table prints that column's count in an Observations or N row, return it
- control_mean_cell: the control-group mean for this outcome, copied exactly from a row or column
  headed "Control mean" ("" when the table does not print one)
- control_sd_cell: the control-group standard deviation for this outcome, copied exactly ("" when it
  is not printed). A cell such as "12.4 (3.1)" beside a control mean holds the mean and its SD.
- n_treatment_cell and n_control_cell: the observations for the treatment group and for the control
  group, copied exactly, only when the table prints them separately ("" when it prints one count for
  both). A pooled observation count is not a per-arm count: leave both empty rather than splitting it.

Do not include estimates the table reproduces from OTHER studies (for example a comparison with
earlier evaluations): only this study's own estimates.
Do not include control-group means, constants, covariates or controls, baseline levels,
first-stage coefficients, R-squared or sample sizes as estimates.

Return JSON only:
{{"results_table": true or false, "table_label": "<e.g. Table 3>", "estimates": [ ... ]}}"""


# ----------------------------------------------------------------- number parsing

_STARS = re.compile(r"\*+|†+|‡+")
_NUM = re.compile(r"[-−–]?\s?\d[\d.,]*")


def parse_number(text: str) -> Optional[float]:
    """
    The first number in `text`, reading separators as a person would:
    "4,408" is 4408 (thousands), "0,84" is 0.84 (decimal comma), "1.234,5" is 1234.5,
    "−0.18***" is -0.18. Returns None when there is no number.
    """
    if text is None:
        return None
    s = _STARS.sub("", str(text)).replace("−", "-").replace("–", "-")
    m = _NUM.search(s)
    if not m:
        return None
    tok = m.group(0).replace(" ", "")
    neg = tok.startswith("-")
    tok = tok.lstrip("-").rstrip(".,")
    if "," in tok and "." in tok:
        # whichever comes last is the decimal mark
        if tok.rfind(",") > tok.rfind("."):
            tok = tok.replace(".", "").replace(",", ".")
        else:
            tok = tok.replace(",", "")
    elif "," in tok:
        head, _, tail = tok.rpartition(",")
        groups = tok.split(",")
        thousands = (len(tail) == 3 and head not in ("0", "") and all(len(g) == 3 for g in groups[1:])
                     and 1 <= len(groups[0]) <= 3)
        tok = tok.replace(",", "") if thousands else tok.replace(",", ".", 1).replace(",", "")
    elif tok.count(".") > 1:
        # "1.234.567" thousands with dots
        tok = tok.replace(".", "")
    try:
        value = float(tok)
    except ValueError:
        return None
    return -value if neg else value


def count_stars(text: str) -> int:
    m = re.search(r"\*+", str(text or ""))
    return len(m.group(0)) if m else 0


def parse_interval(text: str) -> Optional[tuple]:
    nums = [parse_number(x) for x in re.findall(r"[-−–]?\d[\d.,]*", str(text or ""))]
    nums = [n for n in nums if n is not None]
    return (nums[0], nums[1]) if len(nums) >= 2 else None


# ------------------------------------------------------------------- extraction


@dataclass
class Estimate:
    table_label: str
    page: Optional[int]
    table_index: Optional[int]
    outcome: str
    arm: str
    subgroup: str
    row_label: str
    column_label: str
    estimate_cell: str
    se_cell: str
    se_kind: str
    p_cell: str
    effect_size: Optional[float]
    standard_error: Optional[float]
    t_stat: Optional[float]
    ci_low: Optional[float]
    ci_high: Optional[float]
    p_value: Optional[float]
    stars: int
    sample_size: Optional[int]
    control_mean: Optional[float]
    control_sd: Optional[float]
    n_treatment: Optional[int]
    n_control: Optional[int]
    grounded: bool
    source_cell: str = ""
    cell_row: Optional[int] = None
    cell_column: Optional[int] = None
    unit_index: Optional[int] = None
    notes: List[str] = field(default_factory=list)


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", str(s or "")).replace("−", "-").replace("–", "-")


def _number_in_parens(cell: str) -> Optional[float]:
    match = re.search(r"[(\[]\s*(-?[\d.,]+)\s*[)\]]", str(cell or ""))
    return parse_number(match.group(1)) if match else None


def _count(value: Optional[float]) -> Optional[int]:
    return int(value) if value is not None and value > 0 and value == int(value) else None


def to_estimate(raw: Dict[str, Any], table_label: str, page: Optional[int], table_text: str,
                arm_hint: str = "", n_hint: Optional[float] = None,
                control_n: Optional[float] = None, arm_row: str = "",
                table_index: Optional[int] = None, unit_index: Optional[int] = None) -> Estimate:
    est_cell = str(raw.get("estimate_cell") or "")
    # The address the model gave is accepted only when that cell actually holds the reported coefficient.
    cell_row = cell_column = None
    try:
        row_number = int(float(raw.get("row_number")))
        column_number = int(float(raw.get("column_number")))
    except (TypeError, ValueError):
        row_number = column_number = None
    if row_number and column_number:
        from src.extraction.table_structure import parse_markdown_table

        grid = parse_markdown_table(table_text)
        if 1 <= row_number <= len(grid.body) and 1 <= column_number <= len(grid.body[row_number - 1]):
            printed = str(grid.body[row_number - 1][column_number - 1])
            # Match the token the model reported, sign included, so a dropped minus cannot pass and a cell
            # holding two numbers gives the one the model meant rather than the first.
            digits = re.sub(r"\D", "", est_cell)
            negative = est_cell.strip().startswith(("-", "\u2212", "\u2013"))
            same_digits = [token for token in re.findall(r"[-−–]?\d[\d.,]*", printed)
                           if digits and re.sub(r"\D", "", token) == digits]
            # The printed token wins on the sign too: a copy that dropped a minus is a copy error, and the
            # cell itself is the evidence.
            matched = next((token for token in same_digits
                            if token.startswith(("-", "\u2212", "\u2013")) == negative),
                           same_digits[0] if same_digits else None)
            if matched:
                cell_row, cell_column = row_number - 1, column_number - 1
                # The printed token is the authority for the value: the copy can lose a sign or a digit.
                est_cell = matched
    se_cell = str(raw.get("se_cell") or "")
    kind = str(raw.get("se_kind") or "").lower()
    if not kind and se_cell:
        kind = "ci" if "," in se_cell.strip("()[]") and parse_interval(se_cell) and "[" in se_cell else "se"
    se = t = lo = hi = None
    if kind == "ci":
        iv = parse_interval(se_cell)
        lo, hi = iv if iv else (None, None)
    elif kind == "t":
        t = parse_number(se_cell)
    elif se_cell:
        se = parse_number(se_cell)
        se = abs(se) if se is not None else None
    # A zero standard error is a printing artefact or a misread cell, and it would imply infinite precision.
    if se is not None and se == 0:
        se = None
    estimate_value = parse_number(est_cell)
    if kind == "t" and t:
        # t = estimate / se by definition, so a printed t gives the standard error exactly. The tolerance is
        # arithmetic, not an estimate, and it is only taken when both numbers are present.
        if estimate_value not in (None, 0):
            se = abs(estimate_value / t)
    # An interval that does not contain its own estimate was misread or belongs to another row; the
    # estimate is the printed cell beside it, so the interval is dropped rather than stored as a bracket.
    if lo is not None and hi is not None and estimate_value is not None:
        if not (min(lo, hi) <= estimate_value <= max(lo, hi)):
            lo = hi = None
    n = parse_number(raw.get("n"))
    if n is None and n_hint:
        n = float(n_hint)
    table_norm = _norm(table_text)

    def _tokens(text: object) -> List[str]:
        # Whitespace-delimited tokens that keep decimal points, so numbers compare as printed:
        # "2,540.00" becomes ["2", "540.00"] on both sides.
        return re.sub(r"[^a-z0-9.]+", " ", str(text or "").lower()).split()

    table_tokens = _tokens(table_text)

    def found(cell: str) -> bool:
        """A control statistic counts only when its cell is in the table, as the estimate does.

        Substring matching is unsafe here: a one-character count such as "1" appears inside almost any
        table. The cell has to appear as the same run of tokens, and be at least two characters long.
        """
        needle = _tokens(cell)
        if not needle or len(_norm(cell)) < 2:
            return False
        return any(table_tokens[i:i + len(needle)] == needle
                   for i in range(len(table_tokens) - len(needle) + 1))

    cm_cell = str(raw.get("control_mean_cell") or "")
    sd_cell = str(raw.get("control_sd_cell") or "")
    nt_cell = str(raw.get("n_treatment_cell") or "")
    nc_cell = str(raw.get("n_control_cell") or "")
    # The mean is the leading number of "mean (sd)"; the SD is the parenthesised one.
    control_mean = parse_number(cm_cell) if found(cm_cell) else None
    control_sd = (_number_in_parens(sd_cell) or parse_number(sd_cell)) if found(sd_cell) else None
    n_treatment = _count(parse_number(nt_cell)) if found(nt_cell) else None
    n_control = _count(parse_number(nc_cell)) if found(nc_cell) else None
    if n_treatment is None and n_control is None and n_hint and arm_hint:
        # The view is one arm's column and the table prints that column's observation count, so the count
        # belongs to this arm. The control side is named, because a treated arm is anything else.
        if re.search(r"control|comparison|placebo|untreated|non-?beneficiar|\bnsup\b", arm_hint.lower()):
            n_control = _count(float(n_hint))
        else:
            n_treatment = _count(float(n_hint))
    if n_control is None and control_n:
        n_control = _count(float(control_n))

    grounded = bool(est_cell) and _norm(est_cell) in table_norm and (not se_cell or _norm(se_cell) in table_norm)
    notes = [] if grounded else ["cell not found verbatim in the table"]
    return Estimate(
        table_label=table_label, page=page, table_index=table_index,
        outcome=str(raw.get("outcome") or ""),
        arm=arm_row or str(raw.get("arm") or "") or arm_hint, subgroup=str(raw.get("subgroup") or ""),
        row_label=str(raw.get("row_label") or ""), column_label=str(raw.get("column_label") or "") or arm_hint,
        estimate_cell=est_cell, se_cell=se_cell, se_kind=kind, p_cell=str(raw.get("p_cell") or ""),
        effect_size=parse_number(est_cell), standard_error=se, t_stat=t, ci_low=lo, ci_high=hi,
        p_value=_p_value_for(raw.get("p_cell"), count_stars(est_cell)),
        stars=count_stars(est_cell), sample_size=int(n) if n is not None and n.is_integer() and n > 0 else None,
        control_mean=control_mean, control_sd=control_sd, n_treatment=n_treatment, n_control=n_control,
        grounded=grounded, notes=notes,
        cell_row=cell_row, cell_column=cell_column, unit_index=unit_index,
    )


def _included_table(item: Dict[str, Any]) -> bool:
    """A table the reader actually reads: a table, with a pipe grid, that is not garbled."""
    from src.extraction.table_rules import looks_garbled

    if item.get("type") != "table":
        return False
    text = str(item.get("text") or item.get("table_body") or "")
    return "|" in text and not looks_garbled(text)


def table_units(content_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Each table with its page, caption and the text items just before and after it."""
    from src.extraction.table_rules import looks_garbled
    from src.extraction.table_structure import (
        arm_row_label,
        carry_merged_labels,
        control_count,
        parse_markdown_table,
        split_estimate_columns,
    )

    units = []
    for i, item in enumerate(content_list):
        if item.get("type") != "table":
            continue
        text = str(item.get("text") or item.get("table_body") or "")
        if "|" not in text or looks_garbled(text):
            # A garbled table has a broken font mapping; the page image is read instead.
            continue
        # A merged label leaves the following rows without an outcome name; carry it down first.
        text = carry_merged_labels(text)
        around = []
        for j in list(range(max(0, i - CONTEXT_ITEMS), i)) + list(range(i + 1, min(len(content_list), i + 1 + CONTEXT_ITEMS))):
            other = content_list[j]
            if other.get("type") != "table":
                around.append(str(other.get("text") or "")[:1500])
        caption = item.get("table_caption")
        if isinstance(caption, (list, tuple)):
            caption = " ".join(str(c) for c in caption)
        if isinstance(caption, str) and caption.startswith("["):
            try:
                caption = " ".join(json.loads(caption.replace("'", '"')))
            except ValueError:
                pass
        try:
            # Docling's page_idx counts from 0; pages shown to users count from 1, as chunks do
            page = int(item.get("page_idx")) + 1 if item.get("page_idx") not in (None, "") else None
        except (TypeError, ValueError):
            page = None
        page_table_index = sum(1 for earlier in content_list[:i]
                               if _included_table(earlier)
                               and (earlier.get("page_idx") or 0) == (item.get("page_idx") or 0))
        base = {"index": i, "page": page, "table_index": page_table_index,
                "caption": caption or "", "text": text[:MAX_TABLE_CHARS],
                "context": "\n".join(x for x in around if x.strip()), "arm_hint": "",
                "control_n": control_count(parse_markdown_table(text)),
                "arm_row": arm_row_label(parse_markdown_table(text)) or ""}
        # A wide table comes back as one narrow table per estimate column: the model reads the first
        # column across a seven-column row and stops, and the column header is the arm it belongs to.
        columns = split_estimate_columns(text[:MAX_TABLE_CHARS])
        if columns:
            for column in columns:
                units.append({**base, "text": column["text"][:MAX_TABLE_CHARS], "arm_hint": column["header"],
                              "n_hint": column.get("n_hint"),
                              "caption": f"{base['caption']} (column: {column['header']})".strip()})
            # The whole-table read runs too and its rows merge with the column views. A narrow view
            # can lose a standard error the wide read saw, and the wide read is what the pipeline did
            # before, so keeping both makes the change additive.
            units.append({**base, "whole_of_views": True})
            continue
        units.append(base)
    # The view's identity in the reader's order, so a stored cell address can be opened again later.
    for position, unit in enumerate(units):
        unit["unit_index"] = position
    return units


_OUTCOME_PREFIX = re.compile(r"^\s*(?:\(\d+\)|\d+[.)]|panel\s+[a-z][:.]?|table\s+\d+[:.]?)\s*", re.I)


def _merge_outcome(text: object) -> str:
    """The outcome with its leading column marker removed, for comparing two reads of one table.

    A column view may call the same row "(1) Indicator if household owns sheep" and the whole-table read
    "Indicator if household owns sheep"; without this the merge stores the coefficient twice.
    """
    value = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    # A label wrapped at a hyphen comes back as "diversifica- tion"; joining it makes the two reads one.
    value = re.sub(r"(?<=[a-z])-\s+(?=[a-z])", "", value)
    previous = None
    while previous != value:
        previous = value
        value = _OUTCOME_PREFIX.sub("", value).strip()
    return value


def merge_reads(rows: List["Estimate"]) -> List["Estimate"]:
    """One row per (outcome, estimate) across the reads of one table.

    A wide table is read whole and column by column. The reads overlap, so this keeps one row per
    outcome and estimate value, fills a standard error seen in either read, and keeps the arm from
    whichever read named it.
    """
    best: Dict[tuple, "Estimate"] = {}
    order: List[tuple] = []
    for row in rows:
        key = (_merge_outcome(row.outcome or row.row_label), row.effect_size)
        current = best.get(key)
        if current is None:
            best[key] = row
            order.append(key)
            continue
        if current.standard_error is None and row.standard_error is not None:
            current.standard_error, current.se_cell = row.standard_error, row.se_cell
        if not current.arm and row.arm:
            current.arm = row.arm
    return [best[key] for key in order]


async def _chat(client: httpx.AsyncClient, model: str, prompt: str) -> str:
    body = {"model": model, "temperature": 0, "max_tokens": 16000,
            "reasoning": {"effort": "low", "exclude": True},
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": prompt}]}
    for attempt in range(3):
        try:
            r = await client.post(OPENROUTER_URL, json=body)
            if r.status_code >= 500 or r.status_code == 429:
                raise httpx.HTTPStatusError("retryable", request=r.request, response=r)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"] or ""
        except (httpx.HTTPError, KeyError):
            if attempt == 2:
                raise
            await asyncio.sleep(2 * (attempt + 1))
    return ""


def _parse_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0) if m else text)


def _table_analysis(u: Dict[str, Any]):
    """Table type and inferred structure, computed before the model call (lazy imports avoid a cycle)."""
    from src.extraction.table_rules import classify_table
    from src.extraction.table_structure import (
        ESTIMATE,
        LAYOUT_ROWS,
        interpret_table,
        parse_markdown_table,
    )

    grid = parse_markdown_table(u["text"])
    header = " | ".join(grid.headers[-1]) if grid.headers else ""
    kind, _ = classify_table(u.get("caption") or "", " ".join(grid.notes), header)
    result = interpret_table(u["text"], notes=f"{u.get('caption') or ''}\n{u.get('context') or ''}".strip())
    has_estimate = (ESTIMATE in result.row_roles) if result.layout == LAYOUT_ROWS else (result.estimate is not None)
    return kind, result, has_estimate


def _structure_hint(result, text: str = "") -> str:
    """A short description of the inferred columns, for the model prompt."""
    from src.extraction.table_structure import (
        LAYOUT_ROWS,
        parse_markdown_table,
        subgroup_rows_layout,
    )

    parts: List[str] = []
    if text:
        grid = parse_markdown_table(text)
        if subgroup_rows_layout(grid):
            headers = grid.headers[-1] if grid.headers else []
            names = ", ".join(str(cell) for cell in headers[1:4] if str(cell).strip())
            parts.append("the rows are subgroups and the columns are outcomes (" + names + "); put the "
                         "column heading in outcome, the row label in subgroup, and do not treat the row as "
                         "the outcome")
    if result.stat_blocks:
        parts.append("the columns repeat in method blocks (" + ", ".join(result.stat_blocks[:5])
                     + "); for each row and method, return the coefficient and read its standard "
                       "error from the adjacent column in the same block; use the method name as the arm")
    if result.outcome_columns:
        parts.append("the column headers are outcomes (" + ", ".join(result.outcome_columns[:6])
                     + "); each row is a treatment arm and the row printed beneath it holds that "
                       "arm's standard errors in parentheses; keep the arm exactly as printed, "
                       "including any year or interaction")
    if result.layout == LAYOUT_ROWS:
        parts.append("statistics are in rows and outcomes or models are in the columns")
    for index, name in ((result.estimate, "estimate"), (result.se, "standard error"),
                        (result.t, "t or z statistic"), (result.p, "p-value"),
                        (result.ci_low, "confidence interval lower end"),
                        (result.ci_high, "confidence interval upper end")):
        if index is not None and index < len(result.roles):
            header = result.roles[index].header or f"column {index + 1}"
            parts.append(f"{name} is the column headed '{header}'")
    if result.combined:
        parts.append("each cell holds the estimate with its standard error in parentheses")
    if result.conventions.get("se_in_parens"):
        parts.append("the notes say standard errors are in parentheses")
    if result.stars_map:
        parts.append("the notes give a significance-star map")
    return "; ".join(parts)


def _should_skip(kind: str, has_estimate: bool) -> bool:
    """A descriptive table with no estimate inferred is not worth a model call."""
    from src.extraction.table_rules import DESCRIPTIVE

    return kind == DESCRIPTIVE and not has_estimate


def _drop_non_outcome_rows(raw: List[Any]):
    """Remove rows whose label is not an outcome (Observations, R2, Constant, Controls, ...)."""
    from src.extraction.table_rules import is_non_outcome_label

    kept, dropped = [], 0
    for row in raw:
        if isinstance(row, dict) and is_non_outcome_label(str(row.get("outcome") or "")):
            dropped += 1
        else:
            kept.append(row)
    return kept, dropped


async def extract_document(content_list: List[Dict[str, Any]], model: str, api_key: str,
                           drop_duplicates: bool = False) -> Dict[str, Any]:
    """All estimates in a document's tables, plus per-table decisions for auditing.

    `drop_duplicates` is off by default: on the extracted rows so far the merge rule finds nothing,
    so a repeated row is far more likely to be the reader emitting the same line twice than a repeat
    in the paper, and keeping it loses no real estimate.
    """
    from src.extraction.dedupe import dedupe_estimates
    from src.extraction.table_rules import DESCRIPTIVE

    units = table_units(content_list)
    sem = asyncio.Semaphore(TABLE_CONCURRENCY)
    retry_budget = {"left": RETRIES_PER_DOC}
    async with httpx.AsyncClient(timeout=300, headers={"Authorization": f"Bearer {api_key}"}) as client:
        async def one(u):
            kind, result, has_estimate = _table_analysis(u)
            if _should_skip(kind, has_estimate):
                return u, {"skipped": "descriptive table", "estimates": []}, None, kind
            structure = _structure_hint(result, u["text"])
            view = ("one estimate column, whose header is the arm it belongs to: "
                    f"'{u['arm_hint']}'. Return one entry for every outcome row in this view, with "
                    "that header as the arm, including a row whose cell carries no stars.") if u.get("arm_hint") \
                else "the whole table"
            prompt = PROMPT.format(context=(u["caption"] + "\n" + u["context"]).strip()[:4000] or "(none)",
                                   table=u["text"], page=u["page"] if u["page"] is not None else "?",
                                   structure=structure or "(none)", view=view)
            async with sem:
                for attempt in range(2):
                    try:
                        data = _parse_json(await _chat(client, model, prompt))
                        expected = max(_labelled_rows(u["text"]), _estimate_cells(u["text"]))
                        got = len(data.get("estimates") or [])
                        must_read_as_results = (not data.get("results_table")
                                                and expected >= RETRY_MIN_ROWS
                                                and _has_starred_cell(u["text"]))
                        incomplete = (data.get("results_table") and expected >= RETRY_MIN_ROWS
                                      and got < expected)
                        if (must_read_as_results or incomplete) and retry_budget["left"] > 0:
                            # Ask once more, either because the answer stopped short of the rows or because the
                            # structure says results and the model said it was not a results table.
                            retry_budget["left"] -= 1
                            ask = (f"\n\nCOMPLETENESS: you returned {got} of about {expected} data rows. "
                                   "Return every row in the table, including rows whose cell carries no stars "
                                   "and rows whose estimate is small, and do not stop early.")
                            if must_read_as_results:
                                ask = ("\n\nThis table reports estimated effects: its caption, labels and "
                                       "arithmetic say so. Set results_table true and return every row, "
                                       "including rows whose cell carries no stars.")
                            more = _parse_json(await _chat(client, model, prompt + ask))
                            merged = _unique_estimates((data.get("estimates") or []) + (more.get("estimates") or []))
                            data = {**data, "results_table": True, "estimates": merged, "completed": True}
                        return u, data, None, kind
                    except Exception as e:
                        err = f"{type(e).__name__}: {e}"[:200]
                return u, {}, err, kind

        results = await asyncio.gather(*(one(u) for u in units))

    estimates, tables = [], []
    per_item: Dict[int, List[Estimate]] = {}
    views_of: Dict[int, int] = {}
    for u, data, err, kind in results:
        label = str(data.get("table_label") or u["caption"][:40] or f"table at item {u['index']}")
        if u.get("arm_hint"):
            views_of[u["index"]] = views_of.get(u["index"], 0) + 1
        is_results = bool(data.get("results_table"))
        raw = (data.get("estimates") or []) if is_results else []
        raw, non_outcome = _drop_non_outcome_rows(raw)
        rows = [to_estimate(r, label, u["page"], u["text"], u.get("arm_hint") or "", u.get("n_hint"), u.get("control_n"),
                        u.get("arm_row") or "", u.get("table_index"), u.get("unit_index"))
                for r in raw if isinstance(r, dict)]
        for estimate in rows:
            estimate.source_cell = locate_source_cell(u["text"], _merge_outcome(estimate.row_label),
                                                       _merge_outcome(estimate.column_label),
                                                       _merge_outcome(estimate.arm))
            if estimate.cell_row is None:
                estimate.cell_row, estimate.cell_column = locate_cell_position(u["text"], estimate.estimate_cell)
        per_item.setdefault(u["index"], []).extend(rows)
        tables.append({"table": label, "page": u["page"], "results_table": is_results, "estimates": len(rows),
                       "grounded": sum(r.grounded for r in rows), "error": err,
                       "skipped": data.get("skipped"),
                       "non_outcome_rows": non_outcome,
                       "review": kind == DESCRIPTIVE and is_results})
    # A wide table read both ways is merged, so the column views add coverage without repeating rows.
    for index, rows in per_item.items():
        estimates.extend(merge_reads(rows) if views_of.get(index) else rows)
    pair_arm_counts(estimates)
    attach_document_statistics(estimates)
    estimate_dicts = [asdict(e) for e in estimates]
    duplicates = 0
    if drop_duplicates:
        estimate_dicts, duplicates = dedupe_estimates(estimate_dicts)
    return {"estimates": estimate_dicts, "tables": tables, "duplicates": duplicates}
