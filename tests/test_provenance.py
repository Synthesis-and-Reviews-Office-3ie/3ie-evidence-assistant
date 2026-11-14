"""Provenance signal: is the mapped document the study's paper? (src/extraction/provenance.py)."""

from src.extraction.provenance import looks_like_review, looks_like_wrong_version

BRIEF = (
    "Policy brief: evaluation of a graduation bundle for the ultra poor in Egypt. Ragui Assaad, "
    "Adam Osman, William Pariente, Christine Valente. May 2024. This brief summarises the context and "
    "the main messages for policymakers."
)
PAPER = (
    "Table 4 reports the regression estimates. The coefficient on treatment is 0.15 with a standard "
    "error of 0.05. We estimate the treatment effect on total consumption."
)


def test_a_short_table_free_brief_is_flagged():
    assert looks_like_wrong_version(BRIEF, table_count=0)


def test_a_paper_with_results_language_is_not_flagged():
    assert not looks_like_wrong_version(PAPER, table_count=0)


def test_any_table_means_it_is_the_paper():
    assert not looks_like_wrong_version(BRIEF, table_count=3)


def test_a_brief_with_one_pass_mention_is_still_flagged():
    brief = BRIEF + " The evaluation also reports one coefficient for the main outcome."
    assert looks_like_wrong_version(brief, table_count=0)


def test_a_long_document_is_not_flagged_even_without_the_words():
    assert not looks_like_wrong_version("Context. " * 5000, table_count=0)


def test_a_reflection_is_a_review():
    assert looks_like_review(
        "This paper reflects on international and regional experiences.",
        "Can Poverty Graduation Programs Truly Free the Poor? Reflections on Experiences")


def test_a_primary_study_is_not_a_review():
    assert not looks_like_review(PAPER, "Impacts of a graduation programme in Bangladesh")


def test_a_learning_brief_is_not_a_review():
    assert not looks_like_review(
        "SPIR learning brief. The effects of poultry and cash transfers. Figure 1b shows receipt.",
        "SPIR Learning Brief")
