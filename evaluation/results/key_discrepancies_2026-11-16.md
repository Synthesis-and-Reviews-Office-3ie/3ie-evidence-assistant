# Key discrepancies for correction

Five hand-typed cells do not match what their papers print. In each case the paper's value is the one the
extractor stored, and the sheet's value is the outlier. Correcting these five raises measured recall from
305 to 307 of 325 estimates and from 284 to 287 of 305 standard errors; after that, every value that is in
the collection is found, and the only remainder is the 36 values for paper 121766336 whose source table is
not held.

Each row gives the sheet's value, the printed value, and where the sheet says its value came from.

| Study | Sheet | Printed | Field | Sheet's source |
| --- | --- | --- | --- | --- |
| 122182715 | 57.645 | 67.645 | estimate | Page 19, Table 1, Panel A Uganda, row individual coaching, column monthly household income. The store holds 67.645 (9.574) from page 21 and the printed table shows 67.645, so the sheet's first digit is wrong. Table 1 was checked by eye on 16 November. |
| 122182715 | 16.96 | 16.698 | standard error | Same table, Panel C Bangladesh, row group coaching. The coefficient 61.221 matches the print exactly; the paper contains no value beginning 16.9. |
| 121327988 | 691.179 | 691.149 | standard error | Page 27, Table 1.4, non-parametric RD, row RD_Estimate, column Income, ML. The estimate 2501.179 matches the print exactly, so the standard error is one digit out in the last place. |
| 121295641 | 4.24 | 4.224 | standard error | Page 38, Table 3, row consumption per capita, column treatment. The estimate 24.027 matches the print exactly. Table 3 was checked by eye on 16 November and prints 4.224. |
| 122182715 | 192.975 | 192.974 | estimate | Page 44, Table A.12, Panel A Uganda, row group coaching. The sheet names the column any saving, but that column prints 0.090; the value belongs to savings value (2024 PPP), which is the outcome the store records. Checked by eye on 16 November: the printed value is 192.974, so the sheet is one digit out. |

What this means: none of these are extraction failures. Three are one-digit slips in a hand-typed cell
(57.645 for 67.645, 691.179 for 691.149, 192.975 for 192.974), one is a standard error rounded differently
(4.24 for 4.224), and one is a standard error that does not appear in the paper at all. The paper's printed
value is what the store holds in every case. Two of the printed values, Table 1 of 122182715 and Table 3 of
121295641, were checked by eye on 16 November.

The sheet is the data owner's record, so the correction belongs there rather than in the extraction code.
Once it is made, `evaluation/quality_gate.py --update-baseline` records the new figures.

The 36 values for 121766336 are a separate matter. Their source table is not in any public copy of the
work: the policy brief held is the 12-page version whose results are figures, the July 2026 J-PAL brief is
4 pages with no tables, and the working paper prints rounded values (107 (148) for monthly income against
the sheet's 155.4295 (121.73)). Obtaining the table the coder used, or the authors' regression output, is
the only route; until then the retrieval queue keeps the study listed and the attainable denominator
excludes it.
