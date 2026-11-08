from __future__ import annotations

import asyncio
import uuid

import httpx
import psycopg
import pytest
from voizy_api.testing import MakeKey, agent_body, bearer
from voizy_core.permissions import Permission

pytestmark = pytest.mark.asyncio
WS = tuple[uuid.UUID, uuid.UUID]


async def test_missing_or_bad_credentials_get_401_with_challenge(
    client: httpx.AsyncClient, two_workspaces: WS
) -> None:
    for headers in ({}, bearer("garbage"), {"Authorization": "Basic abc"}):
        r = await client.get("/v1/agents", headers=headers)
        assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
        assert "garbage" not in r.text


async def test_missing_permission_gets_403(
    client: httpx.AsyncClient, two_workspaces: WS, make_key: MakeKey
) -> None:
    key = make_key(two_workspaces[0], frozenset({Permission.AGENTS_READ}))
    r = await client.post("/v1/agents", json=agent_body(), headers=bearer(key))
    assert r.status_code == 403


async def test_create_version_publish_flow_and_audit(
    client: httpx.AsyncClient, two_workspaces: WS, make_key: MakeKey, admin: psycopg.Connection
) -> None:
    h = bearer(make_key(two_workspaces[0]))
    r = await client.post("/v1/agents", json=agent_body(), headers=h)
    assert r.status_code == 201 and r.json()["published_version"] is None
    agent_id = r.json()["id"]

    r = await client.post(
        f"/v1/agents/{agent_id}/versions", json={"config": agent_body("v2")["config"]}, headers=h
    )
    assert r.status_code == 201 and r.json()["version"] == 2

    r = await client.post(f"/v1/agents/{agent_id}/versions/2/publish", headers=h)
    assert r.status_code == 200 and r.json()["published_version"] == 2

    r = await client.get(f"/v1/agents/{agent_id}/versions/1", headers=h)
    assert r.json()["is_published"] is False and r.json()["config"]["name"] == "Receptionist"
    actions = [a for (a,) in admin.execute("SELECT action FROM audit_log ORDER BY id").fetchall()]
    assert actions == ["agent.create", "agent.version.create", "agent.publish"]


async def test_invalid_config_and_unknown_fields_are_422(
    client: httpx.AsyncClient, two_workspaces: WS, make_key: MakeKey
) -> None:
    h = bearer(make_key(two_workspaces[0]))
    bad = agent_body()
    bad["config"]["system_prompt"] = "Hi {{undeclared}}"  # type: ignore[index]
    assert (await client.post("/v1/agents", json=bad, headers=h)).status_code == 422
    extra = {**agent_body(), "workspace_id": str(two_workspaces[1])}
    assert (await client.post("/v1/agents", json=extra, headers=h)).status_code == 422


async def test_other_workspace_cannot_see_edit_or_publish(
    client: httpx.AsyncClient, two_workspaces: WS, make_key: MakeKey
) -> None:
    ha = bearer(make_key(two_workspaces[0]))
    hb = bearer(make_key(two_workspaces[1]))
    agent_id = (await client.post("/v1/agents", json=agent_body(), headers=ha)).json()["id"]

    assert (await client.get("/v1/agents", headers=hb)).json() == []
    assert (await client.get(f"/v1/agents/{agent_id}", headers=hb)).status_code == 404
    r = await client.post(
        f"/v1/agents/{agent_id}/versions", json={"config": agent_body()["config"]}, headers=hb
    )
    assert r.status_code == 404
    assert (
        await client.post(f"/v1/agents/{agent_id}/versions/1/publish", headers=hb)
    ).status_code == 404
    assert (await client.get(f"/v1/agents/{agent_id}", headers=ha)).status_code == 200


async def test_archived_agent_rejects_new_versions_and_publish(
    client: httpx.AsyncClient, two_workspaces: WS, make_key: MakeKey, admin: psycopg.Connection
) -> None:
    h = bearer(make_key(two_workspaces[0]))
    agent_id = (await client.post("/v1/agents", json=agent_body(), headers=h)).json()["id"]
    admin.execute("UPDATE agents SET archived_at = now() WHERE id = %s", (agent_id,))
    r = await client.post(
        f"/v1/agents/{agent_id}/versions", json={"config": agent_body()["config"]}, headers=h
    )
    assert r.status_code == 409
    assert (
        await client.post(f"/v1/agents/{agent_id}/versions/1/publish", headers=h)
    ).status_code == 409


async def test_concurrent_version_creation_yields_distinct_numbers(
    client: httpx.AsyncClient, two_workspaces: WS, make_key: MakeKey
) -> None:
    h = bearer(make_key(two_workspaces[0]))
    agent_id = (await client.post("/v1/agents", json=agent_body(), headers=h)).json()["id"]
    body = {"config": agent_body()["config"]}
    rs = await asyncio.gather(
        *[client.post(f"/v1/agents/{agent_id}/versions", json=body, headers=h) for _ in range(6)]
    )
    assert all(r.status_code == 201 for r in rs)
    assert sorted(r.json()["version"] for r in rs) == [2, 3, 4, 5, 6, 7]


async def test_malformed_ids_and_docs_surface(
    client: httpx.AsyncClient, two_workspaces: WS, make_key: MakeKey
) -> None:
    h = bearer(make_key(two_workspaces[0]))
    assert (await client.get("/v1/agents/not-a-uuid", headers=h)).status_code == 422
    assert (await client.get("/docs")).status_code == 404
    assert (await client.get("/healthz")).json() == {"status": "ok"}
