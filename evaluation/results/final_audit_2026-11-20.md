# Effect-role flag: final audit, 2026-11-20

## What was measured

Every stored cell now carries the two axes of its table, labelled with one of six roles, and a flag that
says whether the two axes make a programme effect. The rule fails open: a cell is marked as not an effect
only when one axis is explicitly a control, a covariate, a fixed effect, a dummy, a comparison before the
programme, or some other non-effect. Nothing is dropped; the flag is stored and the drop threshold is set
later.

The reader is `anthropic/claude-haiku-5.5`. The audit classifier is `anthropic/claude-sonnet-5.5`, a
different model, given the same six-role rules.

## Corpus state after re-extraction

- 49 mapped documents re-extracted with prune on at commit `8e5f2ae`, then a write-path fix at `7d81ca4`
  for the documents whose vision and prose rows had no flag. Cost across the runs: $6.89 + $0.22 + $0.09
  = $7.20, under the $12 cap.
- Stored rows: 25,834.
- Rows with a null flag: 0.
- Rows flagged as a non-effect: 1,211 (4.7%).
- Rows with a row role: 13,632; with a column role: 12,956. The remainder are vision and prose rows, which
  carry no role and are kept by the open default.

## The audit

A fresh sample of 60 stored cells was drawn from 57 documents that no earlier sample used
(`evaluation/results/final_audit_sample_2026-11-20.csv`, seed 20261120). Each cell's table was located,
the two axes were labelled independently, and the fail-open decision was compared to the stored flag.

Of the 60 cells, the independent rule calls 43 real effects and 17 non-effects.

- Real effects the stored flag drops: **0 of 43**.
- Non-effects the stored flag keeps: 13 of 17.
- Non-effects the stored flag drops: 4 of 17.

The costs in this sample fall on precision, not recall: the flag keeps most of the non-effects it meets,
because a cell whose column cannot be matched keeps open. No real effect is dropped.

## Non-effects still kept (13)

| Paper | Page | Outcome (row) | Column | Independent roles |
|---|---|---|---|---|
| c905701e6922 | 50 | Incomes and Revenues Index | Endline | row=control_or_covariate, col=outcome |
| 0cb609fbf433 | 33 | Value of productive assets | T1: Grp LH / Grp C | row=not_an_effect |
| 99bdbef0f7b7 | 35 | Quantity of Sheep & Goats Owned | (2) Quantity of Sheep & Goats | row=not_an_effect, col=outcome |
| b98a0422b2e2 | 81 | (2) - Daily Consumption P.C. | T1: Ind. coaching + assets | row=not_an_effect |
| 9b89a1ab05bf | 145 | Switch Program | College-Low - Diff- | row=outcome, col=not_an_effect |
| 442bb134bc3b | 8 | Total number of poultry owned | Enhanced Nutrition arms | row=control_or_covariate |
| 4a1f5e7f9586 | 42 | cowbull_a | 2005 - Treated | row=outcome, col=not_an_effect |
| 8d23199222c8 | 89 | (4) Large purchases influence | (4) Large purchases influence | row=not_an_effect, col=outcome |
| ba83facff3d1 | 62 | HH chores | HH chores - 2007-2009 | row=control_or_covariate, col=outcome |
| 37ec5820d8e8 | 20 | - > 2 meals | | row=not_an_effect |
| e23a72cd85d8 | 51 | Locus of Control | ITT w3-w4 * Saturation | row=control_or_covariate |
| 20883ddebbf3 | 13 | Duck/hen | 2005 - Difference (6=4-5) | row=outcome, col=not_an_effect |
| cc6acb106d4b | 12 | Self-employment (typ. month) | | row=not_an_effect |

## Reading

On this sample the flag meets the bar for real effects: none are dropped. The next work, if the flag is to
be used to drop rows, is the opposite end, the non-effects it keeps, most of which have no column label to
match. No threshold is applied here.
