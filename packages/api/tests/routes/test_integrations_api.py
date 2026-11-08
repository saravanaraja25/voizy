"""Integration keys and tool credentials: encrypted, write-only, permission-gated."""

from __future__ import annotations

import json

import httpx
import jwt
import psycopg
import pytest
from psycopg_pool import AsyncConnectionPool
from voizy_api.app import create_app
from voizy_api.settings import Settings
from voizy_api.testing import FakeChecker, MakeKey, agent_body, bearer
from voizy_core.domain.permissions import Permission
from voizy_core.services.bootstrap import BootstrapResult

LK = {
    "livekit_url": "wss://proj-abc.livekit.cloud",
    "livekit_api_key": "APIkeyForTests1",
    "livekit_api_secret": "sekret-value-for-livekit-tests-0001",
}
SECRET_BITS = ("APIkeyForTests1", "sekret-value-for-livekit-tests-0001")


def dump(*responses: httpx.Response) -> str:
    return " ".join(r.text for r in responses)


async def test_everything_is_unavailable_without_an_encryption_key(
    pool: AsyncConnectionPool, workspace_a: BootstrapResult
) -> None:
    app = create_app(pool, settings=Settings(cookie_secure=False, custom_roles=True))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        h = bearer(workspace_a.token)
        for method, path in (("GET", "/v1/integrations"), ("GET", "/v1/secrets")):
            r = await c.request(method, path, headers=h)
            assert r.status_code == 503 and "VOIZY_SECRET_KEYS" in r.json()["detail"]
        r = await c.put("/v1/integrations/livekit", headers=h, json={"values": LK})
        assert r.status_code == 503


async def test_lists_every_integration_as_unconfigured(
    client: httpx.AsyncClient, workspace_a: BootstrapResult
) -> None:
    r = await client.get("/v1/integrations", headers=bearer(workspace_a.token))
    rows = {i["id"]: i for i in r.json()}
    assert set(rows) == {"livekit", "twilio", "openai", "google", "deepgram", "cartesia"}
    assert not any(i["configured"] for i in rows.values())
    assert [f["name"] for f in rows["livekit"]["fields"]] == list(LK)
    assert (
        rows["livekit"]["fields"][0]["secret"] is False and rows["livekit"]["fields"][1]["secret"]
    )


async def test_saving_is_write_only_and_encrypted_at_rest(
    client: httpx.AsyncClient, workspace_a: BootstrapResult, admin: psycopg.Connection
) -> None:
    h = bearer(workspace_a.token)
    put = await client.put("/v1/integrations/livekit", headers=h, json={"values": LK})
    got = await client.get("/v1/integrations", headers=h)
    assert put.status_code == 200 and put.json()["configured"] is True
    body = dump(put, got)
    assert not any(bit in body for bit in SECRET_BITS)  # no secret is ever returned
    fields = {f["name"]: f for f in put.json()["fields"]}
    assert fields["livekit_url"]["value"] == LK["livekit_url"]  # a URL is not sensitive
    assert (
        fields["livekit_api_key"]["value"] is None
        and fields["livekit_api_key"]["hint"] == "••••sts1"
    )
    assert fields["livekit_api_secret"]["hint"] == "••••0001"

    rows = admin.execute("SELECT name, ciphertext FROM secrets WHERE kind='integration'").fetchall()
    assert len(rows) == 3 and not any(bit in ct for _, ct in rows for bit in SECRET_BITS)
    assert all(ct.startswith("v1:k1:") for _, ct in rows)


async def test_blank_values_keep_what_is_stored_and_partial_saves_are_incomplete(
    client: httpx.AsyncClient, workspace_a: BootstrapResult
) -> None:
    h = bearer(workspace_a.token)
    first = await client.put(
        "/v1/integrations/livekit", headers=h, json={"values": {"livekit_url": LK["livekit_url"]}}
    )
    assert first.json()["configured"] is False
    done = await client.put("/v1/integrations/livekit", headers=h, json={"values": LK})
    assert done.json()["configured"] is True
    changed = await client.put(
        "/v1/integrations/livekit",
        headers=h,
        json={
            "values": {
                "livekit_url": "wss://other.livekit.cloud",
                "livekit_api_key": "  ",
                "livekit_api_secret": "",
            }
        },
    )
    fields = {f["name"]: f for f in changed.json()["fields"]}
    assert fields["livekit_url"]["value"] == "wss://other.livekit.cloud"
    assert changed.json()["configured"] is True and fields["livekit_api_key"]["hint"] == "••••sts1"


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"livekit_url": "https://proj.livekit.cloud"}, "Project URL"),
        ({"livekit_api_key": "x"}, "API key"),
        ({"not_a_field": "x"}, "Unknown field"),
        ({}, "Nothing to save"),
        ({"livekit_api_key": "bad\nvalue123456"}, "API key"),
    ],
)
async def test_invalid_input_is_rejected_without_echoing_the_value(
    client: httpx.AsyncClient, workspace_a: BootstrapResult, values: dict[str, str], message: str
) -> None:
    r = await client.put(
        "/v1/integrations/livekit", headers=bearer(workspace_a.token), json={"values": values}
    )
    assert r.status_code == 422 and message in r.json()["detail"]
    assert "bad" not in r.json()["detail"].lower().replace("bad\n", "")


async def test_unknown_integration_is_404_and_delete_clears_it(
    client: httpx.AsyncClient, workspace_a: BootstrapResult
) -> None:
    h = bearer(workspace_a.token)
    assert (
        await client.put("/v1/integrations/nope", headers=h, json={"values": {"a": "b"}})
    ).status_code == 404
    await client.put("/v1/integrations/livekit", headers=h, json={"values": LK})
    assert (await client.delete("/v1/integrations/livekit", headers=h)).status_code == 204
    rows = {i["id"]: i for i in (await client.get("/v1/integrations", headers=h)).json()}
    assert rows["livekit"]["configured"] is False
    assert (
        await client.delete("/v1/integrations/livekit", headers=h)
    ).status_code == 204  # idempotent


async def test_test_connection_uses_the_stored_values_and_reports_plainly(
    client: httpx.AsyncClient,
    workspace_a: BootstrapResult,
    app_settings: Settings,
    admin: psycopg.Connection,
) -> None:
    h = bearer(workspace_a.token)
    checker = app_settings.integration_checker
    assert isinstance(checker, FakeChecker)
    incomplete = await client.post("/v1/integrations/livekit/test", headers=h)
    assert incomplete.status_code == 422 and "every field" in incomplete.json()["detail"]

    await client.put("/v1/integrations/livekit", headers=h, json={"values": LK})
    ok = await client.post("/v1/integrations/livekit/test", headers=h)
    assert ok.json() == {"ok": True, "message": "Connected."}
    assert checker.calls == [("livekit", LK)]  # decrypted server-side, handed to the checker
    assert not any(bit in ok.text for bit in SECRET_BITS)

    checker.ok = False
    bad = await client.post("/v1/integrations/livekit/test", headers=h)
    assert bad.json()["ok"] is False
    audits = admin.execute(
        "SELECT detail FROM audit_log WHERE action = 'integration.test' ORDER BY id"
    ).fetchall()
    assert [a[0]["ok"] for a in audits] == [True, False]


async def test_every_endpoint_needs_the_provider_keys_permission(
    client: httpx.AsyncClient, workspace_a: BootstrapResult, make_key: MakeKey
) -> None:
    weak = bearer(make_key(workspace_a.workspace_id, frozenset({Permission.AGENTS_READ})))
    calls = [
        ("GET", "/v1/integrations", None),
        ("PUT", "/v1/integrations/livekit", {"values": LK}),
        ("DELETE", "/v1/integrations/livekit", None),
        ("POST", "/v1/integrations/livekit/test", None),
        ("GET", "/v1/secrets", None),
        ("PUT", "/v1/secrets/k", {"value": "v" * 12, "allowed_hosts": ["a.example.com"]}),
        ("DELETE", "/v1/secrets/k", None),
    ]
    for method, path, body in calls:
        r = await client.request(method, path, headers=weak, json=body)
        assert r.status_code == 403, (method, path)
    assert (await client.get("/v1/integrations")).status_code == 401


async def test_workspaces_cannot_see_each_others_keys(
    client: httpx.AsyncClient,
    workspace_a: BootstrapResult,
    two_workspaces: tuple[object, object],
    make_key: MakeKey,
) -> None:
    await client.put(
        "/v1/integrations/livekit", headers=bearer(workspace_a.token), json={"values": LK}
    )
    other = bearer(make_key(two_workspaces[1]))
    rows = {i["id"]: i for i in (await client.get("/v1/integrations", headers=other)).json()}
    assert rows["livekit"]["configured"] is False
    assert dump(await client.get("/v1/secrets", headers=other)) == "[]"


async def test_tool_secrets_are_write_only_and_pinned_to_hosts(
    client: httpx.AsyncClient, workspace_a: BootstrapResult, admin: psycopg.Connection
) -> None:
    h = bearer(workspace_a.token)
    value = "clinic-live-key-0123456789"
    put = await client.put(
        "/v1/secrets/clinic_api_key",
        headers=h,
        json={
            "value": value,
            "allowed_hosts": ["API.Clinic.example", "*.clinic.example"],
            "description": "Clinic",
        },
    )
    assert put.status_code == 200
    assert put.json()["allowed_hosts"] == ["api.clinic.example", "*.clinic.example"]
    listing = await client.get("/v1/secrets", headers=h)
    assert value not in dump(put, listing) and listing.json()[0]["hint"] == "••••6789"
    assert value not in admin.execute("SELECT ciphertext FROM secrets").fetchone()[0]  # type: ignore[index]

    moved = await client.put(  # change only where it may go; the value is untouched
        "/v1/secrets/clinic_api_key", headers=h, json={"allowed_hosts": ["only.clinic.example"]}
    )
    assert (
        moved.json()["allowed_hosts"] == ["only.clinic.example"]
        and moved.json()["hint"] == "••••6789"
    )
    assert (
        await client.put(
            "/v1/secrets/missing", headers=h, json={"allowed_hosts": ["a.example.com"]}
        )
    ).status_code == 404

    audits = admin.execute("SELECT detail FROM audit_log WHERE target_type = 'secret'").fetchall()
    assert len(audits) == 2 and value not in json.dumps([a[0] for a in audits])
    assert (await client.delete("/v1/secrets/clinic_api_key", headers=h)).status_code == 204
    assert (await client.delete("/v1/secrets/clinic_api_key", headers=h)).status_code == 404


@pytest.mark.parametrize(
    ("name", "body", "message"),
    [
        ("Bad Name", {"value": "v" * 12, "allowed_hosts": ["a.example.com"]}, "Names use"),
        ("openai_api_key", {"value": "v" * 12, "allowed_hosts": ["a.example.com"]}, "reserved"),
        ("k", {"value": "v" * 12, "allowed_hosts": []}, "at least one host"),
        ("k", {"value": "v" * 12, "allowed_hosts": ["10.0.0.1"]}, "valid host"),
        ("k", {"value": "v" * 12, "allowed_hosts": ["http://x.example.com"]}, "valid host"),
        ("k", {"value": "line\nbreak", "allowed_hosts": ["a.example.com"]}, "control characters"),
        ("k", {"value": "", "allowed_hosts": ["a.example.com"]}, "value"),
    ],
)
async def test_tool_secret_validation(
    client: httpx.AsyncClient,
    workspace_a: BootstrapResult,
    name: str,
    body: dict[str, object],
    message: str,
) -> None:
    r = await client.put(f"/v1/secrets/{name}", headers=bearer(workspace_a.token), json=body)
    assert r.status_code == 422 and message.lower() in str(r.json()["detail"]).lower()


async def test_test_sessions_use_the_workspaces_stored_livekit_connection(
    pool: AsyncConnectionPool, workspace_a: BootstrapResult, app_settings: Settings
) -> None:
    from voizy_api.livekit import LiveKitSettings

    env_settings = LiveKitSettings("wss://env.example.livekit.cloud", "ENVkey123", "e" * 40)
    app = create_app(pool, livekit=env_settings, settings=app_settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        h = bearer(workspace_a.token)
        agent = (await c.post("/v1/agents", json=agent_body(), headers=h)).json()["id"]
        before = (await c.post(f"/v1/agents/{agent}/versions/1/test-session", headers=h)).json()
        assert before["url"] == env_settings.url  # no stored connection yet: the environment's

        await c.put("/v1/integrations/livekit", headers=h, json={"values": LK})
        after = (await c.post(f"/v1/agents/{agent}/versions/1/test-session", headers=h)).json()
        assert after["url"] == LK["livekit_url"]
        claims = jwt.decode(
            after["token"],
            LK["livekit_api_secret"],
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
        assert claims["iss"] == LK["livekit_api_key"]  # signed with the workspace's own key


async def test_own_key_choice_needs_a_stored_key_and_a_supported_provider(
    client: httpx.AsyncClient, workspace_a: BootstrapResult
) -> None:
    h = bearer(workspace_a.token)
    body = agent_body("Direct")
    cfg = body["config"]
    assert isinstance(cfg, dict)
    cfg["llm"] = {"provider": "openai", "model": "gpt-4o-mini", "connection": "own"}

    r = await client.post("/v1/agents", headers=h, json=body)
    assert r.status_code == 422 and "OpenAI" in r.json()["detail"]

    ok = await client.put(
        "/v1/integrations/openai", headers=h, json={"values": {"openai_api_key": "sk-" + "x" * 30}}
    )
    assert ok.status_code == 200
    created = await client.post("/v1/agents", headers=h, json=body)
    assert created.status_code == 201

    cfg["llm"] = {"provider": "assemblyai", "model": "x", "connection": "own"}
    r = await client.post(
        f"/v1/agents/{created.json()['id']}/versions", headers=h, json={"config": cfg}
    )
    assert r.status_code == 422 and "can't be used with your own key" in r.json()["detail"]
