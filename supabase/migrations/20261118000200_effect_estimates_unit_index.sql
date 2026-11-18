-- Which view of the table a row was read from.
--
-- A wide table is read as several small tables, one per estimate column. The cell position refers to the
-- view, not to the table on the page, so the view identity is needed to open the cell again. The index is the
-- position of the view in the order the reader produced it for its document.
alter table public.effect_estimates
  add column if not exists unit_index integer;

comment on column public.effect_estimates.unit_index is
  'Position of the table view in the reader''s order for the document; with cell_row and cell_column it addresses the printed cell.';
