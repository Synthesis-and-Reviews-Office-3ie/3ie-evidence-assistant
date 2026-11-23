"""Route a bearer token to the verifier for the system that issued it.

During the transition to EvidenceLoop logins (P6), the API accepts two kinds of token: Supabase Auth
tokens (production today) and EvidenceLoop access tokens (behind ``EVIDENCELOOP_AUTH_ENABLED``, off in
production). The unverified ``iss`` claim picks the verifier. The chosen verifier then checks the
token against its own pinned keys and algorithm, so the token never chooses its own key or algorithm.
With the flag off, every token goes to the Supabase verifier exactly as before.

EvidenceLoop users are not yet provisioned here. Under option (b) of
``docs/EVIDENCELOOP_AUTH_DESIGN.md`` their rows hang off an ``app_users`` table that step 2 adds. Until
then a valid EvidenceLoop token is answered with 501 rather than handed to routes that expect an app
user id.
"""

from __future__ import annotations

import jwt
from fastapi import HTTPException, status

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


def resolve_evidenceloop_user(identity: EvidenceLoopIdentity) -> AuthenticatedUser:  # noqa: ARG001 (used in step 2)
    """Map a verified EvidenceLoop identity to this app's user. Step 2 (``app_users``) fills this in."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="EvidenceLoop accounts are not yet available in the Evidence Assistant",
    )


def verify_bearer_token(token: str) -> AuthenticatedUser | None:
    """Verify *token* with the right verifier. ``None`` means 401. Raises 503 if EvidenceLoop is down."""
    if not is_evidenceloop_token(token):
        return verify_supabase_token(token)
    try:
        identity = get_evidenceloop_verifier().verify(token)
    except EvidenceLoopTokenError as exc:
        logger.debug(f"EvidenceLoop token refused: {exc}")
        return None
    except EvidenceLoopUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sign-in could not be checked. Try again shortly.",
        ) from exc
    return resolve_evidenceloop_user(identity)
