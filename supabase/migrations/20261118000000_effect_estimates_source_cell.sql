-- The printed cell a row was read from, located by its row and column labels.
--
-- Verification needs the exact cell, not a search of the page: a page holds several tables and panels repeat
-- row labels. The cell is looked up in the parsed table by the row and column the model named, and only stored
-- when that lookup is unique. Null means the cell could not be identified, which is reported rather than guessed.
alter table public.effect_estimates
  add column if not exists source_cell text;

comment on column public.effect_estimates.source_cell is
  'The printed cell this row was read from, as located in the parsed table; null when the lookup was ambiguous.';
