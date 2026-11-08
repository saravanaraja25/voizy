from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from voizy_core.apikeys import TOKEN_RE, authenticate_api_key, generate_api_key, hash_token
from voizy_core.permissions import Permission
from voizy_core.testing import app_conn


def test_token_shape_hash_and_uniqueness() -> None:
    a, b = generate_api_key(), generate_api_key()
    assert TOKEN_RE.match(a.token) and a.token != b.token
    assert a.key_hash == hash_token(a.token) and len(a.key_hash) == 32
    assert a.token.startswith(a.prefix) and a.token not in repr(a.key_hash)


def insert_key(admin: psycopg.Connection, wid: uuid.UUID, perms: list[str], **cols: object) -> str:
    key = generate_api_key()
    admin.execute(
        "INSERT INTO api_keys (workspace_id, name, prefix, key_hash, permissions, "
        "expires_at, revoked_at) VALUES (%s, 'k', %s, %s, %s, %s, %s)",
        (wid, key.prefix, key.key_hash, perms, cols.get("expires_at"), cols.get("revoked_at")),
    )
    return key.token


async def auth(dsn: str, token: str):  # type: ignore[no-untyped-def]
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await conn.execute("SET ROLE voizy_app")
        await conn.commit()
        return await authenticate_api_key(conn, token)


@pytest.mark.asyncio
async def test_valid_key_resolves_to_workspace_and_known_permissions(
    admin_dsn: str, admin: psycopg.Connection, two_workspaces: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, _ = two_workspaces
    token = insert_key(admin, a, ["agents:read", "retired:permission"])
    principal = await auth(admin_dsn, token)
    assert principal is not None and principal.workspace_id == a
    assert principal.permissions == {Permission.AGENTS_READ}


@pytest.mark.asyncio
async def test_unknown_malformed_revoked_and_expired_keys_fail_identically(
    admin_dsn: str, admin: psycopg.Connection, two_workspaces: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, _ = two_workspaces
    now = datetime.now(UTC)
    revoked = insert_key(admin, a, ["agents:read"], revoked_at=now)
    expired = insert_key(admin, a, ["agents:read"], expires_at=now - timedelta(seconds=1))
    for token in (generate_api_key().token, "garbage", "", revoked, expired, "' OR 1=1 --"):
        assert await auth(admin_dsn, token) is None


def test_lookup_policy_is_read_only_and_needs_the_exact_hash(
    admin_dsn: str, admin: psycopg.Connection, two_workspaces: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, _ = two_workspaces
    token = insert_key(admin, a, ["agents:read"])
    with app_conn(admin_dsn) as conn:
        assert conn.execute("SELECT count(*) FROM api_keys").fetchone() == (0,)
        conn.execute("SELECT set_config('app.api_key_hash', %s, true)", (hash_token("x").hex(),))
        assert conn.execute("SELECT count(*) FROM api_keys").fetchone() == (0,)
        conn.execute("SELECT set_config('app.api_key_hash', %s, true)", (hash_token(token).hex(),))
        assert conn.execute("SELECT count(*) FROM api_keys").fetchone() == (1,)
        # Visible for lookup, but the policy grants no write or delete.
        assert conn.execute("UPDATE api_keys SET permissions = ARRAY['roles:manage']").rowcount == 0
        assert conn.execute("DELETE FROM api_keys").rowcount == 0
    row = admin.execute("SELECT permissions FROM api_keys").fetchone()
    assert row == (["agents:read"],)
