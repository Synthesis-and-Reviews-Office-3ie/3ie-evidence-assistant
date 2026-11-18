"""Tests for the study-to-document rule used by the parser-union evaluation."""

from evaluation.graduation_gt import pick_document


def test_single_paper():
    names = ["abc_121000001.pdf"]
    doc, how = pick_document("121000001", names, names, {})
    assert (doc, how) == ("abc_121000001.pdf", "single-main")


def test_appendix_is_not_the_paper():
    names = ["a_121000001_appendix.pdf", "b_121000001.pdf"]
    doc, how = pick_document("121000001", names, names, {})
    assert doc == "b_121000001.pdf" and how == "single-main"


def test_policy_brief_is_not_the_paper():
    names = ["details121000001_Bab_Amal_Policy_Brief_Details.pdf", "c_121000001.pdf"]
    doc, how = pick_document("121000001", names, names, {})
    assert doc == "c_121000001.pdf" and how == "single-main"


def test_english_translation_preferred():
    names = ["s_121000001_Spanish.pdf", "t_121000001_translated_into_English.pdf"]
    doc, how = pick_document("121000001", names, names, {})
    assert doc == "t_121000001_translated_into_English.pdf" and how == "english"


def test_override_matches_author_named_document():
    names = ["4a1f_Misha_(2019).pdf", "zzz_other.pdf"]
    overrides = {"121000002": {"documents": ["4a1f_Misha_(2019)"]}}
    doc, how = pick_document("121000002", [], names, overrides)
    assert doc == "4a1f_Misha_(2019).pdf" and how == "override"


def test_unmapped_study_returns_none():
    doc, how = pick_document("999999999", [], ["a.pdf"], {})
    assert doc is None and how == "unmapped"
