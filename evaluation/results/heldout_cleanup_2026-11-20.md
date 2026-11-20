# Held-out cleanup: backfill, dedupe and fallback (20 November 2026)

Read-only measurement after three changes. No model calls.

## 1. Outcome backfill on the ten held-out documents

198 rows were renamed with the outcome-in-columns rule. The undo log is
`evaluation/results/outcome_backfill_undo_ten_2026-11-20.jsonl`.

The original 60-row audit was re-checked at the same addresses. The before state is the undo record where
the row changed; otherwise the row is unchanged.

| Class | Before | After backfill | After dedupe |
| --- | --- | --- | --- |
| (a) real effect, right outcome, arm, value and SE | 31 | 34 | 35 |
| (b) not an effect | 1 | 1 | 1 |
| (c) another study | 0 | 0 | 0 |
| (d) duplicate of another stored row | 6 | 6 | 0 |
| (e) wrong value or pairing | 22 | 19 | 24 |
| total | 60 | 60 | 60 |

Three sampled rows changed and all three were swaps, now correct:
- 52f188437804 p70: `Intensive Extension in Phase 1` / `(2) GVAO (IHST)` became `GVAO (IHST)` /
  `Intensive Extension in Phase 1`.
- 52f188437804 p63: `Received Input Package` / `Intensive Margin: Total - Soy` became the column outcome
  as the outcome and the treatment as the arm.
- 52f188437804 p64: `Received Cash Transfer` / `(9) Farm management plan` became `Farm management plan` /
  `Received Cash Transfer`.

The other 57 sampled rows did not meet the swap condition (the model had already used the column header
as the outcome, or the row did not name a treatment), so they are unchanged.

## 2. Duplicates by cell

A duplicate is the same document, table view, cell address and coefficient. Rows with the same cell and a
different value are different estimates from a multi-pair cell and are kept.

The keeper is deterministic (`evaluation/dedupe.py`, tested): a row with a standard error first, then a
row with an arm, then the longer outcome name, then the lowest id. On 9b89a1ab05bf the rule keeps
`Delta Jobs` (the table subject) over the row subgroup, because it is the longer label.

- 606 rows removed on the 49 study documents, undo log `dedupe_undo_49_2026-11-20.jsonl`.
- 325 rows removed on the ten held-out documents, undo log `dedupe_undo_ten_2026-11-20.jsonl`.

Re-audit of the 60 after the delete: the six duplicates are gone. Five are the 9b89 table where the kept
row now carries `Delta Jobs` and loses the subgroup, so they move from (d) to (e). The sixth is
20883ddebbf3, where the kept row is the more specific `% of households: With outstanding loan in kind`.

## 3. Tightened fallback

The value fallback now accepts a table only when the key's row label or column heading agrees with the
cell that prints the value. If the key has neither, the fallback does not fire.

| Measure | Before | After |
| --- | --- | --- |
| Cell-address coefficient | 381/439 | **363/439** |
| Cell-address SE | 333/409 | **310/409** |
| Coefficient where the named table prints the value | 381/387 (98%) | **363/368 (99%)** |
| SE where the named table prints the value | 333/366 (91%) | **310/348 (89%)** |
| Key rows with no matched table | 40 | 59 |

The tighter rule loses 18 coefficient placements and 23 SE placements. In the ten checked earlier, it
keeps the 6 confirmed cells and refuses the 2 wrong ones (a balance-table p-value and a wrong table), the
1 with no row or column in the key, and the 1 where the column name is lost.

## Next candidates (not fixed)

- Swaps of outcome and arm: 1 in the 60, 701165f57f97 p30 `Healthcare`, whose outcome is the treatment
  header and whose arm is empty. The other three swaps were fixed.
- Fragments used as the outcome: 2 in the 60, `share of` and `index (final block)`.
- The outcome is a method or a subgroup instead of the row: 7 in the 60, `Chang (Ridge) - ATT`,
  `Traditional`, and the five 9b89 `Delta Jobs` rows.
- Only the arm is wrong, repeating the column header: 13 in the 60.
- Results sit in the parsed header row: 32 tables across the 49 documents.

No swap, fragment or header-row fix was applied.
