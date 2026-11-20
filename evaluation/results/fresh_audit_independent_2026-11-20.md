# Independent precision audit: ten fresh documents

*Audited 2026-11-20 by an independent reviewer (Claude Code), not by the session that built the reader.*

**Sample.** The 60 rows in `fresh_audit_sample_2026-11-20.csv` (seed 20261120). They come from ten documents
drawn at random from the 39 outside the 49 study documents and the 10 held-out documents. The documents were
re-extracted at `fa863f8` with the new reader.

**Method.** Each row was checked against the page of the local PDF in `data/PDFs of included programs/`.
The checks used `pdftotext -layout` text. Where the text layer was ambiguous, the table was read in full.

**Classes.** The same five classes as the earlier audits, with one clarification. A row counts as (a) only if a reader could identify the
estimate: outcome, arm, value and SE right, and no missing subgroup, time period, pathway or shock type that
changes what the number means. A missing estimation method or model number is noted but not failed. When a
row fails more than one class, it is counted in the first that applies, in the order (b), (c), (d), (e).

## Result

| Class | Rows | Share |
| --- | --: | --: |
| (a) real effect, right outcome, arm, value and SE | **21** | 35% |
| (b) not an effect | **19** | 32% |
| (c) another study's finding | 0 | 0% |
| (d) duplicate | 0 | 0% |
| (e) wrong value, label or pairing | **20** | 33% |

On fresh documents, 21 of 60 stored rows (35%) are fully right. On the ten held-out documents the figure was
45 of 60 (75%). Those documents had been used to design the fixes, and they are mostly regression tables from
journal articles. The fresh draw includes NGO evaluation reports, pre-post indicator tables and older journal
PDFs.

Duplicates could only be judged within the sample. Cross-table duplicates are not visible from 60 rows.

## Why rows fail

### (b) Not an effect: 19 rows

| Cause | Rows | Examples |
| --- | --: | --- |
| Pre-post (baseline vs endline) indicator tables | 7 | 121294813 p79–p98, e.g. "Antenatal Care 77.6, Endline vs baseline" |
| Coefficient on a covariate, time dummy or baseline gap, not the programme term | 6 | Krishna 2010 Table 6: `SUP 2002` (pre-programme gap), `Year 2005`, `House damaged`. 121498871: `Cohort 3`, `Religious group` |
| Baseline balance table | 4 | Bandiera 2013 Tables 2 and A3, "(3) Raw Differences". Krishna 2012 Table 3, 2002 SUP−NSUP |
| p-value column of a descriptive table | 2 | Haseen 2007 Table 8: `Total calorie` 0.01 and `Pulse` 0.78 are the 2006 P column |

### (e) Wrong value, label or pairing: 20 rows

| Cause | Rows | Examples |
| --- | --: | --- |
| **Wrong value: minus sign or decimal lost in the PDF text** | 4 (and 4 more rows already counted in (b)) | Jalal 2015 prints minus as `2` (`20.444` is −0.444). In (b): Krishna 2012 prints minus as `7` (`7291.83` is −291.83), and Bandiera A3 `.582` is stored as 582 and `-.036` as 36 |
| Missing subgroup, time period, pathway or shock | 9 | Bandiera A4 panel (wage vs self-employed at baseline) dropped. Haseen Table 10 "between 2002 and 2004" dropped. Siddiquee Table 10 shock type (`House damage`, `EM died`) dropped. Jalal Table 6 pathway dropped |
| Method or model stored as outcome or arm | 4 | Krishna `Model 2`/`Model 4` as the outcome. 121294813 `K-Nearest Neighbor Matching` as the outcome, `Regression Adjustment - Base Covariate` as the arm |
| p-value stored as the SE | 2 | 121294813 Figure 3.40: `(0.94)` and `(0.92)` are p-values |
| Arm and SE missing | 1 | Bandiera A6 col (2): 0.172, no arm, no SE |

Some rows have more than one fault. Each is counted once, under its main cause.

**The value check cannot catch the sign errors.** `accuracy.py` confirms that a stored value matches the
parsed cell text. In Jalal 2015 and Krishna 2012, the PDF's own text layer encodes the minus sign as a digit.
The cell text is therefore wrong in the same way as the stored value, and the check passes. The Krishna 2010
working paper prints the same table with proper minus signs, which confirms the reading.

## Row-level verdicts

Index = row number in the CSV, from 0.

| Doc | Rows (index: class) |
| --- | --- |
| Bandiera 2013 (a121) | 0 a · 2 a · 9 a · 11 a · 44 a · 48 a · 51 a · 52 a · 16 b (balance; .582→582) · 32 b (balance) · 56 b (balance; −.036→36) · 23 e (no arm, no SE) · 45 e · 55 e · 57 e (panel subgroup dropped) |
| 121294813, USAID Nobo Jatra (3416) | 26 a · 46 a · 8 b · 10 b · 12 b · 13 b · 20 b · 25 b · 27 b (pre-post) · 6 e · 15 e (p-value as SE) · 38 e (method as arm) · 49 e (method as outcome) |
| Siddiquee 2016 (5bd5) | 4 a · 14 a · 19 a · 24 a · 34 a · 53 a · 59 a · 29 e · 42 e (shock type dropped) |
| Jalal 2015 (82fc) | 17 e · 33 e · 35 e · 37 e (minus read as 2) · 3 e · 58 e (pathway dropped) |
| Krishna 2010 (db0c) | 28 a · 5 b (covariate) · 7 b (baseline gap) · 36 b (year dummy) · 47 e (`Model 2` as outcome) |
| Krishna 2012 (f9f7) | 18 a · 31 b (baseline gap; minus read as 7) · 39 b (2002 descriptive gap; minus read as 7) · 54 e (`Model 4` as outcome) |
| Haseen 2007 (b100) | 21 b · 30 b (p-value column) · 1 e (period dropped) · 40 e (change-in-impact label dropped) |
| Md 2025 (4bc6) | 41 a · 43 a |
| 121498871 (b346) | 22 b (group-participation association) · 50 b (cohort dummy) |

## What this implies

1. **Choosing which numbers to keep** is the largest gap: 19 of 60 rows are not programme effects. These
   rows come from tables or terms that should be skipped: pre-post indicators, balance tables, covariate and
   time-dummy coefficients, and p-value columns.
2. **Qualifiers are dropped.** Subgroup panels, time periods, shock types and pathways go missing, which
   changes what a number means.
3. **Sign errors from the PDF text layer** pass every current check. Only a check against the rendered page,
   or a rule for known glyph substitutions, would catch them.
4. The held-out figure (45 of 60) does not generalise. Any further fix should be judged on another fresh draw, not
   on these 60 rows.
