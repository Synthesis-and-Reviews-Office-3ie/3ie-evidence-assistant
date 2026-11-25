"""Migration 20261123000000_app_users.sql, run for real against a throwaway Postgres.

Skipped unless ``MIGRATION_TEST_DATABASE_URL`` points at a disposable Postgres 15+ server with pgvector,
for example:

    docker run --rm -d --name app-users-pg -e POSTGRES_PASSWORD=pg -p 55432:5432 pgvector/pgvector:pg17
    MIGRATION_TEST_DATABASE_URL=postgresql://postgres:pg@127.0.0.1:55432/postgres pytest tests/test_app_users_migration.py

Each run creates a fresh database on that server, adds the few Supabase objects the migrations expect
(the anon, authenticated and service_role roles, ``auth.users``, ``auth.uid()`` and the ``extensions``
schema), applies every file in ``supabase/migrations`` in order, and drops the database afterwards. Never
point it at a real project: it creates and drops databases.
"""

from __future__ import annotations

import asyncio
import os
import re
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

asyncpg = pytest.importorskip("asyncpg")

ADMIN_URL = os.getenv("MIGRATION_TEST_DATABASE_URL", "")
MIGRATIONS = Path(__file__).resolve().parent.parent / "supabase" / "migrations"
APP_USERS = MIGRATIONS / "20261123000000_app_users.sql"
ISSUER = "https://evidenceloop.test"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="MIGRATION_TEST_DATABASE_URL is not set"),
]

SUPABASE_SHIM = """
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN CREATE ROLE anon NOLOGIN; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN CREATE ROLE service_role NOLOGIN BYPASSRLS; END IF;
END $$;
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE SCHEMA IF NOT EXISTS auth;
CREATE TABLE auth.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE FUNCTION auth.uid() RETURNS UUID LANGUAGE sql STABLE AS
    $$ SELECT NULLIF(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
GRANT USAGE ON SCHEMA public, auth, extensions TO anon, authenticated, service_role;
-- Supabase grants table rights to its API roles by default; the migration must take them away itself.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO anon, authenticated, service_role;
"""


def _with_database(url: str, name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{name}"))


async def _apply(conn, path: Path) -> None:
    await conn.execute(path.read_text(encoding="utf-8"))


@pytest.fixture
async def db():
    """A fresh database with the shim, two pre-existing Supabase users, and every migration applied."""
    name = f"app_users_test_{uuid.uuid4().hex[:12]}"
    admin = await asyncpg.connect(ADMIN_URL)
    await admin.execute(f'CREATE DATABASE "{name}"')
    url = _with_database(ADMIN_URL, name)
    conn = await asyncpg.connect(url)
    try:
        await conn.execute(SUPABASE_SHIM)
        before = await conn.fetch(
            "INSERT INTO auth.users (email) VALUES ('a@example.org'), ('b@example.org') RETURNING id, email"
        )
        for path in sorted(MIGRATIONS.glob("*.sql")):
            await _apply(conn, path)
        yield conn, url, {r["email"]: r["id"] for r in before}
    finally:
        await conn.close()
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()


async def test_existing_supabase_users_are_seeded_with_their_own_id(db):
    conn, _, before = db
    rows = await conn.fetch("SELECT id, supabase_user_id, email FROM public.app_users ORDER BY email")
    assert [(r["id"], r["supabase_user_id"], r["email"]) for r in rows] == [
        (before["a@example.org"], before["a@example.org"], "a@example.org"),
        (before["b@example.org"], before["b@example.org"], "b@example.org"),
    ]


async def test_a_new_supabase_sign_up_gets_its_row(db):
    conn, _, _ = db
    new_id = await conn.fetchval("INSERT INTO auth.users (email) VALUES ('c@example.org') RETURNING id")
    row = await conn.fetchrow("SELECT id, supabase_user_id, email FROM public.app_users WHERE id = $1", new_id)
    assert (row["supabase_user_id"], row["email"]) == (new_id, "c@example.org")


async def test_an_evidenceloop_user_is_found_or_created_once(db):
    conn, _, _ = db
    first = await conn.fetchval("SELECT public.app_user_for_evidenceloop($1, '42')", ISSUER)
    seen_1 = await conn.fetchval("SELECT last_seen_at FROM public.app_users WHERE id = $1", first)
    await asyncio.sleep(0.01)
    second = await conn.fetchval("SELECT public.app_user_for_evidenceloop($1, '42')", ISSUER)
    seen_2 = await conn.fetchval("SELECT last_seen_at FROM public.app_users WHERE id = $1", first)
    other_issuer = await conn.fetchval("SELECT public.app_user_for_evidenceloop('https://staging.test', '42')")
    other_sub = await conn.fetchval("SELECT public.app_user_for_evidenceloop($1, '43')", ISSUER)
    assert first == second and seen_2 > seen_1
    assert len({first, other_issuer, other_sub}) == 3
    assert await conn.fetchval("SELECT count(*) FROM public.app_users WHERE evidenceloop_sub IS NOT NULL") == 3


async def test_concurrent_first_requests_get_one_row(db):
    _, url, _ = db
    conns = [await asyncpg.connect(url) for _ in range(8)]
    try:
        ids = await asyncio.gather(*(
            c.fetchval("SELECT public.app_user_for_evidenceloop($1, 'race')", ISSUER) for c in conns
        ))
        assert len(set(ids)) == 1
        count = await conns[0].fetchval("SELECT count(*) FROM public.app_users WHERE evidenceloop_sub = 'race'")
        assert count == 1
    finally:
        for c in conns:
            await c.close()


@pytest.mark.parametrize("columns,values", [
    ("evidenceloop_issuer", f"'{ISSUER}'"),                      # issuer without sub
    ("evidenceloop_sub", "'42'"),                                # sub without issuer
    ("evidenceloop_issuer, evidenceloop_sub", f"'{ISSUER}', ''"),  # empty sub
    ("evidenceloop_issuer, evidenceloop_sub", "'', '42'"),        # empty issuer
    ("email", "'nobody@example.org'"),                           # no identity at all
])
async def test_constraints_refuse_half_identities(db, columns, values):
    conn, _, _ = db
    with pytest.raises(asyncpg.CheckViolationError):
        await conn.execute(f"INSERT INTO public.app_users ({columns}) VALUES ({values})")


@pytest.mark.parametrize("role", ["anon", "authenticated"])
async def test_the_api_roles_cannot_read_write_or_call(db, role):
    conn, _, _ = db
    async with conn.transaction():
        await conn.execute(f"SET LOCAL ROLE {role}")
        for statement in (
            "SELECT * FROM public.app_users",
            "INSERT INTO public.app_users (supabase_user_id) VALUES (gen_random_uuid())",
            f"SELECT public.app_user_for_evidenceloop('{ISSUER}', 'x')",
        ):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                async with conn.transaction():
                    await conn.execute(statement)
    # A trigger function cannot be called directly at all, so check the grant itself.
    assert await conn.fetchval(
        "SELECT has_function_privilege($1, 'public.app_user_from_auth_user()', 'EXECUTE')", role
    ) is False


async def test_the_service_role_can_read_and_call(db):
    conn, _, _ = db
    async with conn.transaction():
        await conn.execute("SET LOCAL ROLE service_role")
        app_user = await conn.fetchval("SELECT public.app_user_for_evidenceloop($1, 'svc')", ISSUER)
        assert await conn.fetchval("SELECT count(*) FROM public.app_users WHERE id = $1", app_user) == 1


async def test_the_migration_can_be_applied_twice(db):
    conn, _, _ = db
    await _apply(conn, APP_USERS)
    assert await conn.fetchval("SELECT count(*) FROM public.app_users") == 2


async def test_the_documented_rollback_removes_everything_and_sign_ups_still_work(db):
    conn, _, _ = db
    text = APP_USERS.read_text(encoding="utf-8")
    rollback = re.findall(r"^--\s+(DROP .+;)$", text, flags=re.MULTILINE)
    assert len(rollback) == 4
    for statement in rollback:
        await conn.execute(statement)
    assert await conn.fetchval("SELECT to_regclass('public.app_users')") is None
    assert await conn.fetchval(
        "SELECT count(*) FROM pg_proc WHERE proname IN ('app_user_for_evidenceloop', 'app_user_from_auth_user')"
    ) == 0
    await conn.execute("INSERT INTO auth.users (email) VALUES ('after-rollback@example.org')")
