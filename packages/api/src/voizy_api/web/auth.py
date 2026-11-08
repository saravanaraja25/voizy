"""Authentication: an API key (Authorization: Bearer) or a session cookie.

Cookie-authenticated requests that change state must also prove they came from our own pages:
a per-session CSRF token in X-CSRF-Token, and an Origin that is on the allowlist. API-key
requests need neither, because a browser never attaches those credentials on its own.
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from voizy_core.domain.permissions import Permission
from voizy_core.services.accounts import resolve_session
from voizy_core.services.auth import Principal, authenticate_api_key

SESSION_COOKIE = "voizy_session"
CSRF_HEADER = "x-csrf-token"
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_bearer = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "invalid or missing credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def check_origin(request: Request) -> None:
    """Reject browser requests from an origin we do not serve. No Origin header = not a browser."""
    origin = request.headers.get("origin")
    if origin is not None and origin not in request.app.state.settings.cors_origins:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "origin not allowed")


async def current_principal(
    request: Request,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    pool = request.app.state.pool
    if creds is not None:
        async with pool.connection() as conn:
            principal = await authenticate_api_key(conn, creds.credentials)
        if principal is None:
            raise _unauthorized()
        return principal

    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise _unauthorized()
    async with pool.connection() as conn:
        principal = await resolve_session(conn, token)
    if principal is None:
        raise _unauthorized()
    if request.method in _UNSAFE_METHODS:
        check_origin(request)
        sent = request.headers.get(CSRF_HEADER, "")
        if not principal.csrf_token or not secrets.compare_digest(sent, principal.csrf_token):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "missing or invalid CSRF token")
    return principal


def require(permission: Permission) -> Callable[..., Awaitable[Principal]]:
    async def dependency(
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> Principal:
        if permission not in principal.permissions:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "missing permission")
        return principal

    return dependency
