# Fixes from the independent audit, 2026-11-20

## Run

The 16 audited documents were re-extracted, prune on, one at a time, at commit `847b6ec` (number, flag and
label fixes) and `f3df136` (page read for a mangled minus). Fifteen documents wrote in the first pass. One, `58622f89cbec` (121340926), failed its write and restored the rows from the earlier run; it was
re-extracted alone, and wrote 72 rows. One document, `6b4e8eccf0e1` (121346575), was re-extracted twice to
settle the page-read question below. Total cost $1.15, under the $3 cap.

## How the audited rows changed

The 60 sampled cells cannot be followed one by one: the reader now addresses 7 of them at a different cell,
so a comparison by cell address pairs the wrong rows. Each named defect was checked in the re-extracted
rows instead.

| Audit defect | Document | Before | After |
| --- | --- | --- | --- |
| Mangled minus stored positive | 121346575 | `Experienced emotional abuse` 0.005, `Experienced physical violence` 0.014 | −0.005 and −0.014 |
| Mangled minus stored positive | Emran 2014 | `Ratio of saris to lungis` 2.01, `Number of big trees` positive | −0.01, and big trees −0.22 to −1.04 |
| Leading decimal lost | Emran 2014 | `.92` stored as 92 | `.92` read as a value below 1 |
| Subgroup row hidden | Jalal 2013 | age groups 6-11, 12-23, 24-35 mo `not_an_effect`, flag false | role `subgroup`, flag true |
| Subgroup row hidden | Raza 2018 | `Non-poor households` the outcome, `not_an_effect`, flag false | role `subgroup`, flag true |
| Arm stored as the outcome | Hossain 2017 | outcome `Treatment X 2009` | outcome `Study`, arm `Treatment X 2009` |
| Time point lost | Sulaiman 2015 | `after 2 years` dropped | kept in the subgroup: `after 2 years - after 4 years` |
| Population lost | Bandiera 2011 | spillover stored like the main effect | subgroup `other poor women` |
| Arm lost | Rahman 2023 | arm empty | `Difference (grants-only ...)` kept |

## The page read on Emran 2014

The audit found that the rendered-page reading did not run on Emran 2014. The reason: the garbled-text test
recognised a run of question marks and a font-mapping pattern like `a114`, but Emran's mis-mapped
punctuation `ð .01Þ` and `½.62, .71` matched neither, so the table was treated as readable and read from the
text layer, where the minus is the digit `2`. The test now also marks a table that carries such a glyph
before a number. Fourteen of Emran's seventeen tables now route to the page image, and its negative cells
come back with the sign.

## What this does not settle

- The role flag is absent on rows read from the page image (Emran 2014, 121346575): the vision reader does
  not label roles, and those rows keep on the open default. They are kept, which is right for the real
  effects here, but the flag carries no information for them.
- Row selection varies between runs. Cell `121346575` `Has knowledge about contraceptives` was not extracted
  in the final run, so the third mangled-minus value named in the audit (−0.004) is not present to check.
  The other two are fixed.
- This is a fixes report, not a new audit. The flag's precision and recall against the printed pages are not
  re-measured here.
