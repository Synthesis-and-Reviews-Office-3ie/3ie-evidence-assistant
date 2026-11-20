# Arm fix, label merge and the re-audit (20 November 2026)

No model calls. The arm fix and the 9b89 label merge are applied; the method and subgroup fields are a
proposal only.

## Arm fix

Rule (`evaluation/arm_fix.py`, tested): when the stored arm equals the column header or the outcome, take
it from the row label if the row is a treatment or regressor, else from the panel. A subgroup row is not
an arm, and a row that is already the outcome is left alone so the layout swap is not masked.

- 1,385 rows changed on the ten held-out documents; undo log
  `evaluation/results/arm_undo_ten_2026-11-20.jsonl`.
- 12 of the 60 audited rows changed, all arm-only: 52f188437804 p66, p73, p58; b98a0422b2e2 p49, p88,
  p100, p105, p65, p77; e23a72cd85d8 p50, p112; fa42c26c3414 p59. For example, 52f188437804 p66
  `Midline use of pesticides` now has arm `Intensive Extension in Phase 1` instead of `Midline use of… -
  Pesticides`; b98a0422b2e2 p49 `Subjective Well-Being Index` now has arm `Spillover Control`.

## Duplicates: combining labels

The keeper is deterministic (standard error, then arm, then longer outcome, then lowest id). When the
deleted duplicate carried a different label, the survivor now takes the combined label. The rule
(`evaluation/dedupe.py`, tested) joins distinct labels with " - " and drops one contained in a longer one;
it combines only when a single-word subgroup label sits beside a longer label, so two long phrases that
merely share a value are not merged.

The 9b89a1ab05bf case: 54 survivors gained a combined label, undo log
`evaluation/results/label_merge_undo_9b89_2026-11-20.jsonl`. The five sampled rows now read
`Delta Jobs - Industry`, `Delta Jobs - Livestock`, `Delta Jobs - Sales`, `Delta Jobs - Services`, and
`Agriculture - Delta Jobs`. `scripts/dedupe_by_cell.py` now combines labels on future runs rather than
only dropping the duplicate.

The 49-document equivalent would change 25 rows, some with placeholders (`Household size - Outcome`), so
it is not applied. It is listed below.

## Method and subgroup fields: proposal

The table already has a `subgroup` column; it has no `estimation_method` column.

Proposed design, not implemented:
- Add `estimation_method TEXT` and use the existing `subgroup`.
- Move a label to `estimation_method` when the whole label names a method: Ridge, Lasso, DRDID, PSM,
  propensity score, ATT, kernel, nearest neighbour, hierarchy, coef/se, p-value, specification, ITT, OLS,
  IV, 2SLS.
- Move a label to `subgroup` when it is a short (one or two word) category: Total, Industry, Services,
  Agriculture, Traditional, Wealth, Male, Female, Girls, Boys, Rural, Urban, Age, Religion.
- Keep the outcome as the table subject and the arm as the treatment. Test the classifier on documents
  outside the 49 before any backfill.

Counts on the 49 study documents (15,852 stored rows):

| Where a method or subgroup label sits | Rows |
| --- | --- |
| method in the arm | 455 |
| method in the outcome | 111 |
| subgroup in the outcome | 287 |
| subgroup in the arm | 51 |

These are separate field counts and overlap, so the number of rows that would move is at most 904 and
should be computed as a union before a backfill.

## Re-audit of the same 60 rows

| Class | Before | After backfill | After dedupe | After arm fix and 9b89 merge |
| --- | --- | --- | --- | --- |
| (a) real effect, right outcome, arm, value and SE | 31 | 34 | 35 | 45 |
| (b) not an effect | 1 | 1 | 1 | 1 |
| (c) another study | 0 | 0 | 0 | 0 |
| (d) duplicate | 6 | 6 | 0 | 0 |
| (e) wrong value or pairing | 22 | 19 | 24 | 14 |
| total | 60 | 60 | 60 | 60 |

The 14 remaining (e): five 9b89 rows whose arm is still the method (`Hierarchy 5 - Diff. No- prod`), one
method as the outcome (`Chang (Ridge) - ATT`), one method in the arm (`ASC - BM (2021)`), one subgroup as
the outcome (`Traditional`), two fragments (`share of`, `index (final block)`), one swap (`Healthcare`,
outcome is the treatment and the arm is empty), one error stored as the value (`(0.021) 0.04` stores
0.021), and two whose arm still repeats the outcome (`Wealth`, `Months of Treatment2`).

## Next candidates

- Method or subgroup labels in the outcome or arm: 904 field assignments (union to compute).
- Fragments as the outcome: 2 in the 60.
- Swaps of outcome and arm: 1 in the 60.
- An error stored as the value: 1 in the 60.
- The arm still repeats the outcome: 2 in the 60.
- The 49-document label merge (25 rows) needs a placeholder guard before it runs.
- Results in the parsed header row: 32 tables across the 49.
