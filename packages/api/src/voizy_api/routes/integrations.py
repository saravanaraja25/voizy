"""Integration keys and tool credentials. Values are write-only: nothing here returns one."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from voizy_core.db.pool import workspace_tx
from voizy_core.domain.integrations import BY_ID, INTEGRATIONS, Integration
from voizy_core.domain.permissions import Permission
from voizy_core.security.secretbox import SecretBox
from voizy_core.services import secrets_store as store
from voizy_core.services.auth import Principal

from voizy_api.schemas.integrations import (
    FieldStatus,
    IntegrationOut,
    IntegrationUpdate,
    TestResultOut,
    ToolSecretOut,
    ToolSecretPut,
)
from voizy_api.web.auth import require
from voizy_api.web.common import audit

router = APIRouter(prefix="/v1", tags=["integrations"])
Admin = Annotated[Principal, Depends(require(Permission.PROVIDER_KEYS_MANAGE))]


def _box(request: Request) -> SecretBox:
    box = request.app.state.settings.secret_box
    if box is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Secret storage is not configured. Set VOIZY_SECRET_KEYS on the server "
            "(generate one with: voizy-admin generate-secret-key).",
        )
    return box  # type: ignore[no-any-return]


def _integration(integration_id: str) -> Integration:
    integration = BY_ID.get(integration_id)
    if integration is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    return integration


async def _describe(
    request: Request, p: Principal, integration: Integration, box: SecretBox
) -> IntegrationOut:
    pool = request.app.state.pool
    async with pool.connection() as conn:
        infos = {i.name: i for i in await store.list_secrets(conn, p.workspace_id, "integration")}
    async with pool.connection() as conn:
        shown = await store.get_integration_values(
            conn, box, p.workspace_id, [f.name for f in integration.fields if not f.secret]
        )
    fields = [
        FieldStatus(
            name=f.name,
            label=f.label,
            secret=f.secret,
            configured=f.name in infos,
            value=shown.get(f.name) if not f.secret else None,
            hint=infos[f.name].hint if f.name in infos and f.secret else "",
            placeholder=f.placeholder,
            help=f.help,
        )
        for f in integration.fields
    ]
    return IntegrationOut(
        id=integration.id,
        label=integration.label,
        description=integration.description,
        used_for=integration.used_for,
        configured=all(f.configured for f in fields),
        fields=fields,
    )


@router.get("/integrations", response_model=list[IntegrationOut])
async def list_integrations(request: Request, p: Admin) -> list[IntegrationOut]:
    box = _box(request)
    return [await _describe(request, p, i, box) for i in INTEGRATIONS]


@router.put("/integrations/{integration_id}", response_model=IntegrationOut)
async def update_integration(
    integration_id: str, body: IntegrationUpdate, request: Request, p: Admin
) -> IntegrationOut:
    box = _box(request)
    integration = _integration(integration_id)
    known = {f.name: f for f in integration.fields}
    unknown = set(body.values) - set(known)
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown field: {sorted(unknown)[0]}"
        )
    # Pasted values often arrive wrapped in quotes; those are never part of a key.
    given = {k: v.strip().strip("\"'").strip() for k, v in body.values.items() if v.strip()}
    for name, value in given.items():
        if not known[name].valid(value):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"{known[name].label} does not look right: it should be one line with no spaces. "
                "Copy it again, without quotes.",
            )
    if not given:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Nothing to save.")
    pool = request.app.state.pool
    for name, value in given.items():
        async with pool.connection() as conn:
            await store.put_secret(conn, box, p.workspace_id, name, value, kind="integration")
    async with workspace_tx(pool, p.workspace_id) as conn:
        await audit(
            conn, p, "integration.update", "integration", integration_id, fields=sorted(given)
        )
    return await _describe(request, p, integration, box)


@router.delete("/integrations/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_integration(integration_id: str, request: Request, p: Admin) -> None:
    _box(request)
    integration = _integration(integration_id)
    pool = request.app.state.pool
    async with pool.connection() as conn:
        await store.delete_secret(
            conn, p.workspace_id, [f.name for f in integration.fields], kind="integration"
        )
    async with workspace_tx(pool, p.workspace_id) as conn:
        await audit(conn, p, "integration.delete", "integration", integration_id)


@router.post("/integrations/{integration_id}/test", response_model=TestResultOut)
async def test_integration(integration_id: str, request: Request, p: Admin) -> TestResultOut:
    box = _box(request)
    integration = _integration(integration_id)
    names = [f.name for f in integration.fields]
    async with request.app.state.pool.connection() as conn:
        values = await store.get_integration_values(conn, box, p.workspace_id, names)
    if any(n not in values for n in names):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Fill in and save every field first."
        )
    checker = request.app.state.settings.integration_checker
    result = await checker(integration_id, values)
    async with workspace_tx(request.app.state.pool, p.workspace_id) as conn:
        await audit(conn, p, "integration.test", "integration", integration_id, ok=result.ok)
    return TestResultOut(ok=result.ok, message=result.message)


# ---- tool credentials ------------------------------------------------------------------------


def _tool_secret_error(exc: store.SecretStoreError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


@router.get("/secrets", response_model=list[ToolSecretOut])
async def list_tool_secrets(request: Request, p: Admin) -> list[ToolSecretOut]:
    _box(request)
    async with request.app.state.pool.connection() as conn:
        infos = await store.list_secrets(conn, p.workspace_id, "tool")
    return [
        ToolSecretOut(
            name=i.name,
            description=i.description,
            allowed_hosts=list(i.allowed_hosts),
            hint=i.hint,
            updated_at=i.updated_at,
        )
        for i in infos
    ]


@router.put("/secrets/{name}", response_model=ToolSecretOut)
async def put_tool_secret(
    name: str, body: ToolSecretPut, request: Request, p: Admin
) -> ToolSecretOut:
    box = _box(request)
    pool = request.app.state.pool
    try:
        if body.value is not None:
            async with pool.connection() as conn:
                await store.put_secret(
                    conn,
                    box,
                    p.workspace_id,
                    name,
                    body.value,
                    kind="tool",
                    allowed_hosts=body.allowed_hosts,
                    description=body.description,
                )
        else:
            async with pool.connection() as conn:
                found = await store.update_tool_secret_meta(
                    conn,
                    p.workspace_id,
                    name,
                    allowed_hosts=body.allowed_hosts,
                    description=body.description,
                )
            if not found:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    except store.SecretStoreError as exc:
        raise _tool_secret_error(exc) from exc
    async with workspace_tx(pool, p.workspace_id) as conn:
        await audit(
            conn,
            p,
            "secret.put",
            "secret",
            name,
            hosts=body.allowed_hosts,
            value_changed=body.value is not None,
        )
    async with pool.connection() as conn:
        infos = await store.list_secrets(conn, p.workspace_id, "tool")
    info = next(i for i in infos if i.name == name)
    return ToolSecretOut(
        name=info.name,
        description=info.description,
        allowed_hosts=list(info.allowed_hosts),
        hint=info.hint,
        updated_at=info.updated_at,
    )


@router.delete("/secrets/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tool_secret(name: str, request: Request, p: Admin) -> None:
    _box(request)
    pool = request.app.state.pool
    async with pool.connection() as conn:
        removed = await store.delete_secret(conn, p.workspace_id, [name], kind="tool")
    if removed == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    async with workspace_tx(pool, p.workspace_id) as conn:
        await audit(conn, p, "secret.delete", "secret", name)
