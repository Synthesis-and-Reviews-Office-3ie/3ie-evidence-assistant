"""When a stored arm repeats the column header or the outcome, take it from the row label or panel.

A row classified as a treatment or regressor carries the arm. A subgroup row does not: the subgroup is
not an arm, so the arm is left for the separate method and subgroup fields.
"""
import re

# A row that names a treatment, a regressor or a period. Subgroup words such as "Industry" or "Traditional"
# are deliberately absent, because a subgroup is not an arm.
ROLE = re.compile(
    r"^\s*(treatment|treated|programme|program|intervention|arm|full|half|t\d+|sup|nsup|"
    r"received|intensive|extension|phase|one year|year\s*\d|waves?\b|round\b|follow[- ]?up|baseline|"
    r"spillover|itt|control|untreated|placebo|comparison|\b(19|20)\d{2}\b)", re.I)
PANEL = re.compile(r"panel\s+([a-z0-9]+)", re.I)


def _norm(text) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def is_role(label) -> bool:
    return bool(ROLE.match(str(label or "")))


def fixed_arm(outcome, arm, row_label, column_header, panel="") -> str:
    """The arm to store: the row label when the arm merely repeats the header or the outcome.

    When the outcome is already the row label the layout swap is the missing fix, not the arm, so the arm
    is left alone rather than copied into a second row-label field.
    """
    if not _norm(arm) or not (_norm(arm) == _norm(column_header) or _norm(arm) == _norm(outcome)):
        return arm
    if _norm(outcome) == _norm(row_label):
        return arm
    if is_role(row_label):
        return str(row_label).strip()
    if panel:
        return str(panel).strip()
    return arm
