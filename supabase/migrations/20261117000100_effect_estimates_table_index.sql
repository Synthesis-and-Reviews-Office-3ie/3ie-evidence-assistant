-- Which table on its page a row came from, so a value can be checked against the exact cell.
--
-- A page often holds several tables, and panel tables repeat a row label in each panel. Without a table
-- identity a verifier cannot tell which cell a stored value should equal, and a reader cannot either. The
-- index is the position of the table among the tables on its page, counting from zero.
alter table public.effect_estimates
  add column if not exists table_index integer;

comment on column public.effect_estimates.table_index is
  'Position of the source table among the tables on its page, from zero; null on rows extracted before this.';
