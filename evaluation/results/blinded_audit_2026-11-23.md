# Blinded audit of reader arms A and B

*Audited 23 November 2026 by an independent reviewer (Claude Code and four checker agents), against rendered
PDF pages. The verdicts were fixed before the arm key was revealed.*

**Arms.** Both arms read the 16 never-used documents. A is the reader without study card or gallery. B is the
reader with the study card (arm, time point and population chosen from the card's lists), the gallery examples
in the prompt, and the outcome label copied from the table cell the model points at.

**Samples.** Four blinded files of 60 rows. X and Y are matched on cell address (cells both arms stored). P and Q
are drawn independently from each arm's full output (seed 20261124). Key: X = B, Y = A, P = A, Q = B.

**Classes.** As in the earlier audits: (a) correct programme effect with the right value, sign, outcome, arm and
qualifiers, (b) not an effect, (d) duplicate, (e) a real effect with a wrong value, sign or label. This audit
also fails a row that does not say which model or specification it comes from when the table prints several.

## Result

| Arm | Sample | Correct (a) | Not an effect (b) | Wrong label or value (e) | Duplicate (d) |
| --- | --- | --: | --: | --: | --: |
| A | Y (matched) | 17 | 8 | 35 | 0 |
| A | P (independent) | 27 | 6 | 26 | 1 |
| B | X (matched) | 15 | 8 | 37 | 0 |
| B | Q (independent) | 15 | 9 | 36 | 0 |
| **A** | **both** | **44 of 120 (37%)** | 14 | 61 | 1 |
| **B** | **both** | **30 of 120 (25%)** | 17 | 73 | 0 |

In five arm-A rows from the Nicaragua paper, the outcome text sits in the arm field. They are counted as (a)
because nothing is lost. A stricter reading gives arm A 39 of 120 (33%).

**Arm B is not better than arm A. On the independent samples it is worse: 15 of 60 rows correct (25%) against 27 of 60 (45%).**

## Why B does worse

| Fault (e rows) | A | B |
| --- | --: | --: |
| Outcome wrong | 34 | 24 |
| Specification or model missing ("other") | 8 | 16 |
| Subgroup or population missing | 3 | 11 |
| Time point missing or wrong | 2 | 7 |
| Sign lost | 3 | 6 |
| Unit or format wrong (% of mean as a level, unsigned effect size) | 5 | 6 |
| Arm wrong (an SE or fragment in the arm field) | 6 | 0 |

1. **The copied outcome label helps.** Wrong outcomes fall from 34 to 24.
2. **The card lists remove qualifiers.** In B, 19 of 120 rows carry "not on card" as the arm or subgroup.
   Subgroup, population, time point and specification faults rise from 13 to 34. When the right qualifier is
   not on the card, B drops the table's own text instead of keeping it.
3. **The reader has nowhere to store the new fields.** `time_point`, `population`, `effect_type`,
   `specification` and `estimand` are empty in both arms, because the migration that adds them is not applied.
   The gallery teaches fields that the output cannot hold.

## Other findings

- **The effect flag was off in both arms.** The arm runner did not pass `read_roles=True`, so every row in both
  arms has `keep_effect = True`. The 31 non-effects in the samples would all be shown.
- **Signs are still lost in Ara 2016.** The page prints −10.22 and −0.06. Both arms store them positive.
- **Rahman 2023 "impact as % of nonparticipant mean"** is still stored as a level in both arms.
- **Hossain 2017 and Jalal 2009** are poor in every sample (2 of 56 rows correct), mostly through bare column
  numbers or headers stored as the outcome and missing model labels.

## What this implies

1. Keep the copied outcome label. Do not adopt the card lists as a restriction. The card should add qualifiers
   the table does not print, never replace the table's own text with "not on card".
2. Apply the migration (Lucas to approve) so the reader can store time point, population, specification and
   estimand. Without these columns the qualifiers are lost whatever the prompt says.
3. Test the gallery on its own (A plus gallery) to separate its effect from the card's.
4. Re-run with `read_roles=True` so the flag can be judged.
