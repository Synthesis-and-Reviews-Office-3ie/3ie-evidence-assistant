# Ten-paper accuracy check (19 November 2026)

A held-out set. These ten documents are outside the 49 study documents, so the reader rules were not
developed against them and they carry no hand-typed key values. They test the reader on documents it
had not been tuned on.

The re-extraction ran at `8c8c913`. The working tree was `837ea3b`; `git diff 8c8c913 HEAD -- src/extraction/`
is empty, so the reader code is exactly `8c8c913`. Each document was re-extracted on its own, with
`prune` on.

## Documents

| Document | Rows carrying an address |
| --- | --- |
| b98a0422b2e2_PDFs_of_included_programs_121430610 | 1470 |
| 52f188437804_PDFs_of_included_programs_121378379 | 977 |
| ba83facff3d1_PDFs_of_included_programs_Bangladesh_-_all_BRAC_programs_BRAC_programs_(40)_Ara_(2021) | 647 |
| 70eedd447e8e_PDFs_of_included_programs_121295095 | 592 |
| a72b17099de1_PDFs_of_included_programs_Bangladesh_-_all_BRAC_programs_BRAC_programs_(40)_Emran_(2012) | 344 |
| e23a72cd85d8_PDFs_of_included_programs_121326829 | 643 |
| 701165f57f97_PDFs_of_included_programs_Bangladesh_-_all_BRAC_programs_BRAC_programs_(40)_Das_(2013) | 590 |
| fa42c26c3414_PDFs_of_included_programs_Bangladesh_-_all_BRAC_programs_BRAC_programs_(40)_Selim_(2020) | 434 |
| 9b89a1ab05bf_PDFs_of_included_programs_Bangladesh_-_all_BRAC_programs_BRAC_programs_(40)_Montoya_(2023) | 437 |
| 20883ddebbf3_PDFs_of_included_programs_Bangladesh_-_all_BRAC_programs_BRAC_programs_(40)_Rabbani_(2006) | 411 |

## Result

`evaluation/accuracy.py` reads each row's stored cell address and checks the value and the parameter
against the printed cell.

- Rows the metric calls table rows: 7,124
- Value matches the addressed cell: 6,521 of 6,523 (100.0%)
- Parameter matches: 2,487 of 2,511 printed parameters (99.0%), 11 printed but not stored

## The rows without an address are mostly not table rows

Of the 601 rows the metric records without an address, 288 are vision reads and 291 are rows the second
pass added without a unit index. The metric counts both as table rows because it does not read
`text_position`. The genuine table residual is 22 rows: 18 where the stored value repeats in the unit and
cannot be tied to a single cell, and 4 where the stored address falls outside the parsed table.

Excluding the vision and second-pass rows, 6,523 of 6,545 table rows carry an address (99.7%). Neither
residual cause is the data-row-as-header fault fixed in `8c8c913`, which was found in other papers; the
pending whole-table header fix would change no row in this set.

## Row count fell by 613

The ten documents held 7,764 rows before the run and 7,151 after, a fall of 613, because `prune` deleted
the old rows and the current reader did not reproduce all of them. Whether the removed rows were correct
is unverified, and they are not counted in the figures above.
