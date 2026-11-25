"""Map a verified identity to this app's user row in ``public.app_users``.

Under option (b) of ``docs/EVIDENCELOOP_AUTH_DESIGN.md`` rows are owned by an app user, not by a
Supabase Auth user. A Supabase user's app-user id is their Supabase id (migration
``20261123000000_app_users.sql`` seeds and maintains that). An EvidenceLoop user is found or created
by ``public.app_user_for_evidenceloop(issuer, sub)``. That runs as one statement in Postgres, so two
first requests at once still get the same row.

The answer is cached in the process for five minutes, so a signed-in user costs one database call
per process every five minutes, not one per request. An app-user id never changes for a given
(issuer, sub), so a stale cache entry is harmless. The cache only delays ``last_seen_at``.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from src.auth.supabase_auth import get_supabase_client
from src.utils.logging import get_logger

logger = get_logger(__name__)

CACHE_SECONDS = 300
CACHE_MAX_ENTRIES = 10_000


class AppUserUnavailable(Exception):
    """The app-user row could not be found or created (database unreachable or not migrated). Maps to 503."""


class AppUserDirectory:
    """Finds the app-user id for an EvidenceLoop (issuer, sub), with a short in-process cache."""

    def __init__(
        self,
        client_factory: Callable[[], Any] = get_supabase_client,
        ttl_seconds: float = CACHE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client_factory = client_factory
        self._ttl = ttl_seconds
        self._clock = clock
        self._cache: dict[tuple[str, str], tuple[str, float]] = {}
        self._lock = threading.Lock()

    def for_evidenceloop(self, issuer: str, sub: str) -> str:
        """The app-user id (a UUID string) for this EvidenceLoop user, created on first sight."""
        if not issuer or not sub:
            raise ValueError("issuer and sub are required")
        key = (issuer, sub)
        now = self._clock()
        with self._lock:
            hit = self._cache.get(key)
            if hit and hit[1] > now:
                return hit[0]

        try:
            data = (
                self._client_factory()
                .rpc("app_user_for_evidenceloop", {"p_issuer": issuer, "p_sub": sub})
                .execute()
                .data
            )
        except Exception as exc:  # the client raises several types; all mean "not available now"
            logger.error(f"app_users lookup failed: {type(exc).__name__}: {exc}")
            raise AppUserUnavailable("app user lookup failed") from exc

        app_user_id = _as_uuid(data)
        if app_user_id is None:
            logger.error(f"app_user_for_evidenceloop returned an unexpected value: {data!r}")
            raise AppUserUnavailable("app user lookup returned no id")

        with self._lock:
            if len(self._cache) >= CACHE_MAX_ENTRIES:
                self._cache = {k: v for k, v in self._cache.items() if v[1] > now}
                if len(self._cache) >= CACHE_MAX_ENTRIES:
                    self._cache.clear()
            self._cache[key] = (app_user_id, now + self._ttl)
        return app_user_id

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()


def _as_uuid(data: Any) -> str | None:
    """PostgREST returns a scalar function result as the bare value. Accept only a UUID."""
    if isinstance(data, list) and len(data) == 1:  # tolerate a one-row list
        data = data[0]
    if isinstance(data, dict) and len(data) == 1:
        data = next(iter(data.values()))
    try:
        return str(uuid.UUID(str(data)))
    except (ValueError, TypeError, AttributeError):
        return None


app_user_directory = AppUserDirectory()
