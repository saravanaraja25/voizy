"""Bearer-token authentication and permission checks."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from voizy_core.apikeys import Principal, authenticate_api_key
from voizy_core.permissions import Permission

_bearer = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "invalid or missing credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def current_principal(
    request: Request,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    if creds is None:
        raise _unauthorized()
    async with request.app.state.pool.connection() as conn:
        principal = await authenticate_api_key(conn, creds.credentials)
    if principal is None:
        raise _unauthorized()
    return principal


def require(permission: Permission) -> Callable[..., Awaitable[Principal]]:
    async def dependency(
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> Principal:
        if permission not in principal.permissions:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "missing permission")
        return principal

    return dependency
