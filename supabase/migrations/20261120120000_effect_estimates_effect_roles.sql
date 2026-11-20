-- The two axes of each cell are labelled, with a flag for whether they make a programme effect. The
-- flag fails open: a cell is marked not-an-effect only when an axis is explicitly a non-effect role.
-- Nothing is dropped here; the flag is stored and the drop threshold is set later.
ALTER TABLE public.effect_estimates
    ADD COLUMN IF NOT EXISTS row_role text;
ALTER TABLE public.effect_estimates
    ADD COLUMN IF NOT EXISTS column_role text;
ALTER TABLE public.effect_estimates
    ADD COLUMN IF NOT EXISTS keep_effect boolean NOT NULL DEFAULT true;
