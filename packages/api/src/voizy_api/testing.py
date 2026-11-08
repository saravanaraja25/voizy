"""Shared pytest plugin and helpers for API tests."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable

import httpx
import psycopg
import pytest
import pytest_asyncio
from psycopg_pool import AsyncConnectionPool
from voizy_core.db.pool import open_pool
from voizy_core.domain.permissions import ALL_PERMISSIONS
from voizy_core.security.apikeys import generate_api_key
from voizy_core.security.secretbox import SecretBox
from voizy_core.security.throttle import Throttle
from voizy_core.services.bootstrap import BootstrapResult, bootstrap_workspace

from voizy_api.app import create_app
from voizy_api.integration_checks import CheckResult
from voizy_api.settings import Settings

MakeKey = Callable[..., str]


@pytest_asyncio.fixture
async def pool(admin_dsn: str) -> AsyncIterator[AsyncConnectionPool]:
    p = await open_pool(admin_dsn)
    yield p
    await p.close()


class FakeChecker:
    """Stands in for 'test connection': records what it was asked to verify."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.ok = True

    async def __call__(self, integration_id: str, values: dict[str, str]) -> CheckResult:
        self.calls.append((integration_id, dict(values)))
        return CheckResult(self.ok, "Connected." if self.ok else "The provider rejected the key.")


SETUP_TOKEN = "setup-token-for-tests"  # noqa: S105 - test value
DASHBOARD_ORIGIN = "http://localhost:5173"


@pytest.fixture
def app_settings() -> Settings:
    return Settings(
        cors_origins=[DASHBOARD_ORIGIN],
        cookie_secure=False,  # tests speak plain http
        setup_token=SETUP_TOKEN,
        custom_roles=True,  # the existing suites exercise roles; superadmin-only has its own
        secret_box=SecretBox.from_env_value(f"k1:{SecretBox.generate_key()}"),
        integration_checker=FakeChecker(),
        email_throttle=Throttle(5, 900),
        ip_throttle=Throttle(30, 900),
    )


@pytest_asyncio.fixture
async def make_client(
    pool: AsyncConnectionPool, app_settings: Settings
) -> AsyncIterator[Callable[[], httpx.AsyncClient]]:
    """Factory for independent clients (each has its own cookie jar) against one app."""
    app = create_app(pool, settings=app_settings)
    made: list[httpx.AsyncClient] = []

    def make() -> httpx.AsyncClient:
        c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        made.append(c)
        return c

    yield make
    for c in made:
        await c.aclose()


@pytest_asyncio.fixture
async def client(
    make_client: Callable[[], httpx.AsyncClient],
) -> AsyncIterator[httpx.AsyncClient]:
    yield make_client()


@pytest.fixture
def fresh_instance(admin: psycopg.Connection) -> None:
    """Depend on this to get first-run setup reopened after the test (via the admin fixture)."""


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


@pytest_asyncio.fixture
async def workspace_a(admin_dsn: str) -> BootstrapResult:
    """A bootstrapped workspace with seeded roles and a superadmin API key."""
    async with await psycopg.AsyncConnection.connect(admin_dsn) as conn:
        return await bootstrap_workspace(conn, "A", seed_templates=True)
