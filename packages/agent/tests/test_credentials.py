from __future__ import annotations

import uuid

import psycopg
import pytest
from voizy_agent.credentials import (
    DbSecretResolver,
    LiveKitCredentials,
    load_livekit,
    primary_workspace_livekit,
    secret_box_from_env,
)
from voizy_core.db.pool import open_pool
from voizy_core.security.secretbox import SecretBox
from voizy_core.services import secrets_store as store

pytestmark = pytest.mark.asyncio
WS = tuple[uuid.UUID, uuid.UUID]


def box() -> SecretBox:
    return SecretBox.from_env_value(f"k1:{SecretBox.generate_key()}")


async def seed_livekit(admin_dsn: str, b: SecretBox, ws: uuid.UUID) -> None:
    pool = await open_pool(admin_dsn)
    try:
        async with pool.connection() as conn:
            for name, value in (
                ("livekit_url", "wss://p.livekit.cloud"),
                ("livekit_api_key", "APIabc123def"),
                ("livekit_api_secret", "s" * 32),
            ):
                await store.put_secret(conn, b, ws, name, value, kind="integration")
    finally:
        await pool.close()


async def test_loads_livekit_only_when_all_three_fields_are_present(
    admin_dsn: str, admin: psycopg.Connection, two_workspaces: WS
) -> None:
    a, _ = two_workspaces
    b = box()
    pool = await open_pool(admin_dsn)
    try:
        async with pool.connection() as conn:
            await store.put_secret(
                conn, b, a, "livekit_url", "wss://p.livekit.cloud", kind="integration"
            )
        assert await load_livekit(pool, b, a) is None  # incomplete
    finally:
        await pool.close()
    await seed_livekit(admin_dsn, b, a)
    pool = await open_pool(admin_dsn)
    try:
        creds = await load_livekit(pool, b, a)
        assert creds == LiveKitCredentials("wss://p.livekit.cloud", "APIabc123def", "s" * 32)
        assert "s" * 32 not in repr(creds)  # the secret never prints
    finally:
        await pool.close()


async def test_primary_workspace_owns_the_workers_connection(
    admin_dsn: str, admin: psycopg.Connection, two_workspaces: WS
) -> None:
    a, b_ws = two_workspaces
    b = box()
    await seed_livekit(admin_dsn, b, a)
    pool = await open_pool(admin_dsn)
    try:
        assert await primary_workspace_livekit(pool, b) is None  # no primary recorded yet
        admin.execute("UPDATE instance_settings SET primary_workspace_id = %s", (b_ws,))
        assert await primary_workspace_livekit(pool, b) is None  # primary has no LiveKit
    finally:
        await pool.close()
    admin.execute("ALTER TABLE instance_settings DISABLE TRIGGER USER")
    admin.execute("UPDATE instance_settings SET primary_workspace_id = %s", (a,))
    admin.execute("ALTER TABLE instance_settings ENABLE TRIGGER USER")
    pool = await open_pool(admin_dsn)
    try:
        found = await primary_workspace_livekit(pool, b)
        assert found is not None and found[0] == a and found[1].url == "wss://p.livekit.cloud"
    finally:
        await pool.close()


async def test_the_tool_resolver_cannot_reach_integration_keys(
    admin_dsn: str, two_workspaces: WS
) -> None:
    a, _ = two_workspaces
    b = box()
    await seed_livekit(admin_dsn, b, a)
    pool = await open_pool(admin_dsn)
    try:
        async with pool.connection() as conn:
            await store.put_secret(
                conn,
                b,
                a,
                "clinic_key",
                "k" * 20,
                kind="tool",
                allowed_hosts=["api.clinic.example"],
            )
        resolve = DbSecretResolver(pool, b, a)
        got = await resolve("clinic_key")
        assert (
            got is not None
            and got.value == "k" * 20
            and got.allowed_hosts == ("api.clinic.example",)
        )
        assert (
            await resolve("livekit_api_secret") is None
        )  # an integration key is not a tool secret
        assert await resolve("missing") is None
    finally:
        await pool.close()


def test_secret_box_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VOIZY_SECRET_KEYS", raising=False)
    assert secret_box_from_env() is None
    monkeypatch.setenv("VOIZY_SECRET_KEYS", "not-a-keyring")
    assert secret_box_from_env() is None  # malformed: treated as not configured, never a crash
    monkeypatch.setenv("VOIZY_SECRET_KEYS", f"k1:{SecretBox.generate_key()}")
    assert secret_box_from_env() is not None
