-- The row and column of the printed cell, found by matching the cell's own text in the parsed table.
--
-- Labels repeat across panels and wrap across lines, so a label cannot always identify a cell. The text of
-- the cell itself can: at extraction time the estimate's printed cell is matched against the parsed grid and
-- its position recorded when that text occurs exactly once. Null means the text occurred more than once, so no
-- position was guessed.
alter table public.effect_estimates
  add column if not exists cell_row integer,
  add column if not exists cell_column integer;

comment on column public.effect_estimates.cell_row is
  'Row position of the printed cell in the parsed table, from zero; null when the cell text was not unique.';
