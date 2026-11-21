-- Proposed, not applied. Lucas asked to see the migration before it runs against Supabase.
--
-- ITT and TOT/LATE are both stored with their estimand. The IV first stage is stored and labelled. Lee and
-- Manski bounds are not confidence intervals: they sit on the main effect row in bound_lower/bound_upper/
-- bound_type, not as separate effects. Adjusted and unadjusted estimates and each quantile are all stored and
-- labelled; the paper's preferred specification is marked. Nothing here is not-null, so existing rows are
-- unaffected.

ALTER TABLE public.effect_estimates
    ADD COLUMN IF NOT EXISTS estimand text,
    ADD COLUMN IF NOT EXISTS stage text,
    ADD COLUMN IF NOT EXISTS specification text,
    ADD COLUMN IF NOT EXISTS quantile text,
    ADD COLUMN IF NOT EXISTS preferred boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS bound_lower double precision,
    ADD COLUMN IF NOT EXISTS bound_upper double precision,
    ADD COLUMN IF NOT EXISTS bound_type text;

COMMENT ON COLUMN public.effect_estimates.estimand IS
    'ITT, TOT, LATE or ATE; ITT is used first in synthesis.';
COMMENT ON COLUMN public.effect_estimates.stage IS
    'first or second, for an IV estimate; a first stage is not a programme effect on an outcome.';
COMMENT ON COLUMN public.effect_estimates.specification IS
    'adjusted or unadjusted, or the printed specification name.';
COMMENT ON COLUMN public.effect_estimates.quantile IS
    'the quantile the estimate is for, when the table reports quantile effects.';
COMMENT ON COLUMN public.effect_estimates.preferred IS
    'true for the specification the paper states as preferred.';
COMMENT ON COLUMN public.effect_estimates.bound_lower IS
    'lower Lee or Manski bound on the main effect row; null unless the table reports a partial-identification bound.';
COMMENT ON COLUMN public.effect_estimates.bound_upper IS
    'upper Lee or Manski bound on the main effect row; null unless the table reports a partial-identification bound.';
COMMENT ON COLUMN public.effect_estimates.bound_type IS
    'Lee or Manski, and the trimming or monotonicity assumption the authors name.';
