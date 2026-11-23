# Accepting EvidenceLoop logins: design note

*23 November 2026. Status: **option (b) chosen by Lucas on 23 November.** Step 1 (the verifier,
behind `EVIDENCELOOP_AUTH_ENABLED`, off in production) is built: `src/auth/evidenceloop.py`,
`src/auth/tokens.py`, `tests/test_evidenceloop_auth.py`. Steps 2 and 3 (the `app_users` table and
the foreign-key swap) are not started.*

Decision P6 in `_portfolio/PRODUCTION_PLAN.md` makes EvidenceLoop (`apps/sr-platform`) the one
account system, and the D3 amendment in `apps/sr-platform/DECISIONS.md` has EvidenceLoop sign
ES256 access tokens that the Evidence Assistant must accept. This note maps where the Assistant
depends on Supabase Auth today. It compares two ways of owning database rows once identity comes
from EvidenceLoop, and recommends one. It ends with what EvidenceLoop must build first.

Production stays on Supabase Auth throughout. EvidenceLoop is not deployed, and it cannot yet
sign a user into another app.

---

## 1. Where authentication is used today

### Backend

| Place | What it does |
| --- | --- |
| `src/auth/supabase_auth.py` | `verify_supabase_token`: checks an HS256 token with the legacy Supabase JWT secret using **python-jose**, with `aud="authenticated"`. If the secret is not set, it calls Supabase's `/auth/v1/user` instead (`verify_token_via_api`), which costs one network round trip per request. Returns `AuthenticatedUser(id, email, role)`. `get_current_user` (401 without a token) and `get_optional_user` (`None` without one) are the FastAPI dependencies. |
| `api/routes/dependencies.py` | `get_current_user_or_legacy`: accepts a Supabase token sent in `X-Admin-Session`, or falls back to the admin password or API key. `get_indexer_for_user` and `authorize_project`: a project is public, or readable only when `rag_projects.user_id == user.id`. |
| `api/routes/rags.py` | 33 routes, all `get_current_user` except two `get_optional_user` (public project page, highlighted PDF). Ownership is checked by `.eq("user_id", user.id)` on `rag_projects`. |
| `api/routes/zotero.py` | 7 routes, all `get_current_user`, with ownership through the project. |
| `api/routes/extraction.py` | 10 routes, `get_optional_user` except `POST /effects/bulk` (`get_current_user`). |
| `api/routes/api.py` | `/query`, `/query/stream` and the four chat-history routes, all `get_optional_user`. Chat history is keyed on `user_id` when signed in and on `session_id` when anonymous. |
| `api/routes/admin/users.py` | Reads email addresses and last-sign-in dates from `supabase.auth.admin.list_users()` and `get_user_by_id()`. |
| Admin console | A separate in-memory password session (`X-Admin-Session`, `X-Admin-API-Key`). It does not use Supabase Auth. |

**The API reaches the database only with the service role** (`get_supabase_client()`, the secret
key). The anon client (`get_supabase_anon_client`) is used only by the token-verification
fallback. No route forwards a user's token to PostgREST. The baseline migration says the same:
"All application data access goes through the FastAPI backend with the secret key … The RLS
policies are defence in depth."

### Frontend

| Place | What it does |
| --- | --- |
| `contexts/AuthContext.tsx` | `supabase.auth.getSession`, `onAuthStateChange`, `signUp`, `signInWithPassword` and `signOut` (email and password only). Exposes `session.access_token`. |
| `lib/supabase/client.ts` | `createBrowserClient` from `@supabase/ssr`, with the anon (publishable) key. |
| `app/auth/callback/route.ts` | `exchangeCodeForSession` for the email-confirmation link. |
| `lib/api.ts` (`authHeaders`), `lib/rag-api.ts` (`fetchWithAuth`), `components/dashboard/RagSettingsTab.tsx` | Read the session and send `Authorization: Bearer <Supabase access token>` to the Railway API. |
| `app/auth/page.tsx`, `app/page.tsx`, `app/dashboard/page.tsx`, `app/dashboard/[ragId]/page.tsx` | Consume `useAuth`. The dashboard pages pass `session.access_token` down. |

**The frontend never queries Supabase tables directly.** There is no `supabase.from(...)` or
`.rpc(...)` in `frontend/src`. Supabase is used in the browser only for sign-in.

### Database

The brief's counts (8 `REFERENCES auth.users`, 42 `auth.uid()`) include `supabase/legacy/`, which
the 7 November baseline superseded. **The live schema has 4 foreign keys and 20 `auth.uid()`
uses**, all in `20261107000000_baseline.sql`, except one in `20261107000100_chunks_pgvector.sql`.

| Table | Owner column | `auth.users` foreign key | RLS policies using `auth.uid()` |
| --- | --- | --- | --- |
| `rag_projects` | `user_id UUID NOT NULL` | `ON DELETE CASCADE` | select, insert, update, delete own |
| `documents` | via `rag_project_id` | — | 4, through `rag_projects.user_id` |
| `processing_jobs` | via `rag_project_id` | — | 2, through `rag_projects.user_id` |
| `zotero_connections` | via project; `connected_by UUID` | `connected_by` (no action) | 1 (`FOR ALL`), through the project |
| `chat_history` | `user_id UUID NULL` (null for anonymous) | `ON DELETE CASCADE` | select, insert, delete own |
| `usage_logs` | `user_id UUID NULL` | `ON DELETE SET NULL` | select own |
| `extracted_estimates` | via `rag_project_id` | — | 2, through the project |
| `chunks` | via `rag_project_id` | — | 1: public projects, or own (anon and authenticated) |
| `query_quality_logs` | `user_id UUID` | none | none (service role only) |
| `evaluation_runs`, `study_cards`, `effect_estimates`, `study_facts` | — | — | RLS on, no user policies (service role only) |

Every user-owned row hangs off `rag_projects.user_id`, `chat_history.user_id`,
`usage_logs.user_id` or `zotero_connections.connected_by`. The user data was reset on 7 November
(P6), so few accounts exist.

### What EvidenceLoop's token carries

These details come from `apps/sr-platform/backend/app/security.py` and its
`tests/test_token_signing.py`, and they matter for the comparison:

- Header: `alg: ES256` and `kid` (the RFC 7638 thumbprint).
- Claims: `iss` (default `"evidenceloop"`, and the production URL once deployed), `aud` as a list
  (`["evidenceloop", "assay", "evidence-assistant"]` on access tokens, `["evidenceloop"]` on every
  other type), `sub`, `type: "access"`, `iat`, `exp` (30 minutes), `jti`, and the extras `role` and
  `tv`.
- **`sub` is an integer id as a string (`"42"`), not a UUID.**
- **`role` is EvidenceLoop's platform role** (`admin`, `maintainer`, `reviewer`, …), not a
  Postgres role.
- There is no `email` claim. Profile details come from `GET /auth/me`.
- The JWK Set at `/.well-known/jwks.json` sends `Cache-Control: public, max-age=300`. Retired keys
  stay listed until their tokens expire. There is no OIDC discovery document.

**Proposed for the sign-in flow (sr-platform `DECISIONS.md` D16, not yet decided).** Tokens
issued to the Assistant through the new PKCE flow would differ from EvidenceLoop's own access
tokens:

- `aud` would be `["evidence-assistant"]` only.
- The header would carry `typ: "at+jwt"` (RFC 9068), and the claims a `client_id`.
- `/auth/me` would refuse them. Profile details would come from `GET /oauth/userinfo` instead
  (`sub`, `email`, `email_verified`, `name`).
- `email_verified` is true only when an identity provider vouched for the address, because
  EvidenceLoop does not verify the e-mail of password accounts.

The verifier in section 3 accepts these tokens.

---

## 2. The options for row ownership

### (a) Supabase third-party auth, with EvidenceLoop as the issuer

Supabase's Custom OIDC provider integration accepts tokens from an issuer other than Supabase Auth,
so RLS can evaluate them. Its documented requirements
([Custom OIDC provider](https://supabase.com/docs/guides/auth/third-party/custom-oidc),
[Third-party auth overview](https://supabase.com/docs/guides/auth/third-party/overview)):

1. An OIDC discovery document at `<issuer>/.well-known/openid-configuration`, with an **HTTPS**
   issuer. Supabase reads the JWKS location from it. A bare JWKS URL is not enough.
2. Asymmetric signing, with a `kid` header. HS256 is refused. ES256 qualifies.
3. **A `role` claim set to `authenticated`** for signed-in users. Without it, requests run as
   `anon`.
4. `auth.uid()` casts `sub` to `uuid`, so it fails for non-UUID subjects. Policies must read
   `auth.jwt() ->> 'sub'` (and should check `iss`).
5. It can run alongside Supabase Auth in the same project. It is billed as Third-Party MAU, and Pro
   includes 100,000
   ([usage](https://supabase.com/docs/guides/platform/manage-your-usage/monthly-active-users-third-party),
   [changelog](https://supabase.com/changelog/33959-greatly-increased-third-party-auth-mau-quota-for-free-and-paid-plans)),
   so the cost at our scale is nil.

How EvidenceLoop's tokens measure against these requirements:

- **The `role` claim conflicts.** EvidenceLoop puts `reviewer` or `admin` in `role`. PostgREST
  would try to assume a Postgres role of that name. The request would fail at best, and if such a
  role ever existed, it would run with that role's grants. Fixing this means EvidenceLoop renames
  its own claim (to `el_role`, say) and adds `role: authenticated` to tokens that are also read by
  Assay and by EvidenceLoop itself. That is a cross-app contract change made for one consumer.
- **`sub` is not a UUID.** All 20 policies would be rewritten to `auth.jwt() ->> 'sub'`. The four
  owner columns would move from `uuid` to `text`, and the `auth.users` foreign keys would go,
  because third-party users have no `auth.users` row. That is the same schema work as option (b).
- **No discovery document**, and the issuer is not deployed. Option (a) cannot even be configured
  until EvidenceLoop is live on HTTPS and serves OIDC discovery.
- **It buys almost nothing here.** RLS matters only when a user's token reaches PostgREST. In this
  app no request does that: the browser never queries tables, and the API always uses the service
  role. Option (a) would protect a path that does not exist, and it would add a second place where
  authorisation is decided.

### (b) The API enforces ownership through the service role, with an app users table

The API keeps using the service role, as it does today. Identity becomes an app-level record:

```sql
CREATE TABLE public.app_users (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    evidenceloop_sub  TEXT UNIQUE,          -- EvidenceLoop user id; NULL until linked
    supabase_user_id  UUID UNIQUE,          -- old Supabase Auth id; NULL for new users
    email             TEXT,                 -- from EvidenceLoop /auth/me, for the admin console
    display_name      TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at      TIMESTAMPTZ,
    CHECK (evidenceloop_sub IS NOT NULL OR supabase_user_id IS NOT NULL)
);
ALTER TABLE public.app_users ENABLE ROW LEVEL SECURITY;   -- no policies: service role only
```

**Existing users keep their UUID.** Each `app_users` row is seeded with `id = auth.users.id` and
`supabase_user_id = auth.users.id`. All four foreign keys then point at `app_users(id)` instead
of `auth.users(id)`, with the same `ON DELETE` behaviour. **No `user_id` value in any table is
rewritten.** The column type stays `uuid`, and every `.eq("user_id", user.id)` in the routes keeps
working. A new EvidenceLoop user gets a fresh UUID with `evidenceloop_sub` set.

The verifier resolves a token to an app user. A Supabase token looks up `supabase_user_id`, and an
EvidenceLoop token looks up `evidenceloop_sub`. The first time an identity is seen, its row is
created, and the lookup is cached in the process for a few minutes. `AuthenticatedUser.id` stays
the app user's UUID, so no route changes.

Option (b) is less work than (a): one additive table and a foreign-key swap, against the same
foreign-key removal plus 20 rewritten policies. It needs nothing from EvidenceLoop's token beyond
what it already issues, and it does not depend on EvidenceLoop being deployed. It also matches the
direction of P10, where the Assistant's data moves behind EvidenceLoop's API and RLS on these
tables stops mattering.

| | (a) Third-party auth | (b) App users table |
| --- | --- | --- |
| RLS keeps working for user tokens | Yes, after rewriting 20 policies | Policies are retired. RLS stays on with no user policies (service role only) |
| Changes to EvidenceLoop's token | Rename `role`, add `role: authenticated`, add OIDC discovery | None |
| Schema change | Four owner columns to `text`, four FKs dropped, 20 policies rewritten | One new table, four FKs repointed, no data rewritten |
| Can be built before EvidenceLoop is deployed | No (needs a public HTTPS issuer) | Yes |
| Where authorisation is decided | Split between Postgres policies and API checks | API only (as today) |
| Cost | Third-Party MAU, within the Pro quota | None |
| Fit with P10 (tables move behind EvidenceLoop) | Work undone later | Same direction |

---

## 3. Migration, the dual-accept period, and permissions

### Migration of existing users and rows

1. **Migration A (additive).** Create `app_users`, and seed it from `auth.users`
   (`id`, `supabase_user_id`, `email`). Nothing reads the table yet. Rollback: drop the table.
2. **Code (behind a flag).** The verifier resolves both token kinds to `app_users`. A Supabase sign-up
   during the transition creates its row on first request, before any write that needs the foreign
   key.
3. **Migration B (foreign-key swap).** For each of the four columns, add the new foreign key to
   `app_users(id)` `NOT VALID`, `VALIDATE` it, then drop the old `auth.users` foreign key, all in
   one transaction. Rollback: re-add the `auth.users` foreign keys. **This rollback works only until
   the first EvidenceLoop-only user writes a row**, because every `user_id` must still exist in
   `auth.users`. After that point, rolling back means switching EvidenceLoop acceptance off and
   keeping `app_users`, which leaves those rows intact but unreachable until it is switched on
   again.
4. **Linking accounts.** A Supabase account is linked to an EvidenceLoop account only on proof of
   both: a "link my account" action that presents a valid Supabase token and a valid EvidenceLoop
   token in the same request. The link sets `evidenceloop_sub` on the existing row, so the user's
   projects follow. Email matching is not used, because an unverified or recycled address would
   hand over someone else's projects. The few accounts that miss the window are linked by an admin
   script with a dry run.

Each migration is run against a real database only with Lucas's approval.

### The dual-accept period and how it ends

- **Settings:** `EVIDENCELOOP_AUTH_ENABLED` (default `false`, and `false` in production),
  `EVIDENCELOOP_ISSUER`, `EVIDENCELOOP_JWKS_URL`, `EVIDENCELOOP_AUDIENCE`
  (default `evidence-assistant`), plus later `SUPABASE_AUTH_ENABLED` (default `true`).
- **Dispatch:** the unverified `iss` claim picks the verifier: the EvidenceLoop issuer, or
  Supabase's `https://<ref>.supabase.co/auth/v1`. The chosen verifier then checks everything
  against its own pinned key source and algorithm, so the token never chooses its own key or
  algorithm. An unknown issuer gets a 401.
- **What the EvidenceLoop verifier requires:** ES256 only, a `kid` known to the JWK Set,
  `aud` containing `evidence-assistant`, the pinned `iss`, and `exp`, `iat`, `sub` and `jti`
  present. If D16 is adopted, it also requires header `typ: "at+jwt"` and `client_id` equal to
  the Assistant's client id. Then the Assistant accepts only tokens issued to it through the PKCE
  flow, not tokens EvidenceLoop minted for its own front end. In that case EvidenceLoop can drop
  `evidence-assistant` from its own access tokens. This check is a setting, so it can be switched
  on once D16 lands.
- **The period ends when** EvidenceLoop's sign-in flow is live, the frontend uses it, and every
  account active in the previous 90 days is linked (or a cut-off date announced to users has
  passed). Then:
  1. Turn off Supabase sign-ups in the Supabase dashboard.
  2. Set `SUPABASE_AUTH_ENABLED=false`. This is one deploy, and the rollback is the flag.
  3. After 30 quiet days, remove `@supabase/ssr` sign-in from the frontend, drop python-jose, the
     Supabase token verifier and the `auth.admin` calls in `admin/users.py` (which reads
     `app_users` instead), and drop the 20 `auth.uid()` policies. RLS stays enabled with no user
     policies, so only the service role can read or write.

### Per-project permissions (R2)

There are two kinds of project:

- **The Assistant's own projects** (`rag_projects`): owner-only or public, decided by
  `rag_projects.user_id` against the app user, exactly as today.
- **Projects that are EvidenceLoop reviews** ("Ask this review", and everything under P10):
  `rag_projects` gains a nullable `evidenceloop_project_id`. `authorize_project` asks EvidenceLoop
  for the caller's role on that project, with the caller's own bearer token, and caches the answer
  for each `(sub, project)` for 60 seconds. It fails closed on errors, except for public projects.
  Ranks map to actions: `viewer` can ask and read, `reviewer` can upload and run, and `owner` or
  `maintainer` can change settings and delete. Membership is not put in token claims, because it
  would go stale for up to 30 minutes, as R2 notes.

This adds no new service. An external authorisation service (OpenFGA, say) would be the larger
design, but the one-provider rule rules it out and the scale does not need it.

### Things that stay true under either option

- **Revocation lag.** The Assistant cannot see a sign-out or password reset until the access token
  expires (30 minutes). This is accepted for reading and asking. If a destructive action (deleting
  a project) should see revocation, EvidenceLoop would need an introspection endpoint (RFC 7662).
  This is listed as optional below.
- **Library.** EvidenceLoop and its consumer test use PyJWT. The Assistant verifies Supabase
  tokens with python-jose, which has had long maintenance gaps. PyJWT 2.15.1 is already installed
  here, as a dependency of `supabase`. Its `PyJWKClient` caches the JWK Set (5 minutes by
  default), refetches once on an unknown `kid` with a 30-second cooldown, refuses redirects and
  non-HTTP(S) schemes, and keeps the cached set when a refetch fails. The new verifier uses PyJWT
  with an explicit `PyJWT[crypto]>=2.15.1` pin. Moving the Supabase verifier to PyJWT too is a
  follow-up, so python-jose can go.
- **Blocking fetch.** `PyJWKClient` uses blocking `urllib`. A JWK Set fetch happens at most once
  per cache lifetime, with a 5-second timeout, and runs in the threadpool, not on the event loop.

---

## 4. Recommendation

**Option (b): the API enforces ownership through the service role, with an `app_users` table
whose `id` is today's Supabase user id.** It needs nothing new in EvidenceLoop's token. Its
rollback is a flag until the first EvidenceLoop-only user writes a row. It keeps authorisation in
one place, the API, where it already is. Option (a) would require EvidenceLoop to change a claim
other apps read, and would protect a database path this app does not use.

**Waiting for Lucas's decision before any code.** After a decision for (b), Phase 3 lands in
this order, each step behind the flag and off in production:

1. The EvidenceLoop token verifier and its tests (no database change).
2. Migration A and resolution to `app_users` (migration run only with approval).
3. Migration B, the foreign-key swap (run only with approval).

---

## 5. What EvidenceLoop must provide

Needed before the Assistant can sign anyone in with EvidenceLoop. The sr-platform session has
answered items 2 to 5 in its proposed D16. Their status is shown, and none of it is decided yet.

1. **A deployed, stable HTTPS API base**, with `JWT_ISSUER` set to that URL and never changed
   afterwards (a change invalidates every consumer's `iss` check). *D16: confirmed.*
2. **An authorization-code flow with PKCE (S256 only)**: `/oauth/authorize` and `/oauth/token`,
   following RFC 9700 (exact redirect-URI matching, a single-use code). *D16: PKCE is mandatory
   for every client, and a confidential client adds `client_secret_basic`, so both client types
   work. Metadata is at `/.well-known/oauth-authorization-server`.* Redirect URIs, exact and with no
   wildcards: `https://3ie-evidence-assistant.vercel.app/auth/evidenceloop/callback` and
   `http://localhost:3000/auth/evidenceloop/callback`. The Vercel domain is the one adopted by the
   7 November rename (`docs/RENAME_PLAN.md`, step 7). Vercel previews are not registered.
3. **A decision on where the Assistant's tokens live (Lucas).** RFC 10017 (BCP 212, August 2026,
   *OAuth 2.0 for Browser-Based Applications*) describes a backend-for-frontend, where the Next.js
   server holds the tokens in httpOnly cookies, as its strongest pattern. D16 makes refresh tokens
   opaque and rotated on every use, with no grace window, and a reused token revokes the whole
   family. Two tabs refreshing at once would therefore sign the user out, and a backend-for-frontend
   serialises refreshes. This is a further reason to choose it. The cost is that the browser's calls
   to the Railway API would go through Next.js.
4. **Sign-out across apps.** *D16: `POST /oauth/revoke` (RFC 7009), and a logout route
   `/oauth/logout?client_id&post_logout_redirect_uri&state`. Refresh tokens last 30 days idle and
   90 days in total.*
5. **Profile details.** *D16: `GET /oauth/userinfo` (`sub`, `email`, `email_verified`, `name`),
   because `/auth/me` refuses tokens addressed only to the Assistant.* Rows are keyed on `sub`,
   never on e-mail, which matches the linking rule in section 3.

Needed for permissions and lifecycle (R2, P10). D16 leaves these as follow-ups:

6. **A project-role endpoint:** `GET /projects/{id}/membership/me` returning the caller's
   `ProjectRole` (404 when not a member), and a list form (`GET /me/projects?min_role=viewer`) for
   the dashboard.
7. **Account-deletion and deactivation signals:** a signed webhook, or a status endpoint the
   Assistant can poll with a service credential, so the Assistant deletes or orphans that user's
   rows (erasure requests).
8. **A service credential** for server-to-server calls made outside a user request (background
   jobs under P10): client credentials, addressed to EvidenceLoop, with a narrow scope.
9. **A staging issuer and JWK Set** the Assistant's CI or a staging deploy can test against.

Optional:

10. Token introspection (RFC 7662), only if destructive actions must see revocation within 30
    minutes.
11. An OIDC discovery document, which costs little and helps standard client libraries. It would
    be required only under option (a).

Not needed under (b): any change to the access token's claims.
