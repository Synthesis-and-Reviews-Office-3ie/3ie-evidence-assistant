# Table gallery

Worked examples of real tables from development impact evaluations. Each entry pairs a table from one of the 49
mapped study documents with the correct answer: which cells are stored as programme effects, with which labels,
and which cells are left out and why. The table reader will receive the two or three closest entries as
few-shot examples.

## Status

26 entries, 464 stored rows. Built on 21–22 November 2026 from the 49 mapped documents only. No test document
(the fresh tens and the never-used set) is in the gallery. Every stored number was read from the rendered page
and checked a second time against the crop by an independent reviewer. All entries are still `status: "draft"`
until Lucas signs them off on the review page.

## Commands

```bash
python scripts/validate_gallery.py      # structure check, exit code 1 on any error
python scripts/render_gallery.py        # crops into images/ and writes review.html
```

`images/` and `review.html` are git-ignored. They hold crops of published pages and are re-made from the JSON.

## What the entries cover

| Group | Entries |
| --- | --- |
| Trial designs | several arms, ANCOVA with control mean, ITT next to TOT, treatment-by-subgroup interactions, p-value column, arms and rounds down the rows |
| Non-randomised designs | matching estimators side by side, participation probit (nothing stored), DiD next to the follow-up difference, regression DiD terms, change in effect between rounds, means table (nothing stored), benefit-cost table |
| Special estimates | IV second stage with an effect size, Lee bounds, quantile effects, q-values, with and without controls, logit marginal effects |
| Formats and populations | odds ratios (flipped), z-score index beside raw outcomes, % of control mean, spillover on non-eligible households, subgroups set by sub-headings, detached minus signs |
| Picture matters | a sideways table whose text layer moves numbers between rows (Bandiera 2017 Table III), sub-headings merged into rows, detached minus signs |

Not found in the 49 documents: a printed IV first stage of programme take-up, regression discontinuity,
synthetic control, event studies, machine-learning heterogeneity (GATES), mediation, and a text layer that
replaces the minus sign with another character. New papers are needed for these.

## Rules the entries follow

Lucas's decisions of 20–22 November 2026:

- Store the programme effect for each arm, round, subgroup and specification shown.
- ITT and TOT/LATE: both, with the estimand in `arm`.
- IV first stage: stored, `effect_type: "first stage"`.
- Lee or Manski bounds: on the main effect row (`bound_lower`, `bound_upper`, `bound_type`, with SEs). Other bound
  pairs go in `other_bounds`. Bounds are never separate rows and never confidence intervals.
- Adjusted and unadjusted estimates, and quantile effects: all stored, labelled. `preferred: true` only where the
  authors name a preferred specification.
- A DiD wins over a plain follow-up difference for the same outcome.
- Change in effect between rounds: `effect_type: "change in effect between rounds"`.
- Contrasts between two programme arms: `effect_type: "difference between arms"`, both arms named.
- Interaction terms: `effect_type: "difference in effect between subgroups"`. The summed subgroup effect is never
  computed.
- Standardised effect-size columns: `effect_type: "standardised effect size"`, signed. An outcome that is itself a
  z-score index is `main`, with its unit in the outcome label.
- % of control mean: `effect_type: "percent change vs control mean"`, value in per cent.
- Reversed conventions: store in the programme-minus-comparison direction. For a ratio this is the reciprocal.
  The printed value goes in `note`.
- The same effect reported twice (a reprint of an earlier round of the same experiment, or a rescaled copy in a
  cost table): stored in both places and linked with `linked_to`.
- Never stored: a before-after change in the treated group only, an RCT endline difference in means when the
  paper estimates the same outcome by regression, control or covariate terms, fixed effects and dummies,
  constants, balance tests and pre-programme gaps, group means, p-values, q-values, t-statistics, F-tests, R², N,
  correlations, costs and cost ratios, sensitivity statistics, and results the paper reports from another study.
- Stars are recorded in `stars` only when no SE, t or p is printed.

## Entry format

Each file `entries/<id>.json` has `id`, `status`, `checked_against_page`, `source` (`doc_key`, `pdf` relative to
`data/PDFs of included programs/`, `page`, `table_label`, `bbox_points` in PDF points, `render_rotation`),
`tags` (`method`, `format`, `layout`, optional `picture_matters`), `snippet`, `context_needed`, `stored_rows`,
`not_stored`, `rule`, and `resolved_questions` where a decision settled a question.

Row fields: `outcome`, `arm`, `time_point`, `subgroup_or_population`, `value`, `se`, `effect_type`, and where
they apply `specification`, `preferred`, `ci_lower`, `ci_upper`, `t_stat`, `bound_lower`, `bound_upper`,
`bound_type`, `other_bounds`, `stars`, `linked_to`, `note`.
