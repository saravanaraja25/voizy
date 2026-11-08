"""First-run setup, login, logout and password change."""

from __future__ import annotations

import asyncio
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from voizy_core.db.pool import workspace_tx
from voizy_core.security.passwords import (
    PasswordPolicyError,
    check_policy,
    hash_password,
    needs_rehash,
    verify_password,
)
from voizy_core.services import accounts
from voizy_core.services.auth import Principal

from voizy_api.schemas.auth import (
    LoginRequest,
    Notice,
    PasswordChange,
    SetupRequest,
    SetupStatus,
)
from voizy_api.schemas.session import MeOut
from voizy_api.web.auth import SESSION_COOKIE, check_origin, current_principal
from voizy_api.web.common import audit

router = APIRouter(prefix="/v1", tags=["auth"])

_BAD_LOGIN = "Incorrect email or password."


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _too_many(retry_after: float) -> HTTPException:
    seconds = max(1, int(retry_after) + 1)
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "Too many attempts. Try again later.",
        headers={"Retry-After": str(seconds)},
    )


def set_session_cookie(request: Request, response: Response, token: str, max_age: int) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        secure=request.app.state.settings.cookie_secure,
        samesite="lax",
        path="/",
    )


async def session_response(
    request: Request, response: Response, user_id: object, workspace_id: object
) -> MeOut:
    """Create a session, set its cookie, and describe the signed-in user."""
    pool = request.app.state.pool
    async with pool.connection() as conn:
        session = await accounts.create_session(conn, user_id, workspace_id)  # type: ignore[arg-type]
    async with pool.connection() as conn:
        principal = await accounts.resolve_session(conn, session.token)
    if principal is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "could not start a session")
    set_session_cookie(
        request, response, session.token, int(accounts.SESSION_ABSOLUTE_TTL.total_seconds())
    )
    return await _me(request, principal)


async def _me(request: Request, p: Principal) -> MeOut:
    async with request.app.state.pool.connection() as conn:
        who = await accounts.who_am_i(conn, p)
    if who is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not signed in")
    return MeOut(
        workspace_id=p.workspace_id,
        workspace_name=who.workspace_name,
        permissions=sorted(p.permissions),
        user_id=who.user_id,
        email=who.email,
        display_name=who.display_name,
        csrf_token=p.csrf_token,
    )


@router.get("/setup/status", response_model=SetupStatus)
async def setup_status(request: Request) -> SetupStatus:
    async with request.app.state.pool.connection() as conn:
        return SetupStatus(needs_setup=await accounts.setup_needed(conn))


@router.post("/setup", response_model=MeOut, status_code=status.HTTP_201_CREATED)
async def setup(body: SetupRequest, request: Request, response: Response) -> MeOut:
    """Create the first workspace and its superadmin. Needs the token printed in the server log."""
    check_origin(request)
    settings = request.app.state.settings
    ip = f"setup:{client_ip(request)}"
    if (wait := settings.ip_throttle.retry_after(ip)) > 0:
        raise _too_many(wait)
    if not secrets.compare_digest(body.setup_token, settings.setup_token):
        settings.ip_throttle.record_failure(ip)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid setup token.")
    try:
        check_policy(body.password, email=body.email)
    except PasswordPolicyError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    password_hash = await asyncio.to_thread(hash_password, body.password)
    async with request.app.state.pool.connection() as conn:
        result = await accounts.complete_setup(
            conn,
            workspace_name=body.workspace_name.strip(),
            email=body.email,
            display_name=body.display_name.strip(),
            password_hash=password_hash,
        )
    if result is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This instance has already been set up.")
    return await session_response(request, response, result.user_id, result.workspace_id)


@router.post("/auth/login", response_model=MeOut)
async def login(body: LoginRequest, request: Request, response: Response) -> MeOut:
    check_origin(request)
    settings = request.app.state.settings
    email = accounts.normalize_email(body.email)
    ip = client_ip(request)
    wait = max(settings.email_throttle.retry_after(email), settings.ip_throttle.retry_after(ip))
    if wait > 0:
        raise _too_many(wait)

    pool = request.app.state.pool
    async with pool.connection() as conn:
        user = await accounts.find_user_for_login(conn, email)
    # Always hash-check, even for unknown accounts, so timing does not reveal which exist.
    verified = await asyncio.to_thread(
        verify_password, user.password_hash if user else None, body.password
    )
    if user is None or not verified or not user.is_active:
        settings.email_throttle.record_failure(email)
        settings.ip_throttle.record_failure(ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _BAD_LOGIN)

    async with pool.connection() as conn:
        memberships = await accounts.memberships_of(conn, user.id)
    chosen = next((m for m in memberships if body.workspace_id in (None, m.workspace_id)), None)
    if chosen is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "This account does not belong to a workspace."
        )

    settings.email_throttle.reset(email)
    rehash = None
    if user.password_hash and needs_rehash(user.password_hash):
        rehash = await asyncio.to_thread(hash_password, body.password)
    async with pool.connection() as conn:
        await accounts.record_login(conn, user.id, new_password_hash=rehash)
    return await session_response(request, response, user.id, chosen.workspace_id)


@router.post("/auth/logout", response_model=Notice)
async def logout(
    request: Request,
    response: Response,
    _: Annotated[Principal, Depends(current_principal)],
) -> Notice:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        async with request.app.state.pool.connection() as conn:
            await accounts.destroy_session(conn, token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return Notice(detail="signed out")


@router.post("/auth/password", response_model=Notice)
async def change_password(
    body: PasswordChange,
    request: Request,
    p: Annotated[Principal, Depends(current_principal)],
) -> Notice:
    if p.user_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only signed-in users have a password.")
    settings = request.app.state.settings
    key = f"pw:{p.user_id}"
    if (wait := settings.email_throttle.retry_after(key)) > 0:
        raise _too_many(wait)
    pool = request.app.state.pool
    async with pool.connection() as conn:
        who = await accounts.who_am_i(conn, p)
        user = await accounts.find_user_for_login(conn, who.email) if who else None
    ok = await asyncio.to_thread(
        verify_password, user.password_hash if user else None, body.current_password
    )
    if user is None or not ok:
        settings.email_throttle.record_failure(key)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Current password is incorrect.")
    try:
        check_policy(body.new_password, email=user.email)
    except PasswordPolicyError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    new_hash = await asyncio.to_thread(hash_password, body.new_password)
    async with pool.connection() as conn:
        await accounts.set_password(conn, user.id, new_hash)
    # A changed password ends every other session; this one continues.
    async with pool.connection() as conn:
        await accounts.destroy_user_sessions(
            conn, user.id, except_token=request.cookies.get(SESSION_COOKIE)
        )
    async with workspace_tx(pool, p.workspace_id) as conn:
        await audit(conn, p, "user.password_change", "user", user.id)
    settings.email_throttle.reset(key)
    return Notice(detail="password changed")
