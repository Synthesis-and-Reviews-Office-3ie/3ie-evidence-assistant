"""Verify access tokens signed by EvidenceLoop.

EvidenceLoop (``apps/sr-platform``) is the one account system for the three apps (decision P6).
It signs access tokens with ES256 and publishes its public keys as a JWK Set at
``<API base>/.well-known/jwks.json``. The contract is in sr-platform's ``INFRASTRUCTURE.md``,
section "Token signing (ES256) and how the other apps verify a login". The design for this app is
in ``docs/EVIDENCELOOP_AUTH_DESIGN.md``.

A token is accepted only when all of these hold:

* the header names ``ES256`` and a ``kid`` found in the JWK Set. Any other algorithm, including
  ``none`` and the HMAC family, is refused before a key is looked up, which closes the
  algorithm-confusion attacks;
* the signature verifies with that key, and the key itself is a P-256 key published for ES256;
* ``iss`` equals the configured issuer and ``aud`` contains ``evidence-assistant``;
* ``exp``, ``iat``, ``iss``, ``aud``, ``sub`` and ``jti`` are present, and ``exp`` has not passed
  (30 seconds of leeway for clock skew between hosts);
* a ``type`` claim, when present, is ``access``. Refresh and reset tokens are already addressed to
  EvidenceLoop alone, so this is a second guard;
* when a client id is configured (sr-platform D16, the PKCE sign-in flow), the header ``typ`` is
  ``at+jwt`` (RFC 9068) and the ``client_id`` claim equals it. The app then accepts only tokens
  issued to it, not tokens EvidenceLoop minted for its own front end.

PyJWT's ``PyJWKClient`` fetches the JWK Set, caches it for five minutes (the ``max-age`` EvidenceLoop
sends), refetches once when it meets an unknown ``kid`` (at most every 30 seconds), refuses redirects,
and keeps the cached set when a refetch fails. A fetch is a blocking call with a five-second timeout,
so callers on the event loop run ``verify`` in the thread pool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

import jwt
from jwt import PyJWKClient

from src.config.settings import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)

ALGORITHM = "ES256"
REQUIRED_CLAIMS = ["exp", "iat", "iss", "aud", "sub", "jti"]
ACCESS_TOKEN_TYPES = {"at+jwt", "application/at+jwt"}  # RFC 9068 section 2.1
LEEWAY_SECONDS = 30
JWKS_CACHE_SECONDS = 300
JWKS_TIMEOUT_SECONDS = 5
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class EvidenceLoopTokenError(Exception):
    """The token is not a valid EvidenceLoop access token for this app. Maps to 401."""


class EvidenceLoopUnavailable(Exception):
    """EvidenceLoop's keys could not be fetched, so no token can be checked. Maps to 503."""


@dataclass(frozen=True)
class EvidenceLoopIdentity:
    """Who a verified token says the caller is. ``sub`` is the EvidenceLoop user id."""

    sub: str
    role: str
    claims: dict[str, Any] = field(repr=False)


def _check_jwks_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme == "https" and parsed.hostname:
        return
    if parsed.scheme == "http" and parsed.hostname in _LOCAL_HOSTS:
        return  # a local EvidenceLoop during development
    raise ValueError(f"EvidenceLoop JWKS URL must be https (or http on localhost): {url!r}")


class EvidenceLoopVerifier:
    """Checks EvidenceLoop access tokens against one issuer, one audience and one JWK Set."""

    def __init__(
        self,
        *,
        issuer: str,
        jwks_url: str,
        audience: str,
        client_id: str = "",
        jwks_client: PyJWKClient | None = None,
    ) -> None:
        if not issuer or not audience:
            raise ValueError("EvidenceLoop issuer and audience must be set")
        _check_jwks_url(jwks_url)
        self.issuer = issuer
        self.audience = audience
        self.client_id = client_id
        self._jwks = jwks_client or PyJWKClient(
            jwks_url, lifespan=JWKS_CACHE_SECONDS, timeout=JWKS_TIMEOUT_SECONDS
        )

    def verify(self, token: str) -> EvidenceLoopIdentity:
        """Return the identity in *token*, or raise ``EvidenceLoopTokenError`` / ``EvidenceLoopUnavailable``."""
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise EvidenceLoopTokenError("malformed token") from exc

        if header.get("alg") != ALGORITHM:
            raise EvidenceLoopTokenError("algorithm not allowed")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise EvidenceLoopTokenError("token has no key id")
        if self.client_id and str(header.get("typ", "")).lower() not in ACCESS_TOKEN_TYPES:
            raise EvidenceLoopTokenError("not an RFC 9068 access token")

        key = self._signing_key(kid)

        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key.key,
                algorithms=[ALGORITHM],
                audience=self.audience,
                issuer=self.issuer,
                leeway=LEEWAY_SECONDS,
                options={"require": REQUIRED_CLAIMS},
            )
        except jwt.ExpiredSignatureError as exc:
            raise EvidenceLoopTokenError("token expired") from exc
        except jwt.PyJWTError as exc:
            raise EvidenceLoopTokenError(f"invalid token: {type(exc).__name__}") from exc

        sub = claims.get("sub")
        if not isinstance(sub, str) or not sub:
            raise EvidenceLoopTokenError("token has no subject")
        if "type" in claims and claims["type"] != "access":
            raise EvidenceLoopTokenError("not an access token")
        if self.client_id and claims.get("client_id") != self.client_id:
            raise EvidenceLoopTokenError("token was issued to another client")

        return EvidenceLoopIdentity(sub=sub, role=str(claims.get("role") or ""), claims=claims)

    def _signing_key(self, kid: str) -> jwt.PyJWK:
        # Load the set first, so an outage (503) is told apart from an unknown key (401).
        try:
            self._jwks.get_jwk_set()
        except (jwt.PyJWKClientError, jwt.PyJWKSetError) as exc:
            logger.error(f"EvidenceLoop JWK Set unavailable: {exc}")
            raise EvidenceLoopUnavailable("EvidenceLoop keys unavailable") from exc
        try:
            key = self._jwks.get_signing_key(kid)
        except (jwt.PyJWKClientConnectionError, jwt.PyJWKSetError) as exc:
            logger.error(f"EvidenceLoop JWK Set unavailable: {exc}")
            raise EvidenceLoopUnavailable("EvidenceLoop keys unavailable") from exc
        except jwt.PyJWKClientError as exc:
            raise EvidenceLoopTokenError("unknown signing key") from exc
        if key.algorithm_name != ALGORITHM:
            raise EvidenceLoopTokenError("signing key is not an ES256 key")
        return key


@lru_cache(maxsize=1)
def get_evidenceloop_verifier() -> EvidenceLoopVerifier:
    """The verifier for the configured EvidenceLoop. Cached, so the JWK Set cache is shared."""
    return EvidenceLoopVerifier(
        issuer=settings.evidenceloop_issuer,
        jwks_url=settings.evidenceloop_jwks_url,
        audience=settings.evidenceloop_audience,
        client_id=settings.evidenceloop_client_id,
    )
