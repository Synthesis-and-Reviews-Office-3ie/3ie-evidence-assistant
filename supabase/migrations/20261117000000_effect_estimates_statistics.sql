-- The uncertainty figures the reader already extracts but the table had nowhere to keep.
--
-- A coefficient's second cell can be a standard error, a t statistic, a confidence interval or a p-value.
-- The standard error and the interval text were stored; the t statistic, the two interval bounds as numbers
-- and which kind the cell was were not, so a t-only table left no uncertainty figure and an interval could
-- not be queried. Null still means "not printed", never zero.
alter table public.effect_estimates
  add column if not exists t_stat double precision,
  add column if not exists ci_low double precision,
  add column if not exists ci_high double precision,
  add column if not exists se_kind text;

comment on column public.effect_estimates.se_kind is
  'What the second cell was: se, t or ci; null when the table printed none.';
comment on column public.effect_estimates.ci_low is
  'Lower bound of a printed confidence interval, as a number; ci_text keeps the printed form.';
