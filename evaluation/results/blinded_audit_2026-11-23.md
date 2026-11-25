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

## Second round: arms D and E (recorded before the key was revealed)

D is the reader with the copied outcome label and the gallery, without the card. E is D with the card as a hint
(a card value is preferred when one fits, otherwise the table's text is kept). Both write time point,
population, effect type, specification and estimand to their own columns, and both compute the effect flag.
Samples R and S, 60 rows each, independent, seed 20261125. Same classes, with two stricter rules: text in the
wrong field is (e), and a row that does not name its specification when the table prints several is (e).

| Sample | Correct (a) | Not an effect (b) | Wrong label or value (e) | Duplicate (d) | Not found (x) |
| --- | --: | --: | --: | --: | --: |
| R | 26 (43%) | 9 | 23 | 1 | 1 |
| S | 21 (35%) | 7 | 32 | 0 | 0 |

For comparison on the same standard: arm A's independent sample P scored 22 of 60 (37%), arm B's Q 15 of 60
(25%). With 60 rows a share has a standard error of about 6 points, so only differences of more than about 15
points are clear.

**The effect flag now works in part.** In R it hides 5 of 9 non-effects and 4 of 49 real effects. In S it hides
3 of 7 non-effects and 2 of 53 real effects. Lee bounds stored as rows (Roy Table 4) and mediation first-stage
coefficients (Hossain annex) are still shown.

**Faults.** Wrong outcome dominates both samples (17 each): values attached to a neighbouring row (Raza Table 4),
the number's own text or a column number as the outcome, outcome and arm swapped. In S, five rows also carry a
wrong effect type, for example a within-subgroup effect labelled "difference in effect between subgroups", or
a matched programme-versus-comparison estimate labelled "difference between arms".

**Key, revealed after the verdicts were recorded:** R = D (copied label and gallery, no card), S = E (D with the
card as a hint).

| Arm | What it adds | Independent sample correct |
| --- | --- | --: |
| A | current reader | 22 of 60 (37%) |
| B | card as a restriction, gallery, copied label | 15 of 60 (25%) |
| D | copied label, gallery | 26 of 60 (43%) |
| E | D with the card as a hint | 21 of 60 (35%) |

D is the best arm, but its lead over A is within sampling error. The card lowered the score in both rounds,
as a restriction and as a hint. The five wrong effect types in S suggest the card's labels push the reader
towards wrong categories.

## What this implies

1. Keep the copied outcome label. Do not adopt the card lists as a restriction. The card should add qualifiers
   the table does not print, never replace the table's own text with "not on card".
2. Apply the migration (Lucas to approve) so the reader can store time point, population, specification and
   estimand. Without these columns the qualifiers are lost whatever the prompt says.
3. Test the gallery on its own (A plus gallery) to separate its effect from the card's.
4. Re-run with `read_roles=True` so the flag can be judged.
