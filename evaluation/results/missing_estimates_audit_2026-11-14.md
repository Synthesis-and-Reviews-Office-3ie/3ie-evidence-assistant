# Missing-estimate audit

Why hand-typed values have no exact match in the stored rows.

## Estimate

Exact match 278 of 325 (86%). Breakdown:

| Why | Count |
| --- | --- |
| rounding 2dp | 2 |
| rounding 1% | 1 |
| sign | 1 |
| outcome present, value differs | 1 |
| missing | 42 |

Samples, rounding 2dp:
- 121058367: Total consumption expenditure per month per adult equivalent = -0.049 (1f44cd8c70b8_PDFs_of_included_)
- 122182715: Savings value (2024 PPP) = 192.975 (792bc37d6275_PDFs_of_included_)

Samples, rounding 1%:
- 122182715: Monthly household income (2024 PPP) = 57.645 (792bc37d6275_PDFs_of_included_)

Samples, sign:
- 121294795: Expenditure = 92.8 (4c9d6fa93352_PDFs_of_included_)

Samples, outcome present, value differs:
- 122182716: Cash savings (BDT) = 1664.0 (8e7ad75de1f2_PDFs_of_included_)

Samples, missing:
- 121295229: Expenditure = 2.404 (cc6acb106d4b_PDFs_of_included_)
- 121305126: Income = -0.59 (63bcc2c07899_PDFs_of_included_)
- 121327988: Income = 2501.179 (d6f0a637496f_PDFs_of_included_)
- 121328483: Consumption Index = 0.05 (7fe6b0bbcef3_PDFs_of_included_)
- 121328483: Asset Value Index = 0.11 (7fe6b0bbcef3_PDFs_of_included_)

## Se

Exact match 263 of 305 (86%). Breakdown:

| Why | Count |
| --- | --- |
| rounding 1% | 1 |
| scale x100 | 1 |
| outcome present, value differs | 1 |
| missing | 39 |

Samples, rounding 1%:
- 121295641: Expenditure = 4.24 (a16f5d6f97c3_PDFs_of_included_)

Samples, outcome present, value differs:
- 122182715: Monthly household income (2024 PPP) = 16.96 (792bc37d6275_PDFs_of_included_)

Samples, missing:
- 121305126: Income = 0.53 (63bcc2c07899_PDFs_of_included_)
- 121327988: Income = 691.179 (d6f0a637496f_PDFs_of_included_)
- 121328483: Consumption Index = 0.036 (7fe6b0bbcef3_PDFs_of_included_)
- 121328483: Asset Value Index = 0.066 (7fe6b0bbcef3_PDFs_of_included_)
- 121328483: Income Index = 0.054 (7fe6b0bbcef3_PDFs_of_included_)
