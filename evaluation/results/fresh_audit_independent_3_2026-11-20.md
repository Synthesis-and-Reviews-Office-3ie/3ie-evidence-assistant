# Independent precision audit: third fresh sample

*Audited 2026-11-20 by an independent reviewer (Claude Code), not by the session that built the reader.*

**Sample.** The 60 rows in `fresh_audit_sample_3_2026-11-20.csv` (seed 20261121), from ten documents not used
before. The documents were re-extracted after `3d1810a`, which added the programme-term filter, the row-role
question to the model and the corrected prompt.

**Method and classes.** As in `fresh_audit_independent_2026-11-20.md`. Each row was checked against the PDF
page with `pdftotext` (raw and layout modes). A row is (a) only if outcome, arm, value and SE are right and no
qualifier is missing or wrong. A missing method or model number is noted but not failed. Junk in a label that
does not change the meaning (for example a subgroup "Death" on a livestock-death row) is also not failed.

## Result

| Class | This sample | First fresh sample |
| --- | --: | --: |
| (a) real effect, right outcome, arm, value and SE | **19** | 21 |
| (b) not an effect | **21** | 19 |
| (c) another study's finding | 0 | 0 |
| (d) duplicate | 0 | 0 |
| (e) wrong value, label or pairing | **20** | 20 |

The changes in `dd7fd5c` and `3d1810a` did not raise the share of correct rows on new documents: 19 of 60 here,
against 21 of 60 before. The failures are of new kinds, which is what a fix tuned on one sample would produce.

## Why rows fail

### (b) Not an effect: 21 rows

| Cause | Rows | Examples |
| --- | --: | --- |
| Covariate coefficients in regression tables | 10 | Mallick 2013 Tables 6, 8 and 9: `FSIZE`, `GEND`, `VISIT`, `IGA`. Nicaragua 121315117 Table 3: household size, education and age of head, distance to school. Das 2010 Table 3: `Beneficiary=1` (the pre-programme gap; the effects are `Year 5*beneficiary` and `Year 8*beneficiary`) |
| Baseline (2002) difference columns in DiD summary tables | 6 | Das 2010 Annexes 4, 8 and 9, column "(3=1-2)" |
| Sensitivity statistics | 2 | Mallick 2013 Table 4: Mantel-Haenszel statistics 5.30 and 6.55, with the p-value 0.000 stored as an SE of 0 |
| Cost-effectiveness ratios | 2 | 121058370 Table 15: cost per taka of increased consumption |
| Correlations | 1 | Das 2010 Table 11: correlation between food insecurity and asset indices |

The row-role step reported 0 disagreements, yet 10 covariate rows were kept. The new filter did not act on
these tables. It should be traced: either the model labelled covariates as programme terms, or the filter did
not see these tables as regression tables. `Beneficiary=1` also passes the code rule, because `beneficiar` is in
the programme-term list.

### (e) Wrong value, label or pairing: 20 rows

| Cause | Rows | Examples |
| --- | --: | --- |
| **Minus sign lost: a reduction stored as an increase** | 8 | Nicaragua Table 3, T1 farm work −1.673 stored as 1.673. Table 7, T2 farm work −10.345 stored as 10.345. Table 6: −0.741, −1.181, −0.568. Jalal 2022 Table 2 prints `- 0.406` with a space after the minus: restricted movement −0.406, psychological oppression −0.296 and violence during pregnancy −0.447 are all stored as positive |
| t-statistic stored as the SE | 4 | Population and Development Review supplement, Tables A4 and A5: the parenthesised values are negative (e.g. `(-2.99)`), so they cannot be SEs, whatever the note says. Two of these rows also store the specification or subgroup as the outcome |
| Unsigned effect size or reversed convention | 3 | Jalal 2022 Table 2 effect-size column (0.149, 0.421) stored as the estimate with no sign. Table 3 "benefit attributable" 13.5 is comparison minus programme, stored with arm "Program vs comparison" |
| Wrong qualifier on a change-in-impact column | 4 | Das 2010 column "(12=11-10) difference between impacts in 2005 & 2008" stored with subgroup "in 2005" |
| Wrong year | 1 | Das 2010 Annex 7: 0.5 is column (6), the 2005 difference, but the arm says 2008 |

**The sign errors reverse findings.** In the Nicaragua paper, both interventions reduce child labour, but the
stored rows say they increase it. These 8 rows are the most harmful failure in the sample.

## Row-level verdicts

Index = row number in the CSV, from 0.

| Doc | Rows (index: class) |
| --- | --- |
| Das 2010 (1a25) | 1 a · 8 a · 13 a · 26 a · 27 a · 34 a · 35 a · 36 a · 37 a · 48 a · 4 b · 9 b · 12 b · 21 b · 23 b · 59 b (2002 gap) · 47 b (`Beneficiary=1`) · 33 b (correlation) · 6 e · 18 e · 28 e · 56 e ("in 2005" on change-in-impact) · 25 e (2005 value labelled 2008) |
| Mallick 2013 (37d3) | 5 a · 2 b · 3 b · 11 b · 16 b · 17 b · 24 b (covariates) · 38 b · 45 b (Mantel-Haenszel) |
| Nicaragua 121315117 (7962) | 43 a · 15 b · 20 b · 41 b (covariates) · 32 e · 42 e · 44 e · 53 e · 55 e (sign lost) |
| Jalal 2022 (6954) | 10 e · 14 e · 58 e (sign lost) · 29 e · 39 e (unsigned effect size) · 40 e (reversed convention) |
| PDR supplement (c39f) | 52 a · 22 e · 50 e · 54 e · 57 e (t-statistic as SE) |
| 121058357 (ef2e) | 0 a · 31 a · 46 a · 51 a |
| Raza 2012 (0f5e) | 7 a · 30 a |
| 121058370 (2a45) | 19 b · 49 b (cost-effectiveness) |

## What this implies

1. Patching rules after each sample does not generalise. Each fresh draw shows new layouts and new failures.
   Deciding whether a number is a programme effect needs a stronger, general decision, then a test on another
   fresh draw.
2. **Sign handling** is a deterministic fix and the most urgent. Read `- 0.406` as negative. Flag documents
   whose text layer drops or replaces the minus glyph, and read their numeric cells from the rendered page.
3. A negative number in the SE position is a t-statistic. Never store it as an SE.
4. Columns that compare groups at baseline, sensitivity statistics, cost ratios and correlations are not
   programme effects.
