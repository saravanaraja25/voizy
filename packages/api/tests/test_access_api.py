from __future__ import annotations

import uuid

import httpx
import psycopg
import pytest
from voizy_api.testing import MakeKey, bearer
from voizy_core.bootstrap import BootstrapResult
from voizy_core.permissions import ALL_PERMISSIONS, Permission

pytestmark = pytest.mark.asyncio
P = Permission
WS = tuple[uuid.UUID, uuid.UUID]


async def role_id(client: httpx.AsyncClient, h: dict[str, str], name: str) -> str:
    roles = (await client.get("/v1/roles", headers=h)).json()
    return str(next(r["id"] for r in roles if r["name"] == name))


async def test_catalog_flags_dangerous_permissions(
    client: httpx.AsyncClient, workspace_a: BootstrapResult
) -> None:
    h = bearer(workspace_a.token)
    cat = {
        c["name"]: c["dangerous"] for c in (await client.get("/v1/permissions", headers=h)).json()
    }
    assert set(cat) == {p.value for p in P}
    assert cat["provider_keys:manage"] is True and cat["agents:read"] is False


async def test_superadmin_creates_updates_and_deletes_custom_role_with_audit(
    client: httpx.AsyncClient, workspace_a: BootstrapResult, admin: psycopg.Connection
) -> None:
    h = bearer(workspace_a.token)
    r = await client.post(
        "/v1/roles",
        json={"name": "Support", "permissions": ["calls:read", "agents:read"]},
        headers=h,
    )
    assert r.status_code == 201 and r.json()["permissions"] == ["agents:read", "calls:read"]
    rid = r.json()["id"]
    r = await client.put(f"/v1/roles/{rid}", json={"permissions": ["calls:read"]}, headers=h)
    assert r.json()["permissions"] == ["calls:read"]
    assert (await client.delete(f"/v1/roles/{rid}", headers=h)).status_code == 204
    actions = [a for (a,) in admin.execute("SELECT action FROM audit_log ORDER BY id").fetchall()]
    assert actions[-3:] == ["role.create", "role.update", "role.delete"]


async def test_cannot_grant_permissions_you_do_not_hold(
    client: httpx.AsyncClient, workspace_a: BootstrapResult, make_key: MakeKey
) -> None:
    key = bearer(make_key(workspace_a.workspace_id, frozenset({P.ROLES_MANAGE, P.AGENTS_READ})))
    r = await client.post(
        "/v1/roles",
        json={"name": "Sneaky", "permissions": ["agents:read", "provider_keys:manage"]},
        headers=key,
    )
    assert r.status_code == 403 and "provider_keys:manage" in r.json()["detail"]
    # ...and nothing was created.
    names = [x["name"] for x in (await client.get("/v1/roles", headers=key)).json()]
    assert "Sneaky" not in names


async def test_locked_superadmin_role_cannot_be_edited_or_deleted_even_by_superadmin(
    client: httpx.AsyncClient, workspace_a: BootstrapResult
) -> None:
    h = bearer(workspace_a.token)
    rid = await role_id(client, h, "Superadmin")
    assert (
        await client.put(f"/v1/roles/{rid}", json={"permissions": []}, headers=h)
    ).status_code == 403
    assert (await client.put(f"/v1/roles/{rid}", json={"name": "x"}, headers=h)).status_code == 403
    assert (await client.delete(f"/v1/roles/{rid}", headers=h)).status_code == 403


async def test_cannot_edit_role_that_outranks_you(
    client: httpx.AsyncClient, workspace_a: BootstrapResult, make_key: MakeKey
) -> None:
    admin_rid = await role_id(client, bearer(workspace_a.token), "Admin")
    weak = bearer(make_key(workspace_a.workspace_id, frozenset({P.ROLES_MANAGE, P.AGENTS_READ})))
    r = await client.put(
        f"/v1/roles/{admin_rid}", json={"permissions": ["agents:read"]}, headers=weak
    )
    assert r.status_code == 403 and "outranks" in r.json()["detail"]


async def test_role_validation_and_duplicates(
    client: httpx.AsyncClient, workspace_a: BootstrapResult
) -> None:
    h = bearer(workspace_a.token)
    bad = await client.post(
        "/v1/roles", json={"name": "X", "permissions": ["agents:everything"]}, headers=h
    )
    assert bad.status_code == 422
    dup = await client.post("/v1/roles", json={"name": "Builder", "permissions": []}, headers=h)
    assert dup.status_code == 409


async def test_roles_are_tenant_isolated(
    client: httpx.AsyncClient, workspace_a: BootstrapResult, two_workspaces: WS, make_key: MakeKey
) -> None:
    other = bearer(make_key(two_workspaces[1]))
    rid = await role_id(client, bearer(workspace_a.token), "Builder")
    assert (await client.get("/v1/roles", headers=other)).json() == []
    assert (
        await client.put(f"/v1/roles/{rid}", json={"name": "pwn"}, headers=other)
    ).status_code == 404
    assert (await client.delete(f"/v1/roles/{rid}", headers=other)).status_code == 404


async def test_api_key_lifecycle_token_shown_once_and_revocation_works(
    client: httpx.AsyncClient, workspace_a: BootstrapResult
) -> None:
    h = bearer(workspace_a.token)
    r = await client.post(
        "/v1/api-keys", json={"name": "ci", "permissions": ["agents:read"]}, headers=h
    )
    assert r.status_code == 201
    created = r.json()
    assert created["token"].startswith("vz_") and created["token"].startswith(created["prefix"])
    listed = (await client.get("/v1/api-keys", headers=h)).json()
    assert all("token" not in k and "key_hash" not in k for k in listed)

    assert (await client.get("/v1/agents", headers=bearer(created["token"]))).status_code == 200
    assert (await client.delete(f"/v1/api-keys/{created['id']}", headers=h)).status_code == 204
    assert (await client.get("/v1/agents", headers=bearer(created["token"]))).status_code == 401


async def test_api_key_cannot_exceed_creator_and_validates_expiry(
    client: httpx.AsyncClient, workspace_a: BootstrapResult, make_key: MakeKey
) -> None:
    mid = bearer(make_key(workspace_a.workspace_id, frozenset({P.API_KEYS_MANAGE, P.AGENTS_READ})))
    r = await client.post(
        "/v1/api-keys", json={"name": "x", "permissions": ["calls:delete"]}, headers=mid
    )
    assert r.status_code == 403
    past = {"name": "x", "permissions": ["agents:read"], "expires_at": "2020-01-01T00:00:00Z"}
    assert (await client.post("/v1/api-keys", json=past, headers=mid)).status_code == 422
    naive = {"name": "x", "permissions": ["agents:read"], "expires_at": "2999-01-01T00:00:00"}
    assert (await client.post("/v1/api-keys", json=naive, headers=mid)).status_code == 422
    assert ALL_PERMISSIONS > {P.API_KEYS_MANAGE}


async def test_api_key_endpoints_require_permission_and_are_isolated(
    client: httpx.AsyncClient, workspace_a: BootstrapResult, two_workspaces: WS, make_key: MakeKey
) -> None:
    reader = bearer(make_key(workspace_a.workspace_id, frozenset({P.AGENTS_READ})))
    assert (await client.get("/v1/api-keys", headers=reader)).status_code == 403
    victim = (await client.get("/v1/api-keys", headers=bearer(workspace_a.token))).json()[0]["id"]
    other = bearer(make_key(two_workspaces[1]))
    assert (await client.delete(f"/v1/api-keys/{victim}", headers=other)).status_code == 404
