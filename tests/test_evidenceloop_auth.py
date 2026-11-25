"""EvidenceLoop access tokens: what the Evidence Assistant accepts, refuses, and leaves to Supabase.

The contract is sr-platform's INFRASTRUCTURE.md, "Token signing (ES256) and how the other apps verify a
login", and the design is docs/EVIDENCELOOP_AUTH_DESIGN.md. Keys are generated here, and the JWK Set is
served by a real HTTP server on localhost, so PyJWT's PyJWKClient fetches, caches and refetches exactly
as it would against EvidenceLoop. No external service is called.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from jwt import PyJWKClient
from jwt.algorithms import ECAlgorithm, RSAAlgorithm

import src.auth.supabase_auth as supabase_auth
import src.auth.tokens as tokens
from src.auth.app_users import AppUserDirectory, AppUserUnavailable
from src.auth.evidenceloop import (
    EvidenceLoopTokenError,
    EvidenceLoopUnavailable,
    EvidenceLoopVerifier,
    get_evidenceloop_verifier,
)
from src.config.settings import Settings, settings

ISSUER = "https://evidenceloop.test"
AUDIENCE = "evidence-assistant"
CLIENT_ID = "evidence-assistant-web"


# --- a stand-in for EvidenceLoop: keys, a JWK Set server, and a token minter -------------


def _kid(public_key: ec.EllipticCurvePublicKey) -> str:
    """RFC 7638 thumbprint, as EvidenceLoop computes it."""
    jwk = ECAlgorithm.to_jwk(public_key, as_dict=True)
    canonical = json.dumps({m: jwk[m] for m in ("crv", "kty", "x", "y")}, separators=(",", ":"), sort_keys=True)
    return base64.urlsafe_b64encode(hashlib.sha256(canonical.encode()).digest()).rstrip(b"=").decode()


class Signer:
    def __init__(self) -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.kid = _kid(self.key.public_key())

    def jwk(self) -> dict[str, Any]:
        jwk = ECAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
        return {**jwk, "kid": self.kid, "use": "sig", "alg": "ES256"}

    def public_pem(self) -> bytes:
        return self.key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )


def claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    base = {
        "iss": ISSUER,
        "aud": ["evidenceloop", "assay", AUDIENCE],
        "sub": "42",
        "type": "access",
        "role": "reviewer",
        "iat": now,
        "exp": now + 1800,
        "jti": uuid.uuid4().hex,
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def mint(signer: Signer, headers: dict[str, Any] | None = None, **overrides: Any) -> str:
    return jwt.encode(claims(**overrides), signer.key, algorithm="ES256",
                      headers={"kid": signer.kid, **(headers or {})})


def forge(header: dict[str, Any], body: dict[str, Any], signature: bytes = b"") -> str:
    enc = lambda obj: base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()  # noqa: E731
    return f"{enc(header)}.{enc(body)}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


class JWKSServer:
    """Serves {"keys": [...]} on localhost and counts requests. ``status`` simulates an outage."""

    def __init__(self) -> None:
        self.keys: list[dict[str, Any]] = []
        self.requests = 0
        self.status = 200
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                server.requests += 1
                body = json.dumps({"keys": server.keys}).encode()
                self.send_response(server.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: Any) -> None:
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/.well-known/jwks.json"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def signer() -> Signer:
    return Signer()


@pytest.fixture
def jwks(signer: Signer):
    server = JWKSServer()
    server.keys = [signer.jwk()]
    yield server
    server.close()


def make_verifier(jwks: JWKSServer, *, client_id: str = "", cooldown: float = 30) -> EvidenceLoopVerifier:
    client = PyJWKClient(jwks.url, lifespan=300, timeout=5, cooldown_duration=cooldown)
    return EvidenceLoopVerifier(issuer=ISSUER, jwks_url=jwks.url, audience=AUDIENCE,
                                client_id=client_id, jwks_client=client)


@pytest.fixture
def verifier(jwks: JWKSServer) -> EvidenceLoopVerifier:
    return make_verifier(jwks)


# --- what is accepted ----------------------------------------------------------------------


def test_a_valid_access_token_gives_the_evidenceloop_user(verifier, signer):
    identity = verifier.verify(mint(signer))
    assert identity.sub == "42" and identity.role == "reviewer"
    assert AUDIENCE in identity.claims["aud"]


def test_an_audience_of_this_app_alone_is_accepted(verifier, signer):
    # D16: tokens issued through the PKCE flow carry aud=["evidence-assistant"] only.
    assert verifier.verify(mint(signer, aud=[AUDIENCE])).sub == "42"
    assert verifier.verify(mint(signer, aud=AUDIENCE)).sub == "42"


def test_a_token_without_a_type_claim_is_accepted(verifier, signer):
    # The type claim is EvidenceLoop-specific. Its absence is not a refusal, only a wrong value is.
    assert verifier.verify(mint(signer, type=None)).sub == "42"


def test_clock_skew_within_the_leeway_is_tolerated(verifier, signer):
    now = int(time.time())
    assert verifier.verify(mint(signer, iat=now - 1800, exp=now - 10)).sub == "42"


def test_the_jwk_set_is_fetched_once_and_cached(verifier, signer, jwks):
    for _ in range(5):
        verifier.verify(mint(signer))
    assert jwks.requests == 1


# --- what is refused -----------------------------------------------------------------------


@pytest.mark.parametrize("aud", [["evidenceloop"], ["assay"], "evidenceloop", ["evidence-assistant-staging"]])
def test_a_token_for_another_audience_is_refused(verifier, signer, aud):
    # ["evidenceloop"] is what EvidenceLoop puts on refresh, reset and OAuth-state tokens.
    with pytest.raises(EvidenceLoopTokenError):
        verifier.verify(mint(signer, aud=aud))


def test_a_token_from_another_issuer_is_refused(verifier, signer):
    with pytest.raises(EvidenceLoopTokenError):
        verifier.verify(mint(signer, iss="https://someone-else.example"))


def test_an_expired_token_is_refused(verifier, signer):
    now = int(time.time())
    with pytest.raises(EvidenceLoopTokenError, match="expired"):
        verifier.verify(mint(signer, iat=now - 3600, exp=now - 120))


def test_an_unknown_kid_is_refused_after_at_most_one_refetch(verifier, signer, jwks):
    stranger = Signer()
    forged = jwt.encode(claims(), stranger.key, algorithm="ES256", headers={"kid": "nope"})
    verifier.verify(mint(signer))  # warm the cache
    for _ in range(3):
        with pytest.raises(EvidenceLoopTokenError, match="unknown signing key"):
            verifier.verify(forged)
    # The cooldown stops a stream of made-up kids from hammering EvidenceLoop.
    assert jwks.requests == 1


def test_a_known_kid_with_a_foreign_signature_is_refused(verifier, signer):
    stranger = Signer()
    forged = jwt.encode(claims(), stranger.key, algorithm="ES256", headers={"kid": signer.kid})
    with pytest.raises(EvidenceLoopTokenError):
        verifier.verify(forged)


def test_alg_none_is_refused(verifier, signer):
    with pytest.raises(EvidenceLoopTokenError, match="algorithm"):
        verifier.verify(forge({"alg": "none", "kid": signer.kid, "typ": "JWT"}, claims()))


def test_hs256_signed_with_the_public_key_is_refused(verifier, signer, jwks):
    # Algorithm confusion: an HMAC whose secret is the published public key.
    unsigned = forge({"alg": "HS256", "kid": signer.kid, "typ": "JWT"}, claims()).rsplit(".", 1)[0]
    mac = hmac.new(signer.public_pem(), unsigned.encode(), hashlib.sha256).digest()
    token = f"{unsigned}.{base64.urlsafe_b64encode(mac).rstrip(b'=').decode()}"
    with pytest.raises(EvidenceLoopTokenError, match="algorithm"):
        verifier.verify(token)
    assert jwks.requests == 0  # refused before any key was looked up


def test_an_hs256_token_with_a_guessable_secret_is_refused(verifier, signer):
    token = jwt.encode(claims(), "dev-jwt-secret-change-me-but-long-enough", algorithm="HS256",
                       headers={"kid": signer.kid})
    with pytest.raises(EvidenceLoopTokenError, match="algorithm"):
        verifier.verify(token)


def test_a_token_without_kid_is_refused(verifier, signer):
    token = jwt.encode(claims(), signer.key, algorithm="ES256")
    with pytest.raises(EvidenceLoopTokenError, match="key id"):
        verifier.verify(token)


@pytest.mark.parametrize("missing", ["exp", "iat", "jti", "sub", "iss", "aud"])
def test_a_token_missing_a_required_claim_is_refused(verifier, signer, missing):
    with pytest.raises(EvidenceLoopTokenError):
        verifier.verify(mint(signer, **{missing: None}))


@pytest.mark.parametrize("token_type", ["refresh", "password_reset", "oauth_state"])
def test_a_non_access_token_is_refused_even_if_addressed_here(verifier, signer, token_type):
    with pytest.raises(EvidenceLoopTokenError, match="access"):
        verifier.verify(mint(signer, type=token_type, aud=[AUDIENCE]))


def test_a_key_of_the_wrong_kind_under_the_kid_is_refused(jwks, signer):
    # An RSA key published under the token's kid must not be used to check an ES256 token.
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwks.keys = [{**RSAAlgorithm.to_jwk(rsa_key.public_key(), as_dict=True),
                  "kid": signer.kid, "use": "sig", "alg": "RS256"}]
    with pytest.raises(EvidenceLoopTokenError):
        make_verifier(jwks).verify(mint(signer))


@pytest.mark.parametrize("token", ["", "not-a-jwt", "a.b.c", "....", "eyJhbGciOiJFUzI1NiJ9"])
def test_malformed_tokens_are_refused(verifier, token):
    with pytest.raises(EvidenceLoopTokenError):
        verifier.verify(token)


# --- the PKCE flow's tokens (sr-platform D16): typ at+jwt and client_id -------------------


def test_with_a_client_id_an_rfc9068_token_for_this_client_is_accepted(jwks, signer):
    verifier = make_verifier(jwks, client_id=CLIENT_ID)
    for typ in ("at+jwt", "application/at+jwt", "AT+JWT"):
        token = mint(signer, headers={"typ": typ}, aud=[AUDIENCE], client_id=CLIENT_ID)
        assert verifier.verify(token).sub == "42"


def test_with_a_client_id_a_first_party_evidenceloop_token_is_refused(jwks, signer):
    # EvidenceLoop's own front-end token: typ JWT, no client_id.
    with pytest.raises(EvidenceLoopTokenError, match="RFC 9068"):
        make_verifier(jwks, client_id=CLIENT_ID).verify(mint(signer))


def test_with_a_client_id_a_token_issued_to_another_client_is_refused(jwks, signer):
    token = mint(signer, headers={"typ": "at+jwt"}, aud=[AUDIENCE], client_id="assay-web")
    with pytest.raises(EvidenceLoopTokenError, match="another client"):
        make_verifier(jwks, client_id=CLIENT_ID).verify(token)


# --- key rotation and outages ----------------------------------------------------------------


def test_a_rotated_key_is_picked_up_by_one_refetch(jwks, signer):
    verifier = make_verifier(jwks, cooldown=0)
    verifier.verify(mint(signer))
    new = Signer()
    jwks.keys = [new.jwk(), signer.jwk()]  # EvidenceLoop lists the new key first, the old one still
    assert verifier.verify(mint(new)).sub == "42"
    assert verifier.verify(mint(signer)).sub == "42"
    assert jwks.requests == 2


def test_a_retired_key_stops_working_once_it_is_unlisted_and_the_cache_expires(jwks, signer):
    client = PyJWKClient(jwks.url, lifespan=0.01, cooldown_duration=0)
    verifier = EvidenceLoopVerifier(issuer=ISSUER, jwks_url=jwks.url, audience=AUDIENCE, jwks_client=client)
    old_token = mint(signer)
    assert verifier.verify(old_token).sub == "42"
    jwks.keys = [Signer().jwk()]
    time.sleep(0.05)
    with pytest.raises(EvidenceLoopTokenError, match="unknown signing key"):
        verifier.verify(old_token)


def test_an_unreachable_jwk_set_is_an_outage_not_a_bad_token(jwks, signer):
    jwks.status = 500
    with pytest.raises(EvidenceLoopUnavailable):
        make_verifier(jwks).verify(mint(signer))


def test_a_jwk_set_with_no_usable_keys_is_an_outage(jwks, signer):
    jwks.keys = []
    with pytest.raises(EvidenceLoopUnavailable):
        make_verifier(jwks).verify(mint(signer))


def test_a_failed_refetch_keeps_the_cached_keys(jwks, signer):
    verifier = make_verifier(jwks, cooldown=0)
    verifier.verify(mint(signer))
    jwks.status = 500
    # An unknown kid forces a refetch, which fails. The good key must still be usable afterwards.
    with pytest.raises((EvidenceLoopTokenError, EvidenceLoopUnavailable)):
        verifier.verify(jwt.encode(claims(), Signer().key, algorithm="ES256", headers={"kid": "new"}))
    assert verifier.verify(mint(signer)).sub == "42"


# --- configuration ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", ["http://evidenceloop.example/.well-known/jwks.json",
                                 "file:///etc/passwd", "ftp://x/jwks.json", "", "https://"])
def test_an_insecure_or_odd_jwks_url_is_refused_at_construction(url):
    with pytest.raises(ValueError):
        EvidenceLoopVerifier(issuer=ISSUER, jwks_url=url, audience=AUDIENCE)


def test_https_and_local_http_jwks_urls_are_allowed():
    EvidenceLoopVerifier(issuer=ISSUER, jwks_url="https://api.example/.well-known/jwks.json", audience=AUDIENCE)
    EvidenceLoopVerifier(issuer=ISSUER, jwks_url="http://localhost:8000/.well-known/jwks.json", audience=AUDIENCE)


def test_settings_refuse_the_flag_without_issuer_and_jwks_url():
    with pytest.raises(ValueError, match="EVIDENCELOOP_ISSUER"):
        Settings(_env_file=None, evidenceloop_auth_enabled=True)
    with pytest.raises(ValueError):
        Settings(_env_file=None, evidenceloop_auth_enabled=True, evidenceloop_issuer=ISSUER)
    ok = Settings(_env_file=None, evidenceloop_auth_enabled=True, evidenceloop_issuer=ISSUER,
                  evidenceloop_jwks_url="https://api.example/.well-known/jwks.json")
    assert ok.evidenceloop_audience == AUDIENCE


def test_the_flag_is_off_by_default():
    assert Settings(_env_file=None).evidenceloop_auth_enabled is False


# --- routing between Supabase and EvidenceLoop ------------------------------------------------


SUPABASE_USER = supabase_auth.AuthenticatedUser(id="00000000-0000-0000-0000-000000000001",
                                                email="s@example.org", role="authenticated")


APP_USER_ID = "5f0c6a52-58a4-4d8e-9a43-0b6a3c1f2e77"


class FakeSupabase:
    """Stands in for the service-role client: records rpc calls and returns one app-user id."""

    def __init__(self, data: Any = APP_USER_ID, error: Exception | None = None) -> None:
        self.data, self.error, self.calls = data, error, []

    def rpc(self, name: str, params: dict[str, Any]):
        self.calls.append((name, params))
        outer = self

        class _Query:
            def execute(self):
                if outer.error:
                    raise outer.error
                return SimpleNamespace(data=outer.data)

        return _Query()


@pytest.fixture
def database(monkeypatch) -> FakeSupabase:
    fake = FakeSupabase()
    monkeypatch.setattr(tokens, "app_user_directory", AppUserDirectory(client_factory=lambda: fake))
    return fake


@pytest.fixture
def routing(monkeypatch, jwks, database):
    """Settings for the dispatcher, a recording Supabase verifier, the test JWK Set, a fake database."""
    seen: list[str] = []

    def fake_supabase(token: str):
        seen.append(token)
        return SUPABASE_USER if token == "supabase-good" else None

    monkeypatch.setattr(tokens, "verify_supabase_token", fake_supabase)
    monkeypatch.setattr(supabase_auth, "verify_supabase_token", fake_supabase)
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.test")
    monkeypatch.setattr(settings, "evidenceloop_issuer", ISSUER)
    monkeypatch.setattr(settings, "evidenceloop_jwks_url", jwks.url)
    monkeypatch.setattr(settings, "evidenceloop_audience", AUDIENCE)
    monkeypatch.setattr(settings, "evidenceloop_client_id", "")
    get_evidenceloop_verifier.cache_clear()
    yield seen
    get_evidenceloop_verifier.cache_clear()


def test_with_the_flag_off_evidenceloop_tokens_go_to_supabase_untouched(routing, monkeypatch, signer, jwks):
    monkeypatch.setattr(settings, "evidenceloop_auth_enabled", False)
    token = mint(signer)
    assert tokens.verify_bearer_token(token) is None
    assert routing == [token]
    assert jwks.requests == 0


def test_with_the_flag_on_supabase_tokens_still_go_to_supabase(routing, monkeypatch):
    monkeypatch.setattr(settings, "evidenceloop_auth_enabled", True)
    assert tokens.verify_bearer_token("supabase-good") is SUPABASE_USER
    supabase_shaped = jwt.encode({"iss": "https://project.supabase.test/auth/v1", "sub": "x"},
                                 "a-supabase-secret-of-sufficient-length", algorithm="HS256")
    assert tokens.verify_bearer_token(supabase_shaped) is None
    assert routing == ["supabase-good", supabase_shaped]


def test_with_the_flag_on_a_valid_evidenceloop_token_becomes_its_app_user(routing, monkeypatch, signer, database):
    monkeypatch.setattr(settings, "evidenceloop_auth_enabled", True)
    user = tokens.verify_bearer_token(mint(signer))
    assert (user.id, user.provider, user.role) == (APP_USER_ID, "evidenceloop", "authenticated")
    assert database.calls == [("app_user_for_evidenceloop", {"p_issuer": ISSUER, "p_sub": "42"})]
    assert routing == []  # never shown to the Supabase verifier


def test_a_bad_evidenceloop_token_never_reaches_the_database(routing, monkeypatch, signer, database):
    monkeypatch.setattr(settings, "evidenceloop_auth_enabled", True)
    assert tokens.verify_bearer_token(mint(signer, iss=ISSUER, aud=["assay"])) is None
    assert database.calls == []


def test_with_the_flag_on_a_database_outage_is_503(routing, monkeypatch, signer, database):
    monkeypatch.setattr(settings, "evidenceloop_auth_enabled", True)
    database.error = ConnectionError("database unreachable")
    with pytest.raises(HTTPException) as caught:
        tokens.verify_bearer_token(mint(signer))
    assert caught.value.status_code == 503


def test_with_the_flag_on_a_bad_evidenceloop_token_is_401_not_a_supabase_retry(routing, monkeypatch, signer):
    monkeypatch.setattr(settings, "evidenceloop_auth_enabled", True)
    assert tokens.verify_bearer_token(mint(signer, aud=["evidenceloop"])) is None
    assert routing == []


def test_with_the_flag_on_an_evidenceloop_outage_is_503(routing, monkeypatch, signer, jwks):
    monkeypatch.setattr(settings, "evidenceloop_auth_enabled", True)
    jwks.status = 503
    with pytest.raises(HTTPException) as caught:
        tokens.verify_bearer_token(mint(signer))
    assert caught.value.status_code == 503


# --- through FastAPI's dependencies -----------------------------------------------------------


@pytest.fixture
def app_client(routing) -> TestClient:
    app = FastAPI()

    @app.get("/private")
    async def private(user=Depends(supabase_auth.get_current_user)):
        return {"id": user.id}

    @app.get("/public")
    async def public(user=Depends(supabase_auth.get_optional_user)):
        return {"id": user.id if user else None}

    return TestClient(app)


@pytest.mark.parametrize("enabled", [False, True])
def test_supabase_sign_in_behaves_the_same_with_the_flag_on_or_off(app_client, monkeypatch, enabled):
    monkeypatch.setattr(settings, "evidenceloop_auth_enabled", enabled)
    ok = {"Authorization": "Bearer supabase-good"}
    bad = {"Authorization": "Bearer supabase-bad"}
    assert app_client.get("/private", headers=ok).json() == {"id": SUPABASE_USER.id}
    assert app_client.get("/private", headers=bad).status_code == 401
    assert app_client.get("/private").status_code == 401
    assert app_client.get("/public", headers=ok).json() == {"id": SUPABASE_USER.id}
    assert app_client.get("/public").json() == {"id": None}


def test_evidenceloop_tokens_through_the_dependencies(app_client, monkeypatch, signer):
    monkeypatch.setattr(settings, "evidenceloop_auth_enabled", True)
    good = {"Authorization": f"Bearer {mint(signer)}"}
    wrong_aud = {"Authorization": f"Bearer {mint(signer, aud=['assay'])}"}
    assert app_client.get("/private", headers=good).json() == {"id": APP_USER_ID}
    assert app_client.get("/public", headers=good).json() == {"id": APP_USER_ID}
    assert app_client.get("/private", headers=wrong_aud).status_code == 401
    assert app_client.get("/public", headers=wrong_aud).json() == {"id": None}


def test_an_evidenceloop_user_reaches_their_own_private_project_and_not_others(routing, monkeypatch, signer):
    # authorize_project compares the project's user_id with user.id. For an EvidenceLoop user, that id is
    # the app-user id, so ownership works as it does for Supabase users once migration B is applied.
    import api.routes.dependencies as deps

    monkeypatch.setattr(settings, "evidenceloop_auth_enabled", True)
    mine = {"id": "p1", "user_id": APP_USER_ID, "is_public": False}
    theirs = {"id": "p2", "user_id": SUPABASE_USER.id, "is_public": False}
    monkeypatch.setattr(deps, "resolve_project", {"p1": mine, "p2": theirs}.get)
    user = tokens.verify_bearer_token(mint(signer))
    assert deps.authorize_project("p1", user) is mine
    with pytest.raises(HTTPException) as caught:
        deps.authorize_project("p2", user)
    assert caught.value.status_code == 403


# --- the app-user directory -------------------------------------------------------------------


def test_the_directory_caches_and_expires(monkeypatch):
    fake, now = FakeSupabase(), [1000.0]
    directory = AppUserDirectory(client_factory=lambda: fake, ttl_seconds=300, clock=lambda: now[0])
    assert directory.for_evidenceloop(ISSUER, "42") == APP_USER_ID
    assert directory.for_evidenceloop(ISSUER, "42") == APP_USER_ID
    assert len(fake.calls) == 1
    now[0] += 301
    directory.for_evidenceloop(ISSUER, "42")
    assert len(fake.calls) == 2


def test_the_directory_keys_on_issuer_and_subject(monkeypatch):
    fake = FakeSupabase()
    directory = AppUserDirectory(client_factory=lambda: fake)
    directory.for_evidenceloop(ISSUER, "42")
    directory.for_evidenceloop("https://staging.evidenceloop.test", "42")
    directory.for_evidenceloop(ISSUER, "43")
    assert [c[1] for c in fake.calls] == [
        {"p_issuer": ISSUER, "p_sub": "42"},
        {"p_issuer": "https://staging.evidenceloop.test", "p_sub": "42"},
        {"p_issuer": ISSUER, "p_sub": "43"},
    ]


@pytest.mark.parametrize("data", [APP_USER_ID, [APP_USER_ID], [{"app_user_for_evidenceloop": APP_USER_ID}]])
def test_the_directory_reads_the_shapes_postgrest_returns(data):
    assert AppUserDirectory(client_factory=lambda: FakeSupabase(data=data)).for_evidenceloop(ISSUER, "42") == APP_USER_ID


@pytest.mark.parametrize("data", [None, "", "42", [], [APP_USER_ID, APP_USER_ID], {"id": "nope"}])
def test_the_directory_refuses_anything_but_one_uuid(data):
    with pytest.raises(AppUserUnavailable):
        AppUserDirectory(client_factory=lambda: FakeSupabase(data=data)).for_evidenceloop(ISSUER, "42")


def test_a_failed_lookup_is_not_cached():
    fake = FakeSupabase(error=RuntimeError("relation app_users does not exist"))
    directory = AppUserDirectory(client_factory=lambda: fake)
    with pytest.raises(AppUserUnavailable):
        directory.for_evidenceloop(ISSUER, "42")
    fake.error = None
    assert directory.for_evidenceloop(ISSUER, "42") == APP_USER_ID


@pytest.mark.parametrize("issuer,sub", [("", "42"), (ISSUER, "")])
def test_the_directory_needs_issuer_and_subject(issuer, sub):
    with pytest.raises(ValueError):
        AppUserDirectory(client_factory=FakeSupabase).for_evidenceloop(issuer, sub)
