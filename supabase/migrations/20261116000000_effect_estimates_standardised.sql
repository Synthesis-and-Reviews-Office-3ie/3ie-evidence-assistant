-- Standardised effect sizes, computed from control_sd and the per-arm counts by
-- src/extraction/effect_sizes.py and written by the extraction step.
-- Null means an input was missing; it is never an estimate of zero.
alter table public.effect_estimates
  add column if not exists effect_size_d double precision,
  add column if not exists var_d double precision,
  add column if not exists hedges_g double precision,
  add column if not exists var_g double precision,
  add column if not exists se_g double precision;

comment on column public.effect_estimates.hedges_g is
  'Hedge''s g, the small-sample-corrected d; equal to yi for a single study.';
comment on column public.effect_estimates.var_g is
  'variance of g (vi), used as the meta-analytic weight.';
