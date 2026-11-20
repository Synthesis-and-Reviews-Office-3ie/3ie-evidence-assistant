# Docling score at `00ae159`

Code at `00ae159`. The 49 Docling documents were re-extracted at `5c20164`; the stored outcome names were then backfilled from the saved tables with the outcome-in-columns rule, no re-extraction and no model call. MinerU and the union were not re-extracted.

Extraction window: 2026-11-19T19:57 to 2026-11-19T22:49.

| Source | Canonical + value | Exact name + value | Token overlap + value | Canonical SE + value | Outcome present | Stored rows |
| --- | --- | --- | --- | --- | --- | --- |
| Docling | 378/439 | 172/439 | 285/439 | 339/409 | 413/439 | 16458 |

Before the backfill, at `5c20164`: coefficient 378/439, SE 339/409.
After the backfill: coefficient 378/439, SE 339/409. Exact-name matches rose from 168 to 172; canonical
and SE did not move.

Cell-address recall: a key value counts only when a stored row's cell address is the cell that prints it
in the table named by the key's `Source` (page, table number and label). The key has 439 coefficients
and 409 SEs.

- coefficient: 278/439 (63%) overall; **278/281 (99%)** where the named table is parsed and prints the
  value. 146 key rows could not be matched to a parsed table, and 12 matched a table that does not
  print the value.
- SE: 243/409 (59%) overall; **243/261 (93%)** where the named table prints the value.

The gap from canonical is table matching and value absence, not address errors: where the table is
found and prints the value, 99% of coefficients and 93% of SEs sit in the printing cell. The measure is
`evaluation/cell_recall.py`.

## Outcome-in-columns, held-out check

30 random stored rows from the ten held-out documents (seed 20261120), each checked against the table on
its page before writing anything:

- before: 27 of 30 stored the actual outcome. Three stored the row label, which names a treatment, while
  the actual outcome was the column header: 52f188437804 p70 `Intensive Extension in Phase 1` (header
  `GVAO (IHST)`), p63 `Received Input Package` (header `Intensive Margin: Total - Soy`), p64
  `Received Cash Transfer` (header `Farm management plan`).
- after: 30 of 30.
- five more rows had the outcome right but the arm field holding the column header; the rule moved the
  row label into the arm. No row changed wrongly: `Control over earnings` and the method headers
  (`kernel`, `Hierarchy`, `ATT`) were left alone.
- placeholder headers (`column 2`), periods (`12 months`, `last Mehr season`), fragments, and an arm
  after its ordinal (`(3) Full Package`) are refused.

The canonical score did not move because the renamed rows were already in the key's category. Of the
seven hand-checked misses, one is a layout case the rule missed; four are category or scope; two are
abbreviations. The claim that no remaining miss is a layout case is wrong for one row.

## The seven hand-checked misses after the backfill

| # | Study | Key outcome | Value | Stored outcome now | Category now | Why it still does not count |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 121058356 | Tontine/AVEC savings (3 months, USD) | 0.72 | `Capital (Followup 1, 6 months after cash grants)` | other | Layout miss: the row label `Capital` is not in the role vocabulary, so the Tontine header was not used. The header was **not** refused by the numbered-arm rule; `_ARM_ROW` does not match `Tontine/AVEC`. |
| 6 | 121058359 | Per capita income | 826.587 | `percapinc` | other | Outcomes in rows; the header is a time period. The abbreviation does not map to income. |
| 14 | 121295641 | Assets | 839.076 | `Value of Livestock (USD)` | livestock | Outcomes in rows; the header is an arm. The key's Assets scope does not include livestock. |
| 18 | 121326790 | Assets | 328 | `Total Value of Livestock (USD)` | livestock | Outcomes in rows; the header is a statistic. Assets vs livestock. |
| 10 | 121295428 | Assets | 0.358 | `Total number of poultry owned by household` | livestock | The outcome is already the column header. Assets vs livestock. |
| 19 | 121328167 | Consumption | -2324 | `(4) Cons.` | other | The outcome is already the column header; the abbreviation does not map to consumption. The arm is still the header. |
| 34 | 121378216 | Assets | -0.123 | `Quantity of Egg-Laying Chickens` | livestock | The outcome is already the column header. Assets vs livestock. The arm is still the header. |

Tally: one layout case the rule missed (row 0), four category or scope cases (rows 14, 18, 10, 34), and
two abbreviation cases (rows 6, 19). The Tontine header is not an arm; the rule did not fire because
`Capital` is not in the row-role vocabulary.

## Undo record

The 381-row backfill kept no undo log. The old arm cannot be recovered exactly from the store; for the
rows the rule changed, the old outcome is their current arm, but the old arm is not recorded.
`scripts/backfill_outcomes.py` now writes an undo log with the id and the old and new outcome and arm
before any update, on a dry run too. A dry run on the ten held-out documents produced 198 records.

The 61 misses below are the same counts as before the backfill. Most are category or scope cases, but
the table above shows that one is a layout case the rule missed.

## 61 coefficient misses (439 minus 378)

### outcome category absent: 26
- study 121295428, outcome 'Assets', key value 0.358; category has 0 stored rows
  - the value is stored under: ['livestock']; e.g. ['Total number of poultry owned by househo']
  - the study stores these categories instead: ['consumption', 'empowerment', 'food_security', 'income', 'livestock', 'other']
- study 121295428, outcome 'Assets', key value 8.069; category has 0 stored rows
  - the value is stored under: ['income', 'livestock']; e.g. ['(4) Amount of income earned from egg sal']
  - the study stores these categories instead: ['consumption', 'empowerment', 'food_security', 'income', 'livestock', 'other']

### extracted under a different category: 33
- study 121058356, outcome 'Tontine/AVEC savings (3 months, USD)', key value 0.72; category has 36 stored rows
  - the value is stored under: ['agriculture', 'other']; e.g. ['Days spent in agriculture', 'Capital (Followup 1, 6 months after cash']
  - the study stores these categories instead: ['agriculture', 'assets', 'business', 'consumption', 'education', 'employment']
  - stored outcomes near the key name: ['Other savings (3 months, USD)', 'Other savings (3 months, USD)']
- study 121058356, outcome 'Tontine/AVEC savings (3 months, USD)', key value 1.32; category has 36 stored rows
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

