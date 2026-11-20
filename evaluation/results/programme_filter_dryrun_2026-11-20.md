# Programme-effect filter dry run on the 49 (20 November 2026)

No model call. The cleaned rules were applied to the 15,852 stored rows of the 49 study documents, using
the printed row label and the whole-table view. The model's row role is not in the stored rows, so this
is the code-only check; in a new extraction the model role is the primary decision.

The rules were cleaned first: no hard-coded years (2002/2005/2006), no study-specific `sup nsup`, and a
year alone does not make a term a control. `is_programme_term("SUP 2005")` is true.

## Result

- Rows the code rules would remove: **49**
  - 36 regression control terms in a term table
  - 13 balance-table rows
- Hand-key hits among the removed rows: **0 coefficients, 0 SEs**.
- Implied recall: **396/439** and **354/409**, unchanged from the current stored score.

The earlier candidate removal at `63bcc2c07899` (Africare, -0.59) was a false positive: a results table
whose `Constant` row made the term guard fire. Excluding non-outcome rows from the guard keeps it, and
it was the only key hit in the previous run.

The 49 have no stored `SUP 2005` row (Krishna 2010 is one of the fresh documents); the unit test
`test_regression_terms_keep_only_the_programme` covers it.

## Reader and prompt changes

- The prompt no longer calls a before/after comparison a results table, and `Endline` is no longer an
  arm example. It states that a before/after comparison without a comparison group is not a programme
  effect.
- The prompt asks the model for a `role` on each regression row: `programme_term`, `control`,
  `fixed_effect` or `baseline_gap`.
- The reader keeps a row when the model says `programme_term`. When the model says a non-programme role
  but the code check says programme, it keeps the row and records a `role disagreement` in the run log,
  rather than silently dropping a possible effect. The code rules are a check now.
