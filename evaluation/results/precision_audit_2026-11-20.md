# Precision audit and matcher checks (20 November 2026)

Read-only. No model call and no extraction change.

## 60 stored rows from the ten held-out documents

The ten documents were re-extracted at `a11fe82`, before the outcome-in-columns code (`aa5e8ac`,
`00ae159`) and before the outcome backfill (`7143174`), which was applied to the 49 study documents only.
So this sample measures the stored rows as they are on the held-out set, not the post-backfill state.
The rows were checked against the parsed table on the page: the cell at the stored address, the row
label, the column header, and the printed error.

| Class | Rows |
| --- | --- |
| (a) a real effect with the right outcome, arm, value and SE | 31 |
| (b) not an effect (balance, baseline or descriptive) | 1 |
| (c) another study's finding | 0 |
| (d) a duplicate of another stored row | 6 |
| (e) a wrong value or pairing | 22 |
| total | 60 |

"Right arm" includes a column or row that is a treatment, a regressor, a period or a method, because that
is what varies in these tables.

Examples:
- (a) 121430610 b98 p103, `T2: Group coaching + asset`, Education and Training Index 0.54; 121295095
  p26, `Beds` -0.009 (0.036); 121326829 p67, savings 6.83 (4.522) for `Two+ relatives`.
- (b) a72b17099de1 p37, `Number of big trees` 0.27 from "Table 2a: Test of difference in mean
  characteristics". That is a balance test, not an effect.
- (d) 9b89a1ab05bf p97 stores the same cells twice, once as `Delta Jobs` and once as the row subgroup
  (`Industry`, `Services`, `Agriculture`, `Total`); 20883ddebbf3 p16 stores -1.93 as `With outstanding
  loan in kind` and as `% of households: With outstanding loan in kind`.
- (e) 70eedd447e8e p20, cell `(0.021) 0.04`, stores 0.021 as the value: that is the error printed before
  the coefficient 0.04. 52f188437804 p70 stores the row label `Intensive Extension in Phase 1` as the
  outcome and the column header `GVAO (IHST)` as the arm. 70eedd447e8e p18 stores the outcome
  `Mental health index` but repeats the column header as the arm.

Composition of (e): 4 swapped outcome and arm, 13 where only the arm is the column header instead of the
row label, 4 where the outcome is a method, subgroup or fragment, and 1 where the error was stored as the
value. The arm-only errors are the pre-backfill state; the 30-row dry run on these ten showed the
outcome-in-columns rule fixing them.

Six duplicates is 10% of the sample. Five of the six are also a descriptive comparison, so (b) would be 6
if a duplicate were counted there instead.

## Fallback spot-check: 10 of the 106 value+words matches

The fallback moved 106 key rows from no table to a matched table. Ten random ones were checked against
the key's `Source` (row label, column, page, table):

- **6 confirmed.** 121766336 `Total expenditure` 264.6363 in the `Total Expenditure` column; 121347787
  `Savings` 5911.25 in the `(3) Difference (ATT)` column; 121058369 `Goats and sheep` 195.89 in the
  `[6] Goats and sheep` row (the key says `[7]`, the label matches).
- **2 wrong.** 121327437 `Savings` 0.35 matched the `Aggregate income` cell in a different table;
  121327437 `Aggregate Income` 0.19 matched a **balance-table p-value** (`Labor income`, column
  `p-value - (3)=(4)`).
- **1 ambiguous.** 122182715 `Productive asset values` 675.301 has no row or column in its `Source`, so the
  matched cell is plausible but unconfirmed.
- **1 header loss.** 122182715 `Monthly household income` 65.63 matched a cell `(6) 65.630...` whose
  column header is only `(6)`; the column name is lost.

So 6 of 10 are the key's cell. The fallback gains coverage but needs the key's row label or column to
agree before the match is accepted; the two wrong cases would be refused by that check. It is not
changed here.

## Tables with results in the parsed header row

Across the 49 study documents, **32 tables** print results in the header row rather than the body. Ten of
the examples are in 121058367, the wide-table paper, where the first data row becomes the header. Some are
descriptive means rather than effect estimates, for example 0cb609fbf433 p23 (`75.58 - (182.96)`), and
some are the 121475071 case (`Exp. increase in profit | 178.4*** (65.6)`). Count only; not fixed.
