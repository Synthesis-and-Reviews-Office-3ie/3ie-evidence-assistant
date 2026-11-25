"""Route a bearer token to the verifier for the system that issued it.

During the transition to EvidenceLoop logins (P6), the API accepts two kinds of token: Supabase Auth
tokens (production today) and EvidenceLoop access tokens (behind ``EVIDENCELOOP_AUTH_ENABLED``, off in
production). The unverified ``iss`` claim picks the verifier. The chosen verifier then checks the
token against its own pinned keys and algorithm, so the token never chooses its own key or algorithm.
With the flag off, every token goes to the Supabase verifier exactly as before.

A verified EvidenceLoop user becomes an ``AuthenticatedUser`` whose ``id`` is their ``app_users`` id
(option (b) of ``docs/EVIDENCELOOP_AUTH_DESIGN.md``). Routes compare that id with ``user_id`` columns
exactly as they do for Supabase users, whose app-user id is their Supabase id.
"""

from __future__ import annotations

import jwt
from fastapi import HTTPException, status

from src.auth.app_users import AppUserUnavailable, app_user_directory
from src.auth.evidenceloop import (
    EvidenceLoopIdentity,
    EvidenceLoopTokenError,
    EvidenceLoopUnavailable,
    get_evidenceloop_verifier,
)
from src.auth.supabase_auth import AuthenticatedUser, verify_supabase_token
from src.config.settings import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)

PROVIDER_EVIDENCELOOP = "evidenceloop"


def _unverified_issuer(token: str) -> str | None:
    """The ``iss`` claim, read without verification and used only to pick a verifier."""
    try:
        iss = jwt.decode(token, options={"verify_signature": False}).get("iss")
    except jwt.PyJWTError:
        return None
    return iss if isinstance(iss, str) else None


def is_evidenceloop_token(token: str) -> bool:
    """True when EvidenceLoop sign-in is on and *token* names EvidenceLoop as its issuer."""
    return bool(
        settings.evidenceloop_auth_enabled
        and settings.evidenceloop_issuer
        and _unverified_issuer(token) == settings.evidenceloop_issuer
    )


def _unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Sign-in could not be checked. Try again shortly.",
    )


def resolve_evidenceloop_user(identity: EvidenceLoopIdentity) -> AuthenticatedUser:
    """The app user for a verified EvidenceLoop identity, created on first sight."""
    try:
        app_user_id = app_user_directory.for_evidenceloop(settings.evidenceloop_issuer, identity.sub)
    except AppUserUnavailable as exc:
        raise _unavailable() from exc
    # Profile details (email, name) come later from EvidenceLoop's userinfo endpoint (D16).
    # No route reads user.email today.
    return AuthenticatedUser(id=app_user_id, email="", role="authenticated", provider=PROVIDER_EVIDENCELOOP)


def verify_bearer_token(token: str) -> AuthenticatedUser | None:
    """Verify *token* with the right verifier. ``None`` means 401. Raises 503 when a dependency is down."""
    if not is_evidenceloop_token(token):
        return verify_supabase_token(token)
    try:
        identity = get_evidenceloop_verifier().verify(token)
    except EvidenceLoopTokenError as exc:
        logger.debug(f"EvidenceLoop token refused: {exc}")
        return None
    except EvidenceLoopUnavailable as exc:
        raise _unavailable() from exc
    return resolve_evidenceloop_user(identity)
