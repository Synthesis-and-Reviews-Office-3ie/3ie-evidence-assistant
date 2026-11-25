-- =============================================================================
-- App users: who owns rows, whichever system signed the user in
-- =============================================================================
-- P6 makes EvidenceLoop the one account system. Under option (b) of
-- docs/EVIDENCELOOP_AUTH_DESIGN.md, ownership moves from auth.users to this table.
--
-- This is migration A of two, and it is additive only. Nothing reads the table until the
-- EvidenceLoop flag is on, and no existing column, key or policy changes here.
-- Migration B (a later file) repoints the four auth.users foreign keys at app_users(id).
-- Do not turn EVIDENCELOOP_AUTH_ENABLED on before migration B is applied, because until then
-- an EvidenceLoop user's writes fail on the auth.users foreign keys.
--
--   * Every existing Supabase user gets a row whose id IS their auth.users id, so after
--     migration B no user_id value anywhere needs rewriting.
--   * A trigger gives each new Supabase sign-up its row, so migration B never meets a
--     user_id that app_users lacks.
--   * An EvidenceLoop user is keyed on (issuer, sub). OpenID Connect treats only that pair
--     as a stable identifier, and keying on it keeps a staging issuer's "42" apart from
--     production's "42".
--   * public.app_user_for_evidenceloop() finds or creates the row in one statement, safe
--     under concurrent first requests, and records when the user was last seen.
--   * Only the service role (the backend) can read the table or call the functions.
--
-- Rollback, valid until migration B is applied:
--   DROP TRIGGER IF EXISTS app_user_from_auth_user ON auth.users;
--   DROP FUNCTION IF EXISTS public.app_user_from_auth_user();
--   DROP FUNCTION IF EXISTS public.app_user_for_evidenceloop(text, text);
--   DROP TABLE IF EXISTS public.app_users;
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.app_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- EvidenceLoop identity: its JWT_ISSUER and the user's sub. Both set or both NULL.
    evidenceloop_issuer TEXT,
    evidenceloop_sub TEXT,

    -- Supabase Auth identity, kept for linking and for the transition. NULL for new users.
    supabase_user_id UUID UNIQUE,

    -- Profile details for the admin console. Not used for identity or for linking.
    email TEXT,
    display_name TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ,

    CONSTRAINT app_users_evidenceloop_identity UNIQUE (evidenceloop_issuer, evidenceloop_sub),
    CONSTRAINT app_users_evidenceloop_pair CHECK ((evidenceloop_issuer IS NULL) = (evidenceloop_sub IS NULL)),
    CONSTRAINT app_users_evidenceloop_nonempty CHECK (evidenceloop_issuer <> '' AND evidenceloop_sub <> ''),
    CONSTRAINT app_users_has_identity CHECK (evidenceloop_sub IS NOT NULL OR supabase_user_id IS NOT NULL)
);

COMMENT ON TABLE public.app_users IS
    'Who owns rows: an EvidenceLoop (issuer, sub), a Supabase Auth user, or both once linked (P6)';

ALTER TABLE public.app_users ENABLE ROW LEVEL SECURITY;
-- No policies: only service_role (which bypasses RLS) reads or writes. Revoke the default
-- grants as well, so a policy added by mistake later still exposes nothing.
REVOKE ALL ON public.app_users FROM anon, authenticated;
-- Stated, not left to Supabase's default privileges, because the functions below run as the
-- caller (the backend's service_role).
GRANT SELECT, INSERT, UPDATE, DELETE ON public.app_users TO service_role;

-- -----------------------------------------------------------------------------
-- Existing Supabase users: one row each, with the same id
-- -----------------------------------------------------------------------------
INSERT INTO public.app_users (id, supabase_user_id, email, created_at)
SELECT u.id, u.id, u.email, COALESCE(u.created_at, NOW())
FROM auth.users u
ON CONFLICT DO NOTHING;

-- -----------------------------------------------------------------------------
-- New Supabase sign-ups: a row at creation, so the later foreign keys always hold
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.app_user_from_auth_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    INSERT INTO public.app_users (id, supabase_user_id, email, created_at)
    VALUES (NEW.id, NEW.id, NEW.email, COALESCE(NEW.created_at, NOW()))
    ON CONFLICT DO NOTHING;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.app_user_from_auth_user() FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS app_user_from_auth_user ON auth.users;
CREATE TRIGGER app_user_from_auth_user
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.app_user_from_auth_user();

-- -----------------------------------------------------------------------------
-- EvidenceLoop users: find or create, in one statement
-- -----------------------------------------------------------------------------
-- The DO UPDATE (rather than DO NOTHING) makes RETURNING give the id on both paths, and
-- records the visit. The backend calls this at most once per user per process every few
-- minutes (src/auth/app_users.py caches the answer).
CREATE OR REPLACE FUNCTION public.app_user_for_evidenceloop(p_issuer TEXT, p_sub TEXT)
RETURNS UUID
LANGUAGE sql
VOLATILE
SET search_path = ''
AS $$
    INSERT INTO public.app_users (evidenceloop_issuer, evidenceloop_sub, last_seen_at)
    VALUES (p_issuer, p_sub, NOW())
    ON CONFLICT (evidenceloop_issuer, evidenceloop_sub)
        DO UPDATE SET last_seen_at = EXCLUDED.last_seen_at
    RETURNING id
$$;

REVOKE ALL ON FUNCTION public.app_user_for_evidenceloop(TEXT, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.app_user_for_evidenceloop(TEXT, TEXT) TO service_role;
