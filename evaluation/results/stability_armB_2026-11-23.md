# Arm B stability on Roy 2015 and Raza 2018, 2026-11-23

Arm B is the reader with the study card and the gallery examples. Each document was read twice, in memory,
with nothing stored. Address turnover is the share of cell addresses present in one reading and not the
other. Label turnover is the share of shared addresses whose stored outcome differs.

| Document | Run 1 rows | Run 2 rows | Address turnover | Label turnover | Cost |
| --- | --: | --: | --: | --: | --: |
| Roy 2015 | 109 | 107 | 5.4% | 7.6% | $0.42 |
| Raza 2018 | 117 | 95 | 18.8% | 35.8% | $0.32 |

Target: under 2% for both.

## Reading

The code-taken outcome label works on Roy: its label turnover fell from 66% without the card to 7.6% with
it, because the label is now copied from the table cell rather than re-written. But neither document reaches
2%, and Raza is far off at 18.8% address and 35.8% label turnover. The number of rows found also moves
between readings (117 against 95), so on Raza the instability is in which rows the tables yield, not only in
the label text. The card fixes the label on a table that is read the same way twice; it does not yet make the
row selection itself repeatable.

So the card is a large improvement on one paper and not a solution on the other. The next step is to find
which Raza tables change between readings and why, before claiming the 2% target is reachable.
