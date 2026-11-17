"""
Supabase Authentication Module

Handles JWT token verification and user authentication for multi-tenant RAG.
"""

from typing import Optional
from dataclasses import dataclass
from functools import lru_cache

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from supabase import create_client, Client

from src.config.settings import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)

# HTTP Bearer token scheme
bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class AuthenticatedUser:
    """Represents an authenticated user from Supabase."""
    id: str  # UUID
    email: str
    role: str  # 'authenticated', 'anon', etc.
    
    
@lru_cache()
def get_supabase_client() -> Client:
    """
    Get a cached Supabase client using the service role key.
    
    Service role key bypasses RLS for admin operations.
    """
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise ValueError("Supabase URL and service role key must be configured")
    
    return create_client(
        settings.supabase_url,
        settings.supabase_service_role_key
    )


def get_supabase_anon_client() -> Client:
    """
    Get a Supabase client using the anon key.
    
    Use this for operations that should respect RLS.
    """
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise ValueError("Supabase URL and anon key must be configured")
    
    return create_client(
        settings.supabase_url,
        settings.supabase_anon_key
    )


# Supabase/PostgREST caps a single response at 1,000 rows (the project's Max Rows
# setting), so any select that can match more than that must be paged, or the caller
# silently sees a truncated set.
SUPABASE_PAGE_SIZE = 1000


def fetch_all_rows(make_query, page_size: int = SUPABASE_PAGE_SIZE) -> list:
    """Run a Supabase select to completion, paging past the 1,000-row response cap.

    ``make_query`` must be a zero-argument callable returning a fresh query builder
    each time, for example ``lambda: client.table("documents").select("id")``.
    """
    rows: list = []
    start = 0
    while True:
        batch = make_query().range(start, start + page_size - 1).execute().data or []
        rows.extend(batch)
        if len(batch) < page_size:
            return rows
        start += page_size


def update_by_ids(client, table: str, ids: list, payload: dict, chunk: int = 500) -> None:
    """Update rows by id in chunks, keeping the request filter within URL limits."""
    for i in range(0, len(ids), chunk):
        client.table(table).update(payload).in_("id", ids[i:i + chunk]).execute()


def document_counts_by_project(client) -> dict:
    """Per-project document and chunk counts.

    Uses the Postgres aggregate ``document_counts_by_project`` when it is present and
    falls back to paging the documents table otherwise. Returns
    ``{project_id: {"docs": int, "chunks": int}}``.
    """
    try:
        rows = client.rpc("document_counts_by_project").execute().data or []
        return {
            r["project_id"]: {"docs": int(r["doc_count"] or 0),
                              "chunks": int(r["chunk_count"] or 0)}
            for r in rows
        }
    except Exception:
        counts: dict = {}
        for d in fetch_all_rows(
            lambda: client.table("documents").select("rag_project_id, chunk_count")
        ):
            project_id = d.get("rag_project_id")
            if project_id:
                entry = counts.setdefault(project_id, {"docs": 0, "chunks": 0})
                entry["docs"] += 1
                entry["chunks"] += d.get("chunk_count") or 0
        return counts


def usage_by_user(client) -> dict:
    """Per-user query count and cost.

    Uses the Postgres aggregate ``usage_by_user`` when it is present and falls back to
    paging usage_logs otherwise. Returns ``{user_id: {"queries": int, "cost": float}}``.
    """
    try:
        rows = client.rpc("usage_by_user").execute().data or []
        return {
            r["user_id"]: {"queries": int(r["queries"] or 0), "cost": float(r["cost"] or 0)}
            for r in rows
        }
    except Exception:
        out: dict = {}
        for log in fetch_all_rows(
            lambda: client.table("usage_logs").select("user_id, cost_usd")
        ):
            user_id = log.get("user_id")
            if user_id:
                entry = out.setdefault(user_id, {"queries": 0, "cost": 0.0})
                entry["queries"] += 1
                entry["cost"] += float(log.get("cost_usd") or 0)
        return out


def verify_supabase_token(token: str) -> Optional[AuthenticatedUser]:
    """
    Verify a Supabase JWT token and extract user info.
    
    Args:
        token: JWT token from Authorization header
        
    Returns:
        AuthenticatedUser if valid, None otherwise
    """
    if not settings.supabase_jwt_secret:
        logger.warning("SUPABASE_JWT_SECRET not configured - using Supabase API for verification")
        return verify_token_via_api(token)
    
    try:
        # Verify JWT with secret
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated"
        )
        
        user_id = payload.get("sub")
        email = payload.get("email", "")
        role = payload.get("role", "authenticated")
        
        if not user_id:
            return None
            
        return AuthenticatedUser(
            id=user_id,
            email=email,
            role=role
        )
        
    except JWTError as e:
        logger.debug(f"JWT verification failed: {e}")
        return None


def verify_token_via_api(token: str) -> Optional[AuthenticatedUser]:
    """
    Verify token by calling Supabase API.
    
    Fallback when JWT secret is not available.
    """
    try:
        client = get_supabase_anon_client()
        # Get user from token
        response = client.auth.get_user(token)
        
        if response and response.user:
            return AuthenticatedUser(
                id=response.user.id,
                email=response.user.email or "",
                role=response.user.role or "authenticated"
            )
    except Exception as e:
        logger.debug(f"Token verification via API failed: {e}")
    
    return None


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> AuthenticatedUser:
    """
    FastAPI dependency to get the current authenticated user.
    
    Usage:
        @app.get("/api/protected")
        async def protected_route(user: AuthenticatedUser = Depends(get_current_user)):
            return {"user_id": user.id}
    """
    # Check if Supabase is configured
    if not settings.supabase_url:
        # Supabase not configured - fall back to legacy auth
        logger.debug("Supabase not configured, using legacy auth")
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Multi-tenant auth requires Supabase configuration"
        )
    
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    user = verify_supabase_token(token)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Optional[AuthenticatedUser]:
    """
    FastAPI dependency to get the current user if authenticated, None otherwise.
    
    Useful for endpoints that work for both authenticated and anonymous users.
    """
    if not credentials or not settings.supabase_url:
        return None
    
    return verify_supabase_token(credentials.credentials)


def is_multi_tenant_enabled() -> bool:
    """Check if multi-tenant mode is enabled (Supabase configured)."""
    return bool(settings.supabase_url and settings.supabase_anon_key)
