-- The position of the standard error cell, so a parameter printed in the row beneath can be verified too.
--
-- Cells mostly hold the coefficient with its standard error in parentheses, but many papers print the error on
-- the row beneath or in the next column. The address is accepted only when it is adjacent to the coefficient
-- and its cell holds a number, so a wrong pairing is refused rather than stored.
alter table public.effect_estimates
  add column if not exists se_row integer,
  add column if not exists se_column integer;
