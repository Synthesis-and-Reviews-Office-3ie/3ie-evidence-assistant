-- Per-project document counts and per-user usage totals, aggregated in Postgres.
--
-- The admin dashboards read these tables row by row through PostgREST, whose response
-- is capped at 1,000 rows (the project's Max Rows setting). A project with more
-- documents than that made the counts wrong. Returning one row per project or user
-- keeps the response small however large the tables grow.

create or replace function public.document_counts_by_project()
returns table (project_id uuid, doc_count bigint, chunk_count bigint)
language sql
stable
set search_path = ''
as $$
    select d.rag_project_id,
           count(*)::bigint,
           coalesce(sum(d.chunk_count), 0)::bigint
    from public.documents d
    group by d.rag_project_id
$$;

create or replace function public.usage_by_user()
returns table (user_id uuid, queries bigint, cost numeric)
language sql
stable
set search_path = ''
as $$
    select u.user_id,
           count(*)::bigint,
           coalesce(sum(u.cost_usd), 0)::numeric
    from public.usage_logs u
    where u.user_id is not null
    group by u.user_id
$$;

grant execute on function public.document_counts_by_project() to service_role;
grant execute on function public.usage_by_user() to service_role;
