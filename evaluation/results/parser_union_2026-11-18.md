# Parser comparison on the poverty graduation collection

Test set: 43 studies, 442 outcome rows with a hand-typed key.

`Value anywhere` is the inflated count (a hand value appears among any stored value in the
document). `Exact + value` requires the same normalised outcome name; `Fuzzy + value` allows
token overlap in the outcome names. The last two are the honest recalls.

| Source | Value anywhere (est) | Exact + value (est) | Fuzzy + value (est) |
| --- | --- | --- | --- |
| Docling | 395/442 (89%) | 150/442 (34%) | 216/442 (49%) |
| MinerU | 395/442 (89%) | 136/442 (31%) | 208/442 (47%) |
| Union | 400/442 (90%) | 164/442 (37%) | 221/442 (50%) |

| Source | Exact + value (SE) | Fuzzy + value (SE) | Outcome exact | Outcome fuzzy | Stored rows |
| --- | --- | --- | --- | --- | --- |
| Docling | 138/412 (33%) | 195/412 (47%) | 206/442 (47%) | 301/442 (68%) | 14495 |
| MinerU | 121/412 (29%) | 185/412 (45%) | 201/442 (45%) | 270/442 (61%) | 15383 |
| Union | 151/412 (37%) | 197/412 (48%) | 220/442 (50%) | 308/442 (70%) | 22740 |

## Why the exact joint match misses an estimate

**Docling** (226 misses)

| Reason | Rows |
| --- | --- |
| outcome missing | 141 |
| value differs (name variant) | 39 |
| outcome present, value differs | 33 |
| rounding 2dp | 8 |
| sign | 3 |
| rounding 1% | 1 |
| scale x1000 | 1 |

**MinerU** (234 misses)

| Reason | Rows |
| --- | --- |
| outcome missing | 172 |
| outcome present, value differs | 36 |
| value differs (name variant) | 13 |
| rounding 2dp | 8 |
| sign | 3 |
| rounding 1% | 1 |
| scale x1000 | 1 |

**Union** (221 misses)

| Reason | Rows |
| --- | --- |
| outcome missing | 134 |
| value differs (name variant) | 41 |
| outcome present, value differs | 36 |
| rounding 2dp | 8 |
| rounding 1% | 1 |
| scale x1000 | 1 |
