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

