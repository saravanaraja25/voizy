from __future__ import annotations

import uuid

import psycopg
import pytest
from voizy_agent import startup
from voizy_core.db.pool import open_pool
from voizy_core.security.secretbox import SecretBox
from voizy_core.services import secrets_store as store

pytestmark = pytest.mark.asyncio


async def no_sleep(_: float) -> None:
    return None


def test_environment_detection_treats_empty_values_as_unset() -> None:
    full = {"LIVEKIT_URL": "wss://a", "LIVEKIT_API_KEY": "k", "LIVEKIT_API_SECRET": "s"}
    assert startup.environment_has_livekit(full)
    assert not startup.environment_has_livekit({**full, "LIVEKIT_API_SECRET": ""})
    assert not startup.environment_has_livekit({})


async def test_environment_credentials_win_and_nothing_is_looked_up() -> None:
    env = {"LIVEKIT_URL": "wss://a", "LIVEKIT_API_KEY": "k", "LIVEKIT_API_SECRET": "s"}
    assert await startup.adopt_stored_livekit(env, max_attempts=1, sleep=no_sleep) is None
    assert env["LIVEKIT_URL"] == "wss://a"  # untouched, and no database was needed


async def test_empty_compose_passthrough_values_are_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VOIZY_SECRET_KEYS", raising=False)
    env = {"LIVEKIT_URL": "", "LIVEKIT_API_KEY": "", "LIVEKIT_API_SECRET": ""}
    with pytest.raises(startup.StartupError, match="No LiveKit connection"):
        await startup.adopt_stored_livekit(env, max_attempts=1, sleep=no_sleep)
    assert env == {}  # empty strings must not reach the SDK


async def test_missing_database_or_key_fails_loudly_instead_of_waiting_forever(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VOIZY_SECRET_KEYS", f"k1:{SecretBox.generate_key()}")
    with pytest.raises(startup.StartupError, match="VOIZY_DATABASE_URL"):
        await startup.adopt_stored_livekit({}, max_attempts=1, sleep=no_sleep)


async def test_waits_until_livekit_is_saved_then_adopts_it(
    admin_dsn: str,
    admin: psycopg.Connection,
    two_workspaces: tuple[uuid.UUID, uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws, _ = two_workspaces
    keyring = f"k1:{SecretBox.generate_key()}"
    monkeypatch.setenv("VOIZY_SECRET_KEYS", keyring)
    env = {"VOIZY_DATABASE_URL": admin_dsn}
    admin.execute("UPDATE instance_settings SET primary_workspace_id = %s", (ws,))

    sleeps: list[float] = []

    async def save_after_two_polls(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 2:  # the operator connects LiveKit in the dashboard meanwhile
            pool = await open_pool(admin_dsn)
            try:
                box = SecretBox.from_env_value(keyring)
                async with pool.connection() as conn:
                    for name, value in (
                        ("livekit_url", "wss://p.livekit.cloud"),
                        ("livekit_api_key", "APIabc123def"),
                        ("livekit_api_secret", "s" * 32),
                    ):
                        await store.put_secret(conn, box, ws, name, value, kind="integration")
            finally:
                await pool.close()

    creds = await startup.adopt_stored_livekit(env, interval_s=3, sleep=save_after_two_polls)
    assert creds is not None and creds.url == "wss://p.livekit.cloud"
    assert sleeps == [3, 3]  # polled, waited, polled, waited, found
    assert env["LIVEKIT_API_KEY"] == "APIabc123def" and env["LIVEKIT_API_SECRET"] == "s" * 32


async def test_gives_up_after_the_attempt_limit(
    admin_dsn: str, admin: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VOIZY_SECRET_KEYS", f"k1:{SecretBox.generate_key()}")
    env = {"VOIZY_DATABASE_URL": admin_dsn}
    assert await startup.adopt_stored_livekit(env, max_attempts=2, sleep=no_sleep) is None
    assert "LIVEKIT_URL" not in env
