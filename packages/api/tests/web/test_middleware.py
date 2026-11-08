from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from voizy_api.testing import bearer
from voizy_core.services.bootstrap import BootstrapResult

pytestmark = pytest.mark.asyncio


async def test_security_headers_present(client: httpx.AsyncClient) -> None:
    r = await client.get("/healthz")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-frame-options"] == "DENY"


async def test_oversized_declared_body_gets_413_before_auth(client: httpx.AsyncClient) -> None:
    r = await client.post("/v1/agents", content=b"x" * (1_048_576 + 1))
    assert r.status_code == 413


async def test_oversized_streamed_body_gets_413(
    client: httpx.AsyncClient, workspace_a: BootstrapResult
) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(3):
            yield b"x" * 600_000

    r = await client.post("/v1/agents", content=chunks(), headers=bearer(workspace_a.token))
    assert r.status_code == 413


async def test_normal_requests_unaffected(
    client: httpx.AsyncClient, workspace_a: BootstrapResult
) -> None:
    r = await client.get("/v1/agents", headers=bearer(workspace_a.token))
    assert r.status_code == 200
