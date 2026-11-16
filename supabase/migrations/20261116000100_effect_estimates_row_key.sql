-- A stable identity per stored estimate, so a re-extraction upserts instead of replacing.
--
-- Extraction used to delete a document's rows and insert a new set, which made recall depend on a
-- stochastic read: a run that failed to reproduce a row lost it, and the weekly gate caught one such
-- loss (304 to 303). With this key a run updates rows it recognises, adds rows it finds for the first
-- time, and leaves alone rows it did not reproduce; retiring those is a separate, explicit act.
--
-- The formula matches src/extraction/identity.py: source, page, outcome, arm, subgroup and the estimate
-- as an integer in units of 1e-9, lower-cased and whitespace-collapsed, pipe-joined and hashed with md5.
-- The estimate is rendered as an integer because float-to-text does not agree between Python and Postgres
-- for small numbers, and the two sides have to compute the same key.

alter table public.effect_estimates add column if not exists row_key text;

update public.effect_estimates
   set row_key = md5(concat_ws('|',
         source,
         coalesce(page::text, ''),
         regexp_replace(lower(btrim(coalesce(outcome_name, ''))), '\s+', ' ', 'g'),
         regexp_replace(lower(btrim(coalesce(treatment_arm, ''))), '\s+', ' ', 'g'),
         regexp_replace(lower(btrim(coalesce(subgroup, ''))), '\s+', ' ', 'g'),
         coalesce(((round(effect_size::numeric, 9)) * 1000000000)::bigint::text, '')))
 where row_key is null;

-- Old runs could store the same estimate twice (the repaired-page double read). The unique index needs
-- one row per identity, so the extra copies go, keeping one.
delete from public.effect_estimates a
 using public.effect_estimates b
 where a.ctid < b.ctid
   and a.rag_project_id = b.rag_project_id
   and a.doc_key = b.doc_key
   and a.row_key = b.row_key;

alter table public.effect_estimates alter column row_key set not null;

create unique index if not exists effect_estimates_doc_row_key
  on public.effect_estimates (rag_project_id, doc_key, row_key);

comment on column public.effect_estimates.row_key is
  'Stable identity of the estimate (source, page, outcome, arm, subgroup, value), used to upsert.';
