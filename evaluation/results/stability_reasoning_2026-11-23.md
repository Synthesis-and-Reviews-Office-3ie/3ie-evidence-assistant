# Stability on Roy 2015 and Raza 2018, reasoning low against off, 2026-11-23

Each document was read twice at each reasoning setting, in memory, with nothing stored. Address turnover is
the share of cell addresses present in one run and not the other. Label turnover is the share of shared
addresses whose outcome label differs, after lower-casing and stripping punctuation.

| Document | Setting | Run 1 rows | Run 2 rows | Address turnover | Label turnover | Cost |
| --- | --- | --: | --: | --: | --: | --: |
| Roy 2015 | low | 111 | 111 | 0.0% | 65.8% | $0.26 |
| Roy 2015 | off | 77 | 95 | 26.3% | 61.6% | $0.16 |
| Raza 2018 | low | 85 | 77 | 13.8% | 28.0% | $0.23 |
| Raza 2018 | off | 95 | 82 | 13.7% | 43.9% | $0.15 |

## Reading

Turning reasoning off is cheaper, about $0.15 against $0.23 to $0.26 for two readings, and it is less stable:
Roy's address turnover goes from 0% to 26.3%, and Raza's label turnover from 28.0% to 43.9%. The reader
already ran at the lowest reasoning effort, so "off" is the only cheaper setting and it is not a trade worth
making.

Neither setting fixes the label churn. Even at low, the labels differ across runs for 66% of Roy's shared
addresses, which matches the earlier paired reading. The address churn and the label churn are both model
output variance, and the fix is the code-taken outcome label, not the reasoning setting.

One reading of one document is not a bound. The numbers here are a fair comparison of the two settings and
nothing more.
