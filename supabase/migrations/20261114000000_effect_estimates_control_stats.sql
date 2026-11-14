-- Inputs needed for standardised effect sizes (d, yi, se_g) in src/extraction/effect_sizes.py.
-- Extraction must read these from the table and store them before standardisation can run.
alter table public.effect_estimates
  add column if not exists control_mean double precision,
  add column if not exists control_sd double precision,
  add column if not exists n_treatment integer,
  add column if not exists n_control integer;

comment on column public.effect_estimates.control_sd is
  'Control-group standard deviation of the outcome, when the table prints it; used to standardise.';
