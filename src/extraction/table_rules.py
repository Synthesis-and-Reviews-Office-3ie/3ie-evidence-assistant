"""
Table-type and non-outcome rules, ported from the TVET pipeline.

Two problems make a results table hard to read, and both were already solved once in TVET
(`pipelines/TVET/pipeline/`, outside this repo):

1. Telling a results table from a descriptive one. A balance table, a summary of baseline
   characteristics or an attrition table looks like a results table: it has rows and numbers. But
   its numbers are means, differences or balance-test statistics, not treatment effects. TVET's
   `prompts/phase2_table_filtering.txt` names the distinction, and `validation_rules.py` flags
   balance, matching and propensity tables.
2. Rows and columns that are not outcomes. "Observations", "R²", "Constant", a list of controls, or
   a column of means and standard deviations sit inside real results tables but are not estimates.
   TVET's `validation_rules.py` (`observations_check`, `goodness_of_fit_check`, `controls_check`,
   `covariate_check`, `column_label_check`) excludes them by pattern.

This module ports those ideas as pure functions: no model, no config file, no I/O. Patterns are
listed here so they are visible and testable. Provenance: TVET phase 2 and `validation_rules.yaml`.
"""

from __future__ import annotations

import re
import unicodedata

RESULTS = "results"
DESCRIPTIVE = "descriptive"
UNKNOWN = "unknown"

# Caption, section and note cues. A descriptive cue wins, because a balance table named
# "Baseline characteristics and impacts" is still a balance table.
_DESCRIPTIVE_CUES = (
    "balance", "baseline", "baseline characteristics", "summary statistics", "descriptive",
    "demographics", "sample characteristics", "attrition", "covariate", "covariates",
    "pre-treatment", "pretreatment", "randomization check", "randomisation check", "first stage",
    "falsification", "placebo", "take-up only", "compliance rates", "summary of sample",
)
# Cues strong enough to decide the table type from the caption alone.
_STRONG_DESCRIPTIVE = (
    "balance", "attrition", "summary statistics", "baseline characteristics", "sample characteristics",
    "descriptive statistics", "demographics", "pre-treatment", "pretreatment", "baseline table",
)
_RESULTS_CUES = (
    "impact", "effect", "treatment effect", "effects of", "regression", "coefficient", "estimates",
    "estimation results", "main results", "itt", "att", "ate", "difference-in-difference",
    "double difference", "differences-in-differences", "results",
)
# Row labels that appear in results tables but are not outcomes.
_NON_OUTCOME = (
    "observations", "number of observations", "n obs", "nobs", "r-squared", "r squared", "r2",
    "adjusted r", "constant", "intercept", "controls", "control variables", "covariates",
    "fixed effects", "f-statistic", "f stat", "p-value", "p value", "standard deviation",
    "clusters", "number of clusters",
)
_NON_OUTCOME_EXACT = {"n", "obs", "sd", "se", "r2", "r²"}
# Font-mapping failures leave runs like "?????? a114 a116" where letters should be.
_GARBLE_ARTIFACT = re.compile(r"[a-z]\d{2,3}")


def looks_garbled(text: object, min_chars: int = 40) -> bool:
    """True when the parser's text is a broken font mapping rather than words.

    Paper 121328483 is the example: its tables come through as "????? ?? ???????a114 a116a115",
    which no text reader can interpret. Such a table should be skipped by the text path and read
    from the page image instead.
    """
    value = str(text or "")
    if len(value) < min_chars:
        return False
    return value.count("?") / len(value) > 0.03 or len(_GARBLE_ARTIFACT.findall(value)) >= 8


def is_pipe_table(text: object, min_rows: int = 2) -> bool:
    """True when the text is a Markdown pipe table rather than a sentence.

    Docling returns some of the largest layout tables as ordinary text, so the table reader never
    sees them: paper 121328483 has its two-year and three-year results tables on pages 18 to 20 typed
    as `text`. Two rows of pipes (a header row and a separator row) are enough to tell a table from
    prose.
    """
    return sum(1 for line in str(text or "").splitlines() if line.count("|") >= 2) >= min_rows


def reclassify_pipe_tables(content_list: list) -> list:
    """A copy of the content list with text items that are Markdown pipe tables typed as tables.

    A repaired page (a transcription written over a garbled table) is left as text on purpose: the
    numbers on that page are read from the page image, and reading its transcription as well would
    store every estimate on the page twice.
    """
    out = []
    for item in content_list:
        if item.get("type") == "text" and not item.get("repaired") and is_pipe_table(item.get("text")):
            item = {**item, "type": "table", "reclassified": True}
        out.append(item)
    return out


def _fold(text: object) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(text or "")) if not unicodedata.combining(c))


def _norm(text: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _fold(text).lower()).strip()


def _cue(text: str, cue: str) -> bool:
    return bool(re.search(rf"\b{re.escape(cue)}(?:s|es)?\b", text))


# Cues and labels are matched in the same normalised form, so "f-statistic" is matched as
# "f statistic" and a hyphen in the printed label does not hide it.
_NON_OUTCOME_CUES = tuple(_norm(c) for c in _NON_OUTCOME)


def classify_table(caption: str = "", notes: str = "", header: str = "") -> tuple[str, str]:
    """`results`, `descriptive` or `unknown`, from the caption and the table notes.

    The header is deliberately not used. A results table often carries a "Baseline" column, and
    reading that as a balance table skipped paper 121330141's difference-in-difference results. The
    caption decides first; the notes decide only when the caption is silent.
    """
    cap = _norm(caption)
    note = _norm(notes)
    if not cap and not note:
        return UNKNOWN, "no caption or notes"
    for cue in _STRONG_DESCRIPTIVE:
        if _cue(cap, cue):
            return DESCRIPTIVE, f"descriptive cue '{cue}' in the caption"
    for cue in _RESULTS_CUES:
        if _cue(cap, cue):
            return RESULTS, f"results cue '{cue}' in the caption"
    for cue in _DESCRIPTIVE_CUES:
        if _cue(cap, cue) or _cue(note, cue):
            return DESCRIPTIVE, f"descriptive cue '{cue}'"
    for cue in _RESULTS_CUES:
        if _cue(cap, cue) or _cue(note, cue):
            return RESULTS, f"results cue '{cue}'"
    return UNKNOWN, "no cue"


def is_non_outcome_label(label: str) -> bool:
    """True for a row label that sits in a results table but is not an outcome."""
    text = str(label or "")
    # A units or vintage note in parentheses is not the label: "Per capita income (BDT constant
    # price)" reports an outcome even though "constant" signals a constant term. A label that is
    # nothing but a parenthetical is kept as printed.
    core = re.sub(r"\([^)]*\)", " ", text).strip() or text
    key = _norm(core)
    if not key:
        return False
    if key in _NON_OUTCOME_EXACT:
        return True
    # "Average effect of T1" is an effect, not a control mean; "Mean in pure control" is a mean.
    if re.search(r"\b(mean|average|avg)\b.*\b(effect|impact)\b", key):
        return False
    # A bare mean or average, or one qualified as the control or baseline group, is a summary statistic.
    # An outcome can begin with the word, though: paper 121354848's livestock table reports "Average price"
    # and "Average price (animals sold)", which are outcomes and were being dropped for the cue "average".
    if re.fullmatch(r"(mean|average|avg)(\s*\([^)]*\))?", key):
        return True
    if re.search(r"\b(control|baseline|comparison|treatment)\s+(mean|average)\b", key):
        return True
    if re.search(r"\b(mean|average|avg)\b\s+(in|of|for)\s+(the\s+)?(pure\s+)?(control|comparison)", key):
        return True
    if re.fullmatch(r"(mean|average|avg)\s+(of\s+)?(the\s+)?controls?\b.*", key):
        return True
    # "Prob > F" is a p-value; "probability of employment" is an outcome, so prob is matched exactly.
    if key == "prob" or key.startswith("prob ") or "prob >" in key:
        return True
    return any(_cue(key, cue) for cue in _NON_OUTCOME_CUES)


def is_descriptive_column(header: str) -> bool:
    """True for a column of means or standard deviations, which are not estimates."""
    key = _norm(header)
    return bool(re.search(r"\b(mean|average|sd|std dev|standard deviation)\b", key))


def html_table_to_markdown(html: str) -> str:
    """A GitHub Markdown pipe table from an HTML table, preserving the cell text.

    MinerU returns a table as HTML in ``table_body`` while Docling returns Markdown in
    ``text``. The estimate reader, the chunker and the vision gate all key on pipe
    tables, so an HTML table is rendered here rather than silently skipped.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(str(html or ""), "html.parser")
    table = soup.find("table") or soup
    rows = []
    for tr in table.find_all("tr"):
        cells = []
        for cell in tr.find_all(["th", "td"]):
            text = " ".join(cell.get_text(" ", strip=True).split()).replace("|", "\\|")
            cells.append(text)
            try:
                span = int(cell.get("colspan") or 1)
            except (TypeError, ValueError):
                span = 1
            cells.extend([""] * max(0, span - 1))
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    header, body = rows[0], rows[1:]
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * width) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in body]
    return "\n".join(lines)


def normalise_tables(content_list: list) -> list:
    """A copy of the content list with HTML ``table_body`` values rendered as Markdown.

    Items that already carry Markdown text, as Docling's do, are left untouched, so this
    is safe to apply to any parser's output.
    """
    out = []
    for item in content_list:
        if item.get("type") == "table" and not str(item.get("text") or "").strip():
            body = str(item.get("table_body") or "")
            if "<table" in body.lower():
                item = {**item, "text": html_table_to_markdown(body)}
        out.append(item)
    return out
