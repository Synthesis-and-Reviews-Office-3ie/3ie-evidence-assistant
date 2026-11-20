-- The estimation method is its own field, so it stops landing in the outcome or the arm.
-- The subgroup column already exists.
ALTER TABLE public.effect_estimates
    ADD COLUMN IF NOT EXISTS estimation_method text;
