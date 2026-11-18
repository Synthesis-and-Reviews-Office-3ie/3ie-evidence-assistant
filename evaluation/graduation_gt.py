"""Ground truth and study-to-document mapping for the poverty graduation evaluation.

The key is ``data/8WR QEX Combined.xlsx`` (Sheet1): 43 studies and 442 outcome rows, with
the hand-typed estimate and standard error in ``Coeff reg`` and ``SE reg``. A study's
document is resolved by study id in the filename, with two written-down overrides in
``study_documents.json`` for papers named by author, and deterministic handling of
appendix, brief and translation duplicates. All 43 studies resolve to 43 distinct
documents on the graduation collection.
"""

from __future__ import annotations

import json
from pathlib import Path

PROJECT_ID = "7efdc60e-e863-480c-929e-616574725e5f"
EVAL_DIR = Path(__file__).resolve().parent
KEY_PATH = EVAL_DIR.parent / "data" / "8WR QEX Combined.xlsx"
OVERRIDES = EVAL_DIR / "study_documents.json"

# A study id can match a paper, its appendix, a policy brief or a translation. Only the
# paper's own results are scored, so these are dropped before the paper is chosen.
EXCLUDED_TAGS = ("appendix", "_app.", "_app_", "_app ", "policy_brief", "brief", "supplement")


def pick_document(study_id, hits, all_names, overrides):
    """Choose exactly one document for a study. Returns ``(document or None, reason)``."""
    candidates = [d.replace(".pdf", "") for d in overrides.get(study_id, {}).get("documents", [])]
    if candidates:
        matched = [n for n in all_names if any(c in n for c in candidates)]
        if len(matched) == 1:
            return matched[0], "override"

    mains = [n for n in hits if not any(tag in n.lower() for tag in EXCLUDED_TAGS)]
    if len(mains) == 1:
        return mains[0], "single-main"

    english = [n for n in mains if "english" in n.lower()]
    if len(english) == 1:
        return english[0], "english"

    if len(mains) > 1:
        return sorted(mains)[0], "ambiguous"
    if len(hits) == 1:
        return hits[0], "only-appendix"
    return None, "unmapped"


def load_overrides(path=None):
    source = Path(path) if path else OVERRIDES
    return json.loads(source.read_text(encoding="utf-8")) if source.exists() else {}


def study_to_document(names, overrides=None):
    """Map each ground-truth study to one document, keyed by study id."""
    overrides = overrides if overrides is not None else load_overrides()
    mapping = {}
    for study_id in ground_truth_studies():
        hits = [n for n in names if study_id in n]
        mapping[study_id], _ = pick_document(study_id, hits, names, overrides)
    return mapping


def ground_truth_studies(path=None):
    """The study ids present in the key."""
    return sorted(load_key(path)["sid"].unique())


def load_key(path=None):
    """The key sheet with a normalised string ``sid`` column."""
    import pandas as pd

    source = Path(path) if path else KEY_PATH
    key = pd.ExcelFile(source).parse("Sheet1")
    key.columns = [str(c).replace("\xa0", " ").strip() for c in key.columns]
    key = key[key["StudyID"].notna()].copy()
    key["sid"] = key["StudyID"].astype(float).astype(int).astype(str)
    return key
