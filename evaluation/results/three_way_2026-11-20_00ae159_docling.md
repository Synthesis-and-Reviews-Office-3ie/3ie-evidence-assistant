# Docling score at `00ae159`

Code at `00ae159`. The 49 Docling documents were re-extracted at `5c20164`; the stored outcome names were then backfilled from the saved tables with the outcome-in-columns rule, no re-extraction and no model call. MinerU and the union were not re-extracted.

Extraction window: 2026-11-19T19:57 to 2026-11-19T22:49.

| Source | Canonical + value | Exact name + value | Token overlap + value | Canonical SE + value | Outcome present | Stored rows |
| --- | --- | --- | --- | --- | --- | --- |
| Docling | 378/439 | 172/439 | 285/439 | 339/409 | 413/439 | 16458 |

Before the backfill, at `5c20164`: coefficient 378/439, SE 339/409.
After the backfill: coefficient 378/439, SE 339/409. Exact-name matches rose from 168 to 172; canonical
and SE did not move.

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

The canonical score did not move because the renamed rows were already in the key's category. The 61
misses below are category-mapping cases, not layout cases: the value is stored under a name the category
mapper does not connect to the key outcome.

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

