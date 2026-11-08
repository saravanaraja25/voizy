from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator

import httpx
import jwt
import psycopg
import pytest
import pytest_asyncio
from psycopg_pool import AsyncConnectionPool
from voizy_api.app import create_app
from voizy_api.livekit import LiveKitSettings
from voizy_api.testing import MakeKey, agent_body, bearer
from voizy_core.domain.dispatch import AGENT_WORKER_NAME, parse_dispatch
from voizy_core.domain.permissions import Permission
from voizy_core.services.bootstrap import BootstrapResult

SETTINGS = LiveKitSettings("wss://example.livekit.cloud", "APIkey123", "s" * 40)
WS = tuple[uuid.UUID, uuid.UUID]


@pytest_asyncio.fixture
async def lk_client(pool: AsyncConnectionPool) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(pool, livekit=SETTINGS)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def make_agent(client: httpx.AsyncClient, h: dict[str, str]) -> str:
    r = await client.post("/v1/agents", json=agent_body(), headers=h)
    return str(r.json()["id"])


async def test_me_returns_workspace_and_sorted_permissions(
    lk_client: httpx.AsyncClient, workspace_a: BootstrapResult
) -> None:
    r = await lk_client.get("/v1/me", headers=bearer(workspace_a.token))
    body = r.json()
    assert r.status_code == 200 and body["workspace_name"] == "A"
    assert body["workspace_id"] == str(workspace_a.workspace_id)
    assert (
        body["permissions"] == sorted(body["permissions"]) and "agents:test" in body["permissions"]
    )
    assert (await lk_client.get("/v1/me")).status_code == 401


async def test_version_listing_newest_first_and_tenant_isolated(
    lk_client: httpx.AsyncClient,
    workspace_a: BootstrapResult,
    two_workspaces: WS,
    make_key: MakeKey,
) -> None:
    h = bearer(workspace_a.token)
    agent = await make_agent(lk_client, h)
    await lk_client.post(
        f"/v1/agents/{agent}/versions", json={"config": agent_body()["config"]}, headers=h
    )
    await lk_client.post(f"/v1/agents/{agent}/versions/1/publish", headers=h)
    rows = (await lk_client.get(f"/v1/agents/{agent}/versions", headers=h)).json()
    assert [(r["version"], r["is_published"]) for r in rows] == [(2, False), (1, True)]
    other = bearer(make_key(two_workspaces[1]))
    assert (await lk_client.get(f"/v1/agents/{agent}/versions", headers=other)).status_code == 404


async def test_test_session_token_claims(
    lk_client: httpx.AsyncClient, workspace_a: BootstrapResult, admin: psycopg.Connection
) -> None:
    h = bearer(workspace_a.token)
    agent = await make_agent(lk_client, h)
    r = await lk_client.post(f"/v1/agents/{agent}/versions/1/test-session", headers=h)
    assert r.status_code == 201
    s = r.json()
    assert s["url"] == SETTINGS.url and s["expires_in_s"] == 600
    assert SETTINGS.api_secret not in r.text

    claims = jwt.decode(
        s["token"], SETTINGS.api_secret, algorithms=["HS256"], options={"verify_aud": False}
    )
    assert claims["iss"] == SETTINGS.api_key and claims["sub"] == s["identity"]
    assert 0 < claims["exp"] - time.time() <= 600
    assert claims["video"]["room"] == s["room"] and claims["video"]["roomJoin"] is True
    (dispatch,) = claims["roomConfig"]["agents"]
    assert dispatch["agentName"] == AGENT_WORKER_NAME
    target = parse_dispatch(dispatch["metadata"])
    assert target is not None and str(target.agent_id) == agent and target.version == 1
    assert target.workspace_id == workspace_a.workspace_id
    assert json.loads(dispatch["metadata"]).keys() == {"workspace_id", "agent_id", "version"}
    assert admin.execute("SELECT action FROM audit_log ORDER BY id DESC LIMIT 1").fetchone() == (
        "agent.test_session",
    )


async def test_each_test_session_gets_a_fresh_room_and_identity(
    lk_client: httpx.AsyncClient, workspace_a: BootstrapResult
) -> None:
    h = bearer(workspace_a.token)
    agent = await make_agent(lk_client, h)
    a = (await lk_client.post(f"/v1/agents/{agent}/versions/1/test-session", headers=h)).json()
    b = (await lk_client.post(f"/v1/agents/{agent}/versions/1/test-session", headers=h)).json()
    assert a["room"] != b["room"] and a["identity"] != b["identity"]


async def test_test_session_requires_permission_and_existing_version(
    lk_client: httpx.AsyncClient, workspace_a: BootstrapResult, make_key: MakeKey
) -> None:
    h = bearer(workspace_a.token)
    agent = await make_agent(lk_client, h)
    reader = bearer(make_key(workspace_a.workspace_id, frozenset({Permission.AGENTS_READ})))
    assert (
        await lk_client.post(f"/v1/agents/{agent}/versions/1/test-session", headers=reader)
    ).status_code == 403
    assert (
        await lk_client.post(f"/v1/agents/{agent}/versions/9/test-session", headers=h)
    ).status_code == 404
    assert (
        await lk_client.post(f"/v1/agents/{uuid.uuid4()}/versions/1/test-session", headers=h)
    ).status_code == 404


async def test_test_session_cannot_target_another_workspaces_agent(
    lk_client: httpx.AsyncClient,
    workspace_a: BootstrapResult,
    two_workspaces: WS,
    make_key: MakeKey,
) -> None:
    agent = await make_agent(lk_client, bearer(workspace_a.token))
    other = bearer(make_key(two_workspaces[1]))
    r = await lk_client.post(f"/v1/agents/{agent}/versions/1/test-session", headers=other)
    assert r.status_code == 404 and "token" not in r.text


async def test_archived_agent_has_no_test_session(
    lk_client: httpx.AsyncClient, workspace_a: BootstrapResult, admin: psycopg.Connection
) -> None:
    h = bearer(workspace_a.token)
    agent = await make_agent(lk_client, h)
    admin.execute("UPDATE agents SET archived_at = now() WHERE id = %s", (agent,))
    assert (
        await lk_client.post(f"/v1/agents/{agent}/versions/1/test-session", headers=h)
    ).status_code == 404


async def test_unconfigured_runtime_is_503(
    pool: AsyncConnectionPool, workspace_a: BootstrapResult, monkeypatch: pytest.MonkeyPatch
) -> None:
    for var in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        monkeypatch.delenv(var, raising=False)
    app = create_app(pool)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        h = bearer(workspace_a.token)
        agent = await make_agent(c, h)
        r = await c.post(f"/v1/agents/{agent}/versions/1/test-session", headers=h)
        assert r.status_code == 503


def test_settings_repr_hides_the_secret() -> None:
    assert SETTINGS.api_secret not in repr(SETTINGS) and "redacted" in repr(SETTINGS)


async def test_cors_allows_only_listed_origins_and_never_credentials(
    pool: AsyncConnectionPool,
) -> None:
    app = create_app(pool, livekit=SETTINGS, cors_origins=["http://localhost:5173"])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        ok = await c.options(
            "/v1/agents",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert ok.headers["access-control-allow-origin"] == "http://localhost:5173"
        assert "access-control-allow-credentials" not in ok.headers
        bad = await c.options(
            "/v1/agents",
            headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
        )
        assert "access-control-allow-origin" not in bad.headers


async def test_cors_is_off_by_default_and_wildcard_is_ignored(
    pool: AsyncConnectionPool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VOIZY_CORS_ORIGINS", "*")
    app = create_app(pool, livekit=SETTINGS)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.options(
            "/v1/agents",
            headers={"Origin": "http://anything.example", "Access-Control-Request-Method": "GET"},
        )
        assert "access-control-allow-origin" not in r.headers
