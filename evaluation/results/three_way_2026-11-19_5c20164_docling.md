# Docling score at `5c20164`

Pinned commit `5c20164`. Prune on. Only the Docling project was re-extracted at this commit; MinerU and the union were not, so this report has no cross-source column.

Extraction window: 2026-11-19T19:57 to 2026-11-19T22:49.

| Source | Canonical + value | Exact name + value | Token overlap + value | Canonical SE + value | Outcome present | Stored rows |
| --- | --- | --- | --- | --- | --- | --- |
| Docling | 378/439 | 168/439 | 285/439 | 339/409 | 413/439 | 16458 |

Previous Docling measurement at `0760e63`: coefficient 377/439, SE 261/409.
Now: coefficient 378/439, SE 339/409. The SE rise is the new printed-error lookup. It placed 3,711
errors in the row below, 202 in the column to the right, and 2 in the column to the left. The left rule
is removed in `94beb11`, because two placements do not justify guessing at that side, so a later run
would place at most 337 of 409.

## 61 coefficient misses (439 minus 378)

### outcome category absent: 26
- study 121295428, outcome 'Assets', key value 0.358; category has 0 stored rows
  - the value is stored under: ['livestock']; e.g. ['Total number of poultry owned by househo']
  - the study stores these categories instead: ['consumption', 'empowerment', 'food_security', 'income', 'livestock', 'other']
- study 121295428, outcome 'Assets', key value 8.069; category has 0 stored rows
  - the value is stored under: ['income', 'livestock']; e.g. ['(4) Amount of income earned from egg sal']
  - the study stores these categories instead: ['consumption', 'empowerment', 'food_security', 'income', 'livestock', 'other']

### extracted under a different category: 33
- study 121058356, outcome 'Tontine/AVEC savings (3 months, USD)', key value 0.72; category has 34 stored rows
  - the value is stored under: ['agriculture', 'other']; e.g. ['Days spent in agriculture', 'Capital (Followup 1, 6 months after cash']
  - the study stores these categories instead: ['agriculture', 'assets', 'business', 'consumption', 'education', 'employment']
  - stored outcomes near the key name: ['Other savings (3 months, USD)', 'Other savings (3 months, USD)']
- study 121058356, outcome 'Tontine/AVEC savings (3 months, USD)', key value 1.32; category has 34 stored rows
  - the value is stored under: ['income', 'other']; e.g. ['Full (Followup 1, 6 months after cash gr', 'Household transfers out (yearly, USD)']
  - the study stores these categories instead: ['agriculture', 'assets', 'business', 'consumption', 'education', 'employment']
  - stored outcomes near the key name: ['Other savings (3 months, USD)', 'Other savings (3 months, USD)']

### value present on a different row/column/panel: 1
- study 121058356, outcome 'Livestock count (TLU)', key value 0.8; category has 53 stored rows
  - the study stores these categories instead: ['agriculture', 'assets', 'business', 'consumption', 'education', 'employment']
  - stored outcomes near the key name: ['Change in livestock count (yearly, TLU)', 'Change in livestock count (yearly, TLU)']

### value not extracted at all: 1
- study 121295229, outcome 'Expenditure', key value 2.404; category has 36 stored rows
  - the study stores these categories instead: ['assets', 'business', 'consumption', 'employment', 'fertility_children', 'food_security']

### the key itself wrong: 0


## Manual check of ten coefficient misses

Five from "extracted under a different category" and five from "outcome category absent". For each I
opened the table on the page named by the parsed content and found the key value in its printed cell.

| # | Study | Key outcome | Value | Printed cell | Verdict |
| --- | --- | --- | --- | --- | --- |
| 0 | 121058356 | Tontine/AVEC savings (3 months, USD) | 0.72 | Table 9, p52: row `Capital`, column (2) `Tontine/AVEC savings` = 0.72 | right cell, column name stored as the outcome |
| 6 | 121058359 | Per capita income | 826.587 | Table 4, p46: row `percapinc`, column D1(2005-2002) = 826.587 | right cell, abbreviation stored as the outcome |
| 14 | 121295641 | Assets | 839.076 | Table 3, p39: row `Value of Livestock (USD)` under the `Assets` panel = 839.076 | right cell, panel heading vs row |
| 18 | 121326790 | Assets | 328.0 | Table 4, p25: row `Total Value of Livestock (USD)` = 328 | right cell, table scope vs row |
| 32 | 121354848 | Saving | 0.03 | Saving row (Table 2, p5) prints 0.000 with SE 0.038; the 0.030 cells are wasting (SE), attrition and `sold` | coincidence; no Saving row prints 0.03 |
| 10 | 121295428 | Assets | 0.358 | Table 4, p8: row `Randomized to cash sub-arm`, column (2) `Total number of poultry` = 0.358 | right cell, panel heading vs row |
| 19 | 121328167 | Consumption | -2324.0 | Table IV, p54: row `Year 2 × above k`, column (4) `Cons.` = -2,324 | right cell, abbreviated column |
| 34 | 121378216 | Assets | -0.123 | Table 5.3.3, p36: row `Forsa Treatment`, column (2) `Quantity of Egg-Laying Chickens` = -0.123 | right cell, table scope vs column |
| 40 | 121475285 | Expenditure | -0.01 | Table 2, p9: row `TUP*2014`, column `FoodShr` = -0.01, but -0.01 appears in five other cells | ambiguous; likely the FoodShr column |
| 56 | 122182711 | Assets | 12.4 | 12.4 is printed for small animals in cooking spaces, guinea pigs and sweets; no assets row prints it | coincidence; no Assets row prints 12.4 |

Seven are the right cell stored under a different name: a row label where the key names a column, a
column label where the key names a table, an abbreviation, or a panel heading. One is ambiguous because
the value repeats. Two are coincidences, where the number matches an unrelated cell and no row for the
key outcome prints it. None of the ten is a row that was not extracted, and none is a value read wrongly.

## The 70 standard-error misses (409 minus 339)

| Cause | Rows |
| --- | --- |
| stored under a different category | 28 |
| outcome category absent | 22 |
| row present, error stored but different | 19 |
| row present, error not stored | 1 |
| error not printed (key wrong or page not parsed) | 0 |

Examples: a different category, 121058356 Tontine/AVEC savings 1.32; category absent, 121295428 Assets
0.269; row present but stored error differs, 121058356 Harvest value 15.21; row present but error not
stored, 121378172 daily per-capita consumption-expenditure 0.03. The same label pattern dominates, and
the 19 "stored but different" are the only group that is a reading or pairing error rather than a name.

## The 200 stored standard errors with no cell

- 155 are printed as a parenthesised number in a cell directly below or to the right of the coefficient,
  but the row records no error cell.
- 45 are not printed in the coefficient's cell or its two neighbours.
- All 200 are `se_kind` "se" (2 blank). The split matches rows that never reached the cell check.

They come from the second pass. `extract_document` calls `finalise_addresses` on the first-pass rows, but
`run_second_pass` builds estimates with `to_estimate`, converts them with `rows_for` and merges them, so
the second-pass rows skip `finalise_addresses`. Their errors were checked only by `to_estimate`'s pairing
rules (a printed neighbour wins, a multi-number cell drops the error) and by the arithmetic checks (the
error is positive and agrees with t, p and the interval). They were not checked against the addressed
cell. If the same finalise step ran on them, the 155 would be verified and recorded with a cell, and the
45 would be dropped.

## Naming fixes

No category mapping was changed for this check. The tally shows that most misses are labels, not missing
cells, so a mapping change would raise the score without changing the reader. It must be tested on
documents outside these 49, or it fits the answer key.

