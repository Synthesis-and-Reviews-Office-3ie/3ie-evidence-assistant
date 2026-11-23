-- Proposed, not applied. Lucas asked to see the migration before it runs against Supabase.
--
-- Labels stop carrying structure: the time point, the specification, the estimand and the quantile move to
-- their own columns, so a round no longer has to be baked into the outcome text. A bounds pair sits on the
-- main effect row rather than becoming its own effect. effect_type says what kind of effect a row is.
-- preferred is null when the authors did not name one, which is not the same as false.
--
-- Every column is nullable or has a default, so existing rows are unaffected.

ALTER TABLE public.effect_estimates
    ADD COLUMN IF NOT EXISTS estimand text,
    ADD COLUMN IF NOT EXISTS specification text,
    ADD COLUMN IF NOT EXISTS quantile text,
    ADD COLUMN IF NOT EXISTS time_point text,
    ADD COLUMN IF NOT EXISTS effect_type text,
    ADD COLUMN IF NOT EXISTS preferred boolean,
    ADD COLUMN IF NOT EXISTS linked_to text,
    ADD COLUMN IF NOT EXISTS bound_lower double precision,
    ADD COLUMN IF NOT EXISTS bound_upper double precision,
    ADD COLUMN IF NOT EXISTS bound_lower_se double precision,
    ADD COLUMN IF NOT EXISTS bound_upper_se double precision,
    ADD COLUMN IF NOT EXISTS bound_type text,
    ADD COLUMN IF NOT EXISTS other_bounds jsonb,
    ADD COLUMN IF NOT EXISTS stars integer;

COMMENT ON COLUMN public.effect_estimates.estimand IS
    'ITT, TOT, LATE or ATE; ITT is used first in synthesis.';
COMMENT ON COLUMN public.effect_estimates.specification IS
    'adjusted or unadjusted, or the printed specification name (for example D4, D5).';
COMMENT ON COLUMN public.effect_estimates.quantile IS
    'the quantile the estimate is for, when the table reports quantile effects.';
COMMENT ON COLUMN public.effect_estimates.time_point IS
    'the round or period, as printed (for example 2005, after 2 years).';
COMMENT ON COLUMN public.effect_estimates.effect_type IS
    'main, difference between arms, change in effect between rounds, percent change vs control mean, '
    'odds ratio, standardised effect size, first stage, or difference in effect between subgroups.';
COMMENT ON COLUMN public.effect_estimates.preferred IS
    'true for the specification the authors name as preferred; null when they do not say.';
COMMENT ON COLUMN public.effect_estimates.linked_to IS
    'the row_key of another row holding the same effect (a reprint of an earlier round, or a rescaled copy).';
COMMENT ON COLUMN public.effect_estimates.bound_lower IS
    'lower Lee or Manski bound on the main effect row; null unless the table reports a partial-identification bound.';
COMMENT ON COLUMN public.effect_estimates.bound_upper IS
    'upper Lee or Manski bound on the main effect row; null unless the table reports a partial-identification bound.';
COMMENT ON COLUMN public.effect_estimates.bound_lower_se IS
    'standard error of the lower bound, where printed.';
COMMENT ON COLUMN public.effect_estimates.bound_upper_se IS
    'standard error of the upper bound, where printed.';
COMMENT ON COLUMN public.effect_estimates.bound_type IS
    'Lee or Manski, and the trimming or monotonicity assumption the authors name.';
COMMENT ON COLUMN public.effect_estimates.other_bounds IS
    'further bound pairs, as a JSON object, when the table prints more than one.';
COMMENT ON COLUMN public.effect_estimates.stars IS
    'the number of significance stars, recorded only when no SE, t or p is printed.';
