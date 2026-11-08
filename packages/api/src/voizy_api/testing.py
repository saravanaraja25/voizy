"""Shared pytest plugin and helpers for API tests."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable

import httpx
import psycopg
import pytest
import pytest_asyncio
from psycopg_pool import AsyncConnectionPool
from voizy_core.apikeys import generate_api_key
from voizy_core.db import open_pool
from voizy_core.permissions import ALL_PERMISSIONS

from voizy_api.app import create_app

MakeKey = Callable[..., str]


@pytest_asyncio.fixture
async def pool(admin_dsn: str) -> AsyncIterator[AsyncConnectionPool]:
    p = await open_pool(admin_dsn)
    yield p
    await p.close()


@pytest_asyncio.fixture
async def client(pool: AsyncConnectionPool) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app(pool))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def make_key(admin: psycopg.Connection) -> MakeKey:
    def make(workspace_id: uuid.UUID, permissions: frozenset[object] | None = None) -> str:
        perms = ALL_PERMISSIONS if permissions is None else permissions
        key = generate_api_key()
        admin.execute(
            "INSERT INTO api_keys (workspace_id, name, prefix, key_hash, permissions) "
            "VALUES (%s, 'test', %s, %s, %s)",
            (workspace_id, key.prefix, key.key_hash, sorted(str(p) for p in perms)),
        )
        return key.token

    return make


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def agent_body(name: str = "Receptionist") -> dict[str, object]:
    return {
        "name": name,
        "config": {
            "name": name,
            "system_prompt": "You are {{agent_name}}.",
            "stt": {"provider": "deepgram", "model": "nova-3"},
            "llm": {"provider": "openai", "model": "gpt-4o-mini"},
            "tts": {"provider": "cartesia", "model": "sonic", "voice_id": "v1"},
        },
    }
