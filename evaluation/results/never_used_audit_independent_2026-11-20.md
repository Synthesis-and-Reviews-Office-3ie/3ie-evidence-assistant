# Independent audit: 60 rows from 16 never-used documents

*Audited 2026-11-20 by an independent reviewer (Claude Code), against the PDF pages, not by a model re-labelling
rows.*

**Sample.** `never_used_sample_2026-11-20.csv`: 60 rows, seed 20261122. The rows come from 16 of the 17 documents
that no earlier sample, test or fix used. They were re-extracted with the current reader (role flags,
spaced-minus fix, DiD rules).

**Classes.** As in the two earlier fresh audits, under Lucas's rules of 20 November:

- (a) Correct: a programme effect with the right outcome, arm, value and qualifiers.
- (b) Not an effect.
- (e) A real effect stored with a wrong value, sign or label.

A standard error printed but not stored is noted, not failed, as before. The flag is judged separately: does
`keep_effect` keep the real effects and hide the non-effects?

## Result

| Class | Rows | Earlier fresh samples |
| --- | --: | --- |
| (a) correct | **28 (47%)** | 21 and 19 of 60 |
| (b) not an effect | 10 | 19 and 21 |
| (e) real effect, wrong value, sign or label | 22 | 20 and 20 |

**The flag.** There are 50 real effects (a + e) and 10 non-effects in the sample.

| | Kept (shown) | Hidden |
| --- | --: | --: |
| Real effects (50) | 45 | **5** |
| Non-effects (10) | 2 | 8 |

The app would show 47 rows. Of those, 25 (53%) are fully right, 20 are real effects with a fault, and 2 are
not effects.

## What still goes wrong

### Real effects hidden by the flag (5)

- **Jalal 2013, three rows.** The rows are child age groups ("6–11 mo") and the column is the difference of
  differences. The model labels age-group rows `not_an_effect`, so three real DiD effects are hidden.
- **Raza 2018 Table 4 (p14).** The outcome is stored as "Non-poor households", a subgroup. The row role then
  reads as non-effect.
- **121340926 p10.** An effect-size column (odds ratio 0.32 [0.05, 1.87]) gets column role `not_an_effect`,
  and the arm is stored as "column 3".

### Wrong value or sign (9 of the 22 (e) rows)

| Cause | Rows | Examples |
| --- | --: | --- |
| Spaced minus still lost | 3 | 121346575 prints `- 0.004`, `- 0.014`, `- 0.005`. All three are stored as positive, despite the spaced-minus fix in `3182372` |
| Minus glyph printed as `2` (rendered-page reading not applied) | 2 | Emran 2014 `2.01` is −.01 (saris-to-lungis ratio) and `21.14` is −1.14 (big trees). Confirmed by the CI `2.04, .21` around .09 |
| Leading decimal point lost | 2 | Emran 2014 `.10` stored as 10, `.92` stored as 92 |
| Sign convention reversed | 2 | Jalal 2009 "benefit attributable to programme (A−B)" (42.5, 10.3) is comparison minus programme, a reduction, but is stored as a plain positive effect |

### Wrong or missing label (13 of the 22 (e) rows)

- **Arm missing in a two-arm study:** Rahman 2023, grants-only vs hybrid (2 rows).
- **Timing missing or wrong:** Sulaiman 2015 "after 2 years" stored under a table labelled "after 4 years"
  (2 rows).
- **Population missing:** Bandiera 2011 Table 6 is the effect on other poor women (spillover), stored like
  the main effect.
- **Outcome replaced by the arm:** Hossain 2017, outcome "Treatment X 2009" (2 rows).
- **Other missing qualifiers:**
  - Rahman 2023 "impact as % of nonparticipant mean" stored as a level (83.72).
  - Chowdhury 2024 GATES "most affected 20%" stored under subgroup "Random Forest".
  - Ara 2016 food category ("Miscellaneous") dropped from the outcome.
- **Spurious qualifier:** Nicaragua 121319138 Table 3 "in 2005" (a covariate's label) attached to the
  programme effect.
- **The two rows the flag hides,** above: Raza 2018 and 121340926.

### Non-effects (10)

- **Hidden correctly (8):**
  - p-values and CI bounds (121340926)
  - a follow-up difference where a DiD exists (Ahmed 2009)
  - a time effect within the control group (Ahmed 2006)
  - a covariate (Chowdhury 2024)
  - a baseline normalised difference (Bandiera 2011)
  - a treatment-group mean (Ara 2016)
- **Shown wrongly (2):** a follow-up difference where a DiD exists (Ahmed 2009, shoes 0.06), and the
  odds ratio of a covariate (Ahmed 2006, health expenditure 3.56).

## Row-level verdicts

| Doc | Rows (index: class) |
| --- | --- |
| Roy 2015 (3cfb) | 0 a · 16 a · 32 a · 48 a |
| Raza 2018 (6d1f) | 1 a · 33 a · 49 a · 17 e (subgroup as outcome; hidden) |
| Sulaiman 2015 (fc67) | 34 a · 50 a · 2 e · 18 e (after 2 years, labelled 4) |
| Ahmed 2009 (57a7) | 3 a · 35 a · 19 b (shown) · 51 b |
| 121340926 (5862) | 4 b · 20 b · 36 b · 52 e (OR effect size hidden) |
| Emran 2014 (4f55) | 5 e · 21 e (minus as 2) · 37 e · 53 e (decimal lost) |
| Bandiera 2011 (26b0) | 6 a · 22 a · 38 b · 54 e (other poor women) |
| Nicaragua 121319138 (b952) | 7 a · 23 a · 39 a · 55 e (spurious "in 2005") |
| Ara 2016 (df0f) | 8 a · 24 a · 40 b · 56 e (food category dropped) |
| Jalal 2009 (c4ba) | 25 a · 57 a · 9 e · 41 e (reversed convention) |
| Ahmed 2006 (2419) | 42 a · 58 a · 10 b · 26 b (shown) |
| Chowdhury 2024 (90e8) | 43 a · 59 a · 27 b · 11 e (GATES quintile) |
| Jalal 2013 (ec6c) | 12 a · 28 a · 44 a (all three hidden by the flag) |
| Hossain 2017 (6659) | 13 a · 29 e · 45 e (arm as outcome) |
| Rahman 2023 (a1da) | 14 e · 30 e · 46 e (arm missing; % of mean) |
| 121346575 (6b4e) | 15 e · 31 e · 47 e (spaced minus lost) |

The sign of Jalal 2013 row 28 (stored −0.06, text layer 0.06) could not be confirmed from the text layer. The
magnitude and the cell are right.

## What this implies

1. **Progress is real:** 47% correct, against about a third in the earlier fresh samples, and non-effects fell
   from about 20 to 10.
2. **Numbers are still the most harmful fault.** Spaced and glyph minus signs and lost leading decimals give 7
   wrong values in 60 rows. The spaced-minus fix does not reach these documents, and the rendered-page reading
   did not run on Emran 2014.
3. **The flag hides real effects** when rows are subgroups (age groups) or columns are effect sizes. It should
   not use `not_an_effect` for a subgroup row.
4. **Labels:** the arm, timing and population qualifiers are the next largest group.
