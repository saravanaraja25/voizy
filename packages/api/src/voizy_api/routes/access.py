"""Roles, permission catalog and API-key management, with escalation prevention."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, status
from psycopg import AsyncConnection
from voizy_core.db.pool import workspace_tx
from voizy_core.domain.permissions import DANGEROUS_PERMISSIONS, Permission
from voizy_core.security.apikeys import generate_api_key
from voizy_core.security.authz import (
    RoleView,
    api_key_permissions,
    check_can_edit_role,
    check_can_grant,
)
from voizy_core.services.auth import Principal

from voizy_api.schemas.access import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyOut,
    PermissionOut,
    RoleCreate,
    RoleOut,
    RoleUpdate,
)
from voizy_api.web.auth import require
from voizy_api.web.common import audit, not_found, returned

router = APIRouter(prefix="/v1", tags=["access"])


def _view(role_id: str, name: str, locked: bool, perms: list[str]) -> RoleView:
    return RoleView(role_id, name, frozenset(Permission(p) for p in perms), locked)


async def _role_out(conn: AsyncConnection, role_id: uuid.UUID) -> RoleOut:
    cur = await conn.execute(
        "SELECT r.id, r.name, r.is_system, r.is_locked, "
        "coalesce(array_agg(rp.permission ORDER BY rp.permission) "
        "FILTER (WHERE rp.permission IS NOT NULL), '{}') "
        "FROM roles r LEFT JOIN role_permissions rp "
        "ON rp.workspace_id = r.workspace_id AND rp.role_id = r.id "
        "WHERE r.id = %s GROUP BY r.workspace_id, r.id",
        (role_id,),
    )
    row = returned(await cur.fetchone())
    return RoleOut(id=row[0], name=row[1], is_system=row[2], is_locked=row[3], permissions=row[4])


async def _set_permissions(
    conn: AsyncConnection, workspace_id: uuid.UUID, role_id: uuid.UUID, perms: list[Permission]
) -> None:
    await conn.execute("DELETE FROM role_permissions WHERE role_id = %s", (role_id,))
    for perm in sorted(set(perms)):
        await conn.execute(
            "INSERT INTO role_permissions (workspace_id, role_id, permission) VALUES (%s, %s, %s)",
            (workspace_id, role_id, perm.value),
        )


@router.get("/permissions", response_model=list[PermissionOut])
async def permission_catalog(
    _: Annotated[Principal, Depends(require(Permission.ROLES_MANAGE))],
) -> list[PermissionOut]:
    return [PermissionOut(name=p, dangerous=p in DANGEROUS_PERMISSIONS) for p in Permission]


@router.get("/roles", response_model=list[RoleOut])
async def list_roles(
    request: Request, p: Annotated[Principal, Depends(require(Permission.ROLES_MANAGE))]
) -> list[RoleOut]:
    async with workspace_tx(request.app.state.pool, p.workspace_id) as conn:
        cur = await conn.execute("SELECT id FROM roles ORDER BY name")
        return [await _role_out(conn, rid) for (rid,) in await cur.fetchall()]


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
async def create_role(
    body: RoleCreate,
    request: Request,
    p: Annotated[Principal, Depends(require(Permission.ROLES_MANAGE))],
) -> RoleOut:
    requested = frozenset(body.permissions)
    check_can_grant(p.permissions, requested)
    try:
        async with workspace_tx(request.app.state.pool, p.workspace_id) as conn:
            cur = await conn.execute(
                "INSERT INTO roles (workspace_id, name) VALUES (%s, %s) RETURNING id",
                (p.workspace_id, body.name),
            )
            role_id = returned(await cur.fetchone())[0]
            await _set_permissions(conn, p.workspace_id, role_id, body.permissions)
            await audit(
                conn,
                p,
                "role.create",
                "role",
                role_id,
                name=body.name,
                permissions=sorted(x.value for x in requested),
            )
            return await _role_out(conn, role_id)
    except psycopg.errors.UniqueViolation:
        raise HTTPException(status.HTTP_409_CONFLICT, "a role with that name exists") from None


@router.put("/roles/{role_id}", response_model=RoleOut)
async def update_role(
    role_id: uuid.UUID,
    body: RoleUpdate,
    request: Request,
    p: Annotated[Principal, Depends(require(Permission.ROLES_MANAGE))],
) -> RoleOut:
    try:
        async with workspace_tx(request.app.state.pool, p.workspace_id) as conn:
            before = await _locked_role(conn, role_id)
            check_can_edit_role(p.permissions, before)
            new_perms = before.permissions
            if body.permissions is not None:
                new_perms = frozenset(body.permissions)
                check_can_grant(p.permissions, new_perms)
                await _set_permissions(conn, p.workspace_id, role_id, body.permissions)
            if body.name is not None:
                await conn.execute("UPDATE roles SET name = %s WHERE id = %s", (body.name, role_id))
            await audit(
                conn,
                p,
                "role.update",
                "role",
                role_id,
                before=sorted(x.value for x in before.permissions),
                after=sorted(x.value for x in new_perms),
                name=body.name,
            )
            return await _role_out(conn, role_id)
    except psycopg.errors.UniqueViolation:
        raise HTTPException(status.HTTP_409_CONFLICT, "a role with that name exists") from None


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: uuid.UUID,
    request: Request,
    p: Annotated[Principal, Depends(require(Permission.ROLES_MANAGE))],
) -> None:
    try:
        async with workspace_tx(request.app.state.pool, p.workspace_id) as conn:
            role = await _locked_role(conn, role_id)
            check_can_edit_role(p.permissions, role)
            await conn.execute("DELETE FROM roles WHERE id = %s", (role_id,))
            await audit(conn, p, "role.delete", "role", role_id, name=role.name)
    except psycopg.errors.ForeignKeyViolation:
        raise HTTPException(status.HTTP_409_CONFLICT, "role still has members") from None


async def _locked_role(conn: AsyncConnection, role_id: uuid.UUID) -> RoleView:
    cur = await conn.execute(
        "SELECT id, name, is_locked FROM roles WHERE id = %s FOR UPDATE", (role_id,)
    )
    row = await cur.fetchone()
    if row is None:
        raise not_found()
    cur = await conn.execute(
        "SELECT permission FROM role_permissions WHERE role_id = %s", (role_id,)
    )
    perms = [r[0] for r in await cur.fetchall()]
    return _view(str(row[0]), row[1], row[2], perms)


# --- API keys -----------------------------------------------------------------------------


def _key_out(row: tuple[Any, ...]) -> ApiKeyOut:
    return ApiKeyOut(
        id=row[0],
        name=row[1],
        prefix=row[2],
        permissions=row[3],
        expires_at=row[4],
        revoked_at=row[5],
        created_at=row[6],
    )


@router.get("/api-keys", response_model=list[ApiKeyOut])
async def list_api_keys(
    request: Request, p: Annotated[Principal, Depends(require(Permission.API_KEYS_MANAGE))]
) -> list[ApiKeyOut]:
    async with workspace_tx(request.app.state.pool, p.workspace_id) as conn:
        cur = await conn.execute(
            "SELECT id, name, prefix, permissions, expires_at, revoked_at, created_at "
            "FROM api_keys ORDER BY created_at DESC"
        )
        return [_key_out(r) for r in await cur.fetchall()]


@router.post("/api-keys", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    body: ApiKeyCreate,
    request: Request,
    p: Annotated[Principal, Depends(require(Permission.API_KEYS_MANAGE))],
) -> ApiKeyCreated:
    granted = api_key_permissions(p.permissions, frozenset(body.permissions))
    key = generate_api_key()
    async with workspace_tx(request.app.state.pool, p.workspace_id) as conn:
        cur = await conn.execute(
            "INSERT INTO api_keys (workspace_id, name, prefix, key_hash, permissions, expires_at) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "RETURNING id, name, prefix, permissions, expires_at, revoked_at, created_at",
            (
                p.workspace_id,
                body.name,
                key.prefix,
                key.key_hash,
                sorted(x.value for x in granted),
                body.expires_at,
            ),
        )
        row = returned(await cur.fetchone())
        await audit(
            conn,
            p,
            "api_key.create",
            "api_key",
            row[0],
            name=body.name,
            permissions=sorted(x.value for x in granted),
        )
    return ApiKeyCreated(**_key_out(row).model_dump(), token=key.token)


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: uuid.UUID,
    request: Request,
    p: Annotated[Principal, Depends(require(Permission.API_KEYS_MANAGE))],
) -> None:
    async with workspace_tx(request.app.state.pool, p.workspace_id) as conn:
        cur = await conn.execute(
            "UPDATE api_keys SET revoked_at = coalesce(revoked_at, now()) WHERE id = %s "
            "RETURNING id",
            (key_id,),
        )
        if await cur.fetchone() is None:
            raise not_found()
        await audit(conn, p, "api_key.revoke", "api_key", key_id)
