-- The consistency flags a row failed when it was written.
--
-- The stored numbers must satisfy arithmetic: t is the coefficient over its standard error, the p-value follows
-- from t, the interval sits around the coefficient, and the arms cannot exceed the sample. A flag records that a
-- check failed and which field was dropped, so a reader knows what was printed and what was not stored.
alter table public.effect_estimates
  add column if not exists quality_flags text;
