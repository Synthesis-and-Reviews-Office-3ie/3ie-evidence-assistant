-- Rekey the table with the outcome normalisation in src/extraction/identity.py.
--
-- The first key used the outcome as written, so a run that called the same outcome "Per capita
-- consumption" and "Per capita consumption (2)" on two passes stored the estimate twice: paper 121295229
-- held 292 rows for 135 distinct values. The key now strips a leading table, panel or column marker and a
-- trailing bare column number, then the duplicates collapse.

alter table public.effect_estimates drop constraint if exists effect_estimates_doc_row_key;
drop index if exists public.effect_estimates_doc_row_key;

update public.effect_estimates
   set row_key = md5(concat_ws('|',
         source,
         coalesce(page::text, ''),
         btrim(regexp_replace(regexp_replace(
             regexp_replace(lower(btrim(coalesce(outcome_name, ''))), '\s+', ' ', 'g'),
             '^\s*(panel\s+[a-z0-9]+\s*[:.-]?|\(\d{1,2}\)\s*[:.-]?|table\s+[a-z0-9]+\s*[:.-]?)\s*', '', 'i'),
           '\s*\(\s*(\d{1,2}|[ivx]{1,3})\s*\)\s*$', '', 'i'), ' .:;-'),
         regexp_replace(lower(btrim(coalesce(treatment_arm, ''))), '\s+', ' ', 'g'),
         regexp_replace(lower(btrim(coalesce(subgroup, ''))), '\s+', ' ', 'g'),
         coalesce(((round(effect_size::numeric, 9)) * 1000000000)::bigint::text, '')));

delete from public.effect_estimates a
 using public.effect_estimates b
 where a.ctid < b.ctid
   and a.rag_project_id = b.rag_project_id
   and a.doc_key = b.doc_key
   and a.row_key = b.row_key;

create unique index if not exists effect_estimates_doc_row_key
  on public.effect_estimates (rag_project_id, doc_key, row_key);
