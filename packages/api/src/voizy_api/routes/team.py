"""Members and invitations, with the escalation rules enforced."""

from __future__ import annotations

import asyncio
import uuid
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from voizy_core.db.pool import workspace_tx
from voizy_core.domain.permissions import Permission
from voizy_core.security.authz import (
    AuthzError,
    check_can_assign_role,
    check_member_change_keeps_owner,
)
from voizy_core.security.passwords import PasswordPolicyError, check_policy, hash_password
from voizy_core.services import accounts
from voizy_core.services.auth import Principal

from voizy_api.routes.auth import _too_many, client_ip, session_response
from voizy_api.schemas.auth import AcceptInvite
from voizy_api.schemas.session import MeOut
from voizy_api.schemas.team import (
    AssignableRole,
    InviteCreate,
    InviteCreated,
    InviteOut,
    InvitePreview,
    MemberOut,
    MemberRoleChange,
)
from voizy_api.web.auth import check_origin, require
from voizy_api.web.common import audit, not_found

router = APIRouter(prefix="/v1", tags=["team"])
Manager = Annotated[Principal, Depends(require(Permission.MEMBERS_MANAGE))]


def _member(m: accounts.Member) -> MemberOut:
    return MemberOut(
        user_id=m.user_id,
        email=m.email,
        display_name=m.display_name,
        role_id=m.role_id,
        role_name=m.role_name,
        joined_at=m.joined_at,
        last_login_at=m.last_login_at,
    )


# ---- members ---------------------------------------------------------------------------------


@router.get("/assignable-roles", response_model=list[AssignableRole])
async def assignable_roles(request: Request, p: Manager) -> list[AssignableRole]:
    """Roles the caller may hand out: never one that carries a permission the caller lacks."""
    async with workspace_tx(request.app.state.pool, p.workspace_id) as conn:
        cur = await conn.execute(
            "SELECT r.id, r.name, "
            "coalesce(array_agg(rp.permission) FILTER (WHERE rp.permission IS NOT NULL), '{}') "
            "FROM roles r LEFT JOIN role_permissions rp "
            "ON rp.workspace_id = r.workspace_id AND rp.role_id = r.id "
            "GROUP BY r.workspace_id, r.id ORDER BY r.name"
        )
        rows = await cur.fetchall()
    out: list[AssignableRole] = []
    for rid, name, perms in rows:
        held = {Permission(x) for x in perms if x in Permission._value2member_map_}
        if held <= p.permissions:
            out.append(AssignableRole(id=rid, name=name))
    return out


@router.get("/members", response_model=list[MemberOut])
async def list_members(request: Request, p: Manager) -> list[MemberOut]:
    async with request.app.state.pool.connection() as conn:
        return [_member(m) for m in await accounts.list_members(conn, p.workspace_id)]


async def _target_and_views(
    request: Request, p: Principal, user_id: uuid.UUID
) -> tuple[dict[str, object], object]:
    async with request.app.state.pool.connection() as conn:
        views = await accounts.role_views_by_user(conn, p.workspace_id)
    current = views.get(str(user_id))
    if current is None:
        raise not_found()
    # Someone whose role outranks yours is not yours to change or remove.
    if not current.permissions <= p.permissions:
        raise AuthzError("you cannot change a member whose role outranks yours")
    return dict(views), current


@router.put("/members/{user_id}/role", response_model=MemberOut)
async def change_member_role(
    user_id: uuid.UUID, body: MemberRoleChange, request: Request, p: Manager
) -> MemberOut:
    async with request.app.state.pool.connection() as conn:
        new_role = await accounts.role_view(conn, p.workspace_id, body.role_id)
    if new_role is None:
        raise not_found()
    check_can_assign_role(p.permissions, new_role)
    views, current = await _target_and_views(request, p, user_id)
    check_member_change_keeps_owner(views, str(user_id), new_role)  # type: ignore[arg-type]

    async with workspace_tx(request.app.state.pool, p.workspace_id) as conn:
        await conn.execute(
            "UPDATE memberships SET role_id = %s WHERE user_id = %s", (body.role_id, user_id)
        )
        await audit(
            conn,
            p,
            "member.role_change",
            "user",
            user_id,
            before=getattr(current, "name", None),
            after=new_role.name,
        )
    async with request.app.state.pool.connection() as conn:
        members = await accounts.list_members(conn, p.workspace_id)
    return _member(next(m for m in members if m.user_id == user_id))


@router.delete("/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(user_id: uuid.UUID, request: Request, p: Manager) -> None:
    views, current = await _target_and_views(request, p, user_id)
    check_member_change_keeps_owner(views, str(user_id), None)  # type: ignore[arg-type]
    async with workspace_tx(request.app.state.pool, p.workspace_id) as conn:
        # Deleting the membership also ends that user's sessions (foreign-key cascade).
        await conn.execute("DELETE FROM memberships WHERE user_id = %s", (user_id,))
        await audit(conn, p, "member.remove", "user", user_id, role=getattr(current, "name", None))


# ---- invitations (managed by admins) ---------------------------------------------------------


@router.post("/invites", response_model=InviteCreated, status_code=status.HTTP_201_CREATED)
async def create_invite(body: InviteCreate, request: Request, p: Manager) -> InviteCreated:
    pool = request.app.state.pool
    async with pool.connection() as conn:
        role = await accounts.role_view(conn, p.workspace_id, body.role_id)
    if role is None:
        raise not_found()
    check_can_assign_role(p.permissions, role)  # cannot invite someone above your own rank
    try:
        async with pool.connection() as conn:
            invite = await accounts.create_invite(conn, p, email=body.email, role_id=body.role_id)
    except psycopg.errors.UniqueViolation:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "There is already a pending invitation for that email."
        ) from None
    async with workspace_tx(pool, p.workspace_id) as conn:
        await audit(conn, p, "invite.create", "invite", invite.id, role=role.name)
    return InviteCreated(
        id=invite.id,
        email=accounts.normalize_email(body.email),
        role_name=role.name,
        expires_at=invite.expires_at,
        created_at=invite.expires_at - accounts.INVITE_TTL,
        token=invite.token,
        invite_path=f"/invite/{invite.token}",
    )


@router.get("/invites", response_model=list[InviteOut])
async def list_invites(request: Request, p: Manager) -> list[InviteOut]:
    async with workspace_tx(request.app.state.pool, p.workspace_id) as conn:
        cur = await conn.execute(
            "SELECT i.id, i.email, r.name, i.expires_at, i.created_at FROM invites i "
            "JOIN roles r ON r.workspace_id = i.workspace_id AND r.id = i.role_id "
            "WHERE i.accepted_at IS NULL AND i.revoked_at IS NULL AND i.expires_at > now() "
            "ORDER BY i.created_at DESC LIMIT 200"
        )
        return [
            InviteOut(id=r[0], email=r[1], role_name=r[2], expires_at=r[3], created_at=r[4])
            for r in await cur.fetchall()
        ]


@router.delete("/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(invite_id: uuid.UUID, request: Request, p: Manager) -> None:
    async with workspace_tx(request.app.state.pool, p.workspace_id) as conn:
        cur = await conn.execute(
            "UPDATE invites SET revoked_at = now() "
            "WHERE id = %s AND accepted_at IS NULL AND revoked_at IS NULL RETURNING id",
            (invite_id,),
        )
        if await cur.fetchone() is None:
            raise not_found()
        await audit(conn, p, "invite.revoke", "invite", invite_id)


# ---- invitations (opened by the invitee, no account yet) -------------------------------------


@router.get("/invites/{token}", response_model=InvitePreview)
async def preview_invite(token: str, request: Request) -> InvitePreview:
    settings = request.app.state.settings
    ip = f"invite:{client_ip(request)}"
    if (wait := settings.ip_throttle.retry_after(ip)) > 0:
        raise _too_many(wait)
    async with request.app.state.pool.connection() as conn:
        info = await accounts.peek_invite(conn, token)
    if info is None:
        settings.ip_throttle.record_failure(ip)
        raise not_found()
    return InvitePreview(
        workspace_name=info.workspace_name,
        email=info.email,
        role_name=info.role_name,
        expires_at=info.expires_at,
    )


@router.post("/invites/{token}/accept", response_model=MeOut, status_code=status.HTTP_201_CREATED)
async def accept_invite(
    token: str, body: AcceptInvite, request: Request, response: Response
) -> MeOut:
    check_origin(request)
    settings = request.app.state.settings
    ip = f"invite:{client_ip(request)}"
    if (wait := settings.ip_throttle.retry_after(ip)) > 0:
        raise _too_many(wait)
    pool = request.app.state.pool
    async with pool.connection() as conn:
        info = await accounts.peek_invite(conn, token)
    if info is None:
        settings.ip_throttle.record_failure(ip)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This invitation is invalid or has expired.")
    try:
        check_policy(body.password, email=info.email)
    except PasswordPolicyError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    password_hash = await asyncio.to_thread(hash_password, body.password)
    try:
        async with pool.connection() as conn:
            user_id = await accounts.accept_invite(
                conn, token, display_name=body.display_name.strip(), password_hash=password_hash
            )
    except accounts.AcceptError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await session_response(request, response, user_id, info.workspace_id)
