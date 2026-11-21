# The named audit faults: fix or explain, 2026-11-21

## Sulaiman 2015, one time point per row

Fixed. The reader merged two panels' times into one subgroup, "after 2 years - after 4 years". Each row
now keeps only its own time point: when the row label, its column or its outcome names one, it wins, and a
time on the model's subgroup that names a different point is dropped. `derive_subgroup` in
`src/extraction/table_structure.py` carries the change, with a test for both panels.

## Jalal 2009, the (A−B) sign

Not fixed. Table 3.10 prints `Control (%) A`, `Program (%) B`, `Benefit attributable to program (%) A-B`
and `Proportional benefit (A-B)/A`. The stored value is the printed `A−B` figure, 42.5 as printed. Calling
it a negative needs a rule that reads the outcome's direction, so that a fall in dissatisfaction is a
benefit. The reader has no such rule and adding one would also flip genuine positives, so the printed
value stands. The outcome label does keep `benefit attributable to program`, so the direction is recorded
for a reader.

## Rahman 2023, impact as a percent of the nonparticipant mean

Not fixed. The reader stores the printed cell. When the table's own column header names a percentage it is
kept in the outcome, as with Jalal 2009's `(benefit attributable to program, %)`. On this row the header
carries no percentage, so the value stands as a level. Distinguishing a percent-of-mean column from a level
column needs the header to say so; the reader cannot infer it.

## Chowdhury 2024, the GATES "most affected 20%"

Not fixed. No table holding `GATES` or `most affected` was parsed from this document, so the row is not in
the stored set to relabel. This is a table-recall gap, not a labelling one.

## Ara 2016, the food category

Not fixed. Table 4 is a descriptive intake table, "Mean per capita per day quantity of food intake", and its
parse is broken: a header row of food categories (`Cereals`, `Pulse`, ... `Miscellaneous`, `Total`) is
flattened into data rows. The reader does not attach `Miscellaneous` as a category because it never sees a
category header. The table also reports means and differences, not programme effects.

## Nicaragua 121319138, the stray "in 2005"

Partly fixed. A period that the row's own label already carries is no longer appended: `Measured economy in
2005` (Jalal 2009 page 60) no longer also gets `in 2005` as a subgroup. The change is in `derive_subgroup`,
with the label-that-is-the-period case left alone. The Nicaragua case at page 34, where the outcome is
`Total labor hours` and the period `in 2005` is not in its label, still stands: the reader cannot tell that
period from a genuine time point on that row.

## 121340926, the odds-ratio column

Partly fixed. The effect-size rule now labels the odds-ratio column `programme_effect`, so the column axis
no longer hides it. The row axis still reads `control_or_covariate` on some of these rows and the flag is
false for them, and the document's text is badly parsed, with outcome cells holding runs of numbers
(`- 0.71 - 0.45 - 0.31 ...`). The column role is fixed; the document needs a page read to settle the rest.

## Run-to-run stability

Three documents were each re-extracted twice with the current reader, and the stored cells compared by
address (page, cell row, cell column).

| Document | Run 1 cells | Run 2 cells | Turnover | Percent |
| --- | --: | --: | --: | --: |
| Roy 2015 | 133 | 153 | 32 | 20.1% |
| Raza 2018 | 126 | 129 | 11 | 8.3% |
| Emran 2014 | 10 | 10 | 0 | not informative |

Emran 2014 is read from page images, and its rows carry no cell address, so every row shares one address
and the comparison says nothing about it.

The turnover is above the 2% line, so the cause was checked. A paired in-memory reading of Roy 2015 (two
readings, nothing stored) gave an address turnover of 6.1% but a (page, outcome, value) turnover of 51.8%,
and the differing keys are label text, not numbers: run 1 has `spend themoney she earns` where run 2 has
`spend the money she earns`, both 0.105, and run 1 labels a row `Treatment impact on whether the main
female works and Keeps all of the income earned` where run 2 has `Keeps all of the income earned`, both
-0.077. The reader re-assembles the outcome label, and sometimes folds the arm into it, differently each
run, and it sometimes judges the same table a results table in one run and not the other.

So the churn is model-output variance, not the storage path: the numbers are largely stable, while the
address and the label text move. For an audit, match rows by cell address, and treat 5–20% address churn as
the reader's own variance. Two paired runs on one document do not bound it tightly.

