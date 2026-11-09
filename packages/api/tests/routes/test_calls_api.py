"""Call history API: permission-gated, transcript-gated, tenant-isolated, deletes audited."""

from __future__ import annotations

import uuid
from collections.abc import Callable

import httpx
import psycopg
import pytest
from psycopg_pool import AsyncConnectionPool
from voizy_api.retention import run_once
from voizy_api.testing import MakeKey, bearer
from voizy_core.domain.agent_config import PolicyConfig
from voizy_core.domain.permissions import Permission
from voizy_core.services import calls
from voizy_core.services.bootstrap import BootstrapResult


async def seed(
    pool: AsyncConnectionPool, admin: psycopg.Connection, wid: uuid.UUID, n: int = 1
) -> list[uuid.UUID]:
    row = admin.execute(
        "INSERT INTO agents (workspace_id, name) VALUES (%s, 'Front desk') RETURNING id", (wid,)
    ).fetchone()
    assert row is not None
    ids = []
    for i in range(n):
        async with pool.connection() as conn:
            cid = await calls.start_call(
                conn,
                wid,
                agent_id=row[0],
                version=1,
                source="test",
                room=f"r{i}",
                policy=PolicyConfig(),
            )
        async with pool.connection() as conn:
            await calls.add_turn(conn, wid, cid, 0, "user", text="call me on 415-555-0134")
        async with pool.connection() as conn:
            await calls.finish_call(conn, wid, cid)
        ids.append(cid)
    return ids


async def test_list_detail_summary_and_pagination(
    client: httpx.AsyncClient,
    pool: AsyncConnectionPool,
    admin: psycopg.Connection,
    workspace_a: BootstrapResult,
) -> None:
    ids = await seed(pool, admin, workspace_a.workspace_id, 3)
    h = bearer(workspace_a.token)
    first = (await client.get("/v1/calls?limit=2", headers=h)).json()
    assert len(first["items"]) == 2 and first["next_cursor"]
    second = (
        await client.get(f"/v1/calls?limit=2&cursor={first['next_cursor']}", headers=h)
    ).json()
    assert second["next_cursor"] is None
    got = {c["id"] for c in [*first["items"], *second["items"]]}
    assert got == {str(i) for i in ids}
    assert first["items"][0]["agent_name"] == "Front desk"

    detail = (await client.get(f"/v1/calls/{ids[0]}", headers=h)).json()
    assert detail["transcript_visible"] is True
    assert detail["turns"][0]["text"] == "call me on [phone]"
    s = (await client.get("/v1/calls/summary", headers=h)).json()
    assert (s["total"], s["completed"]) == (3, 3)
    assert (await client.get("/v1/calls?cursor=garbage", headers=h)).status_code == 422
    assert (await client.get("/v1/calls?status=bogus", headers=h)).status_code == 422


async def test_transcript_needs_its_own_permission(
    client: httpx.AsyncClient,
    pool: AsyncConnectionPool,
    admin: psycopg.Connection,
    workspace_a: BootstrapResult,
    make_key: MakeKey,
) -> None:
    (cid,) = await seed(pool, admin, workspace_a.workspace_id)
    h = bearer(make_key(workspace_a.workspace_id, frozenset({Permission.CALLS_READ})))
    detail = (await client.get(f"/v1/calls/{cid}", headers=h)).json()
    assert detail["transcript_visible"] is False and detail["turns"] == []
    assert detail["call"]["turn_count"] == 1  # metadata is still shown


async def test_permissions_and_isolation(
    client: httpx.AsyncClient,
    pool: AsyncConnectionPool,
    admin: psycopg.Connection,
    workspace_a: BootstrapResult,
    make_key: MakeKey,
    two_workspaces: tuple[uuid.UUID, uuid.UUID],
) -> None:
    _, other_ws = two_workspaces
    (theirs,) = await seed(pool, admin, other_ws)
    h = bearer(workspace_a.token)
    assert (await client.get("/v1/calls")).status_code == 401
    nothing = bearer(make_key(workspace_a.workspace_id, frozenset({Permission.AGENTS_READ})))
    assert (await client.get("/v1/calls", headers=nothing)).status_code == 403
    assert (await client.get(f"/v1/calls/{theirs}", headers=h)).status_code == 404
    assert (await client.delete(f"/v1/calls/{theirs}", headers=h)).status_code == 404
    assert (await client.get("/v1/calls", headers=h)).json()["items"] == []


async def test_delete_is_gated_and_audited(
    client: httpx.AsyncClient,
    pool: AsyncConnectionPool,
    admin: psycopg.Connection,
    workspace_a: BootstrapResult,
    make_key: MakeKey,
) -> None:
    (cid,) = await seed(pool, admin, workspace_a.workspace_id)
    reader = bearer(make_key(workspace_a.workspace_id, frozenset({Permission.CALLS_READ})))
    assert (await client.delete(f"/v1/calls/{cid}", headers=reader)).status_code == 403
    assert (
        await client.delete(f"/v1/calls/{cid}", headers=bearer(workspace_a.token))
    ).status_code == 204
    assert (await client.get(f"/v1/calls/{cid}", headers=reader)).status_code == 404
    logged = admin.execute(
        "SELECT target_id FROM audit_log WHERE action = 'call.delete'"
    ).fetchall()
    assert logged == [(str(cid),)]


@pytest.mark.usefixtures("fresh_instance")
async def test_retention_sweep_removes_expired_calls(
    pool: AsyncConnectionPool,
    admin: psycopg.Connection,
    workspace_a: BootstrapResult,
    make_client: Callable[[], httpx.AsyncClient],
) -> None:
    (cid,) = await seed(pool, admin, workspace_a.workspace_id)
    admin.execute("UPDATE calls SET expires_at = now() - interval '1 day'")
    assert await run_once(pool) == (1, 0)
    assert admin.execute("SELECT count(*) FROM calls WHERE id = %s", (cid,)).fetchone() == (0,)


async def test_numbers_are_masked_without_view_pii(
    client: httpx.AsyncClient,
    pool: AsyncConnectionPool,
    admin: psycopg.Connection,
    workspace_a: BootstrapResult,
    make_key: MakeKey,
) -> None:
    (cid,) = await seed(pool, admin, workspace_a.workspace_id)
    admin.execute("UPDATE calls SET remote_number = '+14155550134'")
    full = bearer(workspace_a.token)
    d = (await client.get(f"/v1/calls/{cid}", headers=full)).json()["call"]
    assert d["remote_number"] == "+14155550134" and d["remote_number_masked"] is False

    reader = bearer(make_key(workspace_a.workspace_id, frozenset({Permission.CALLS_READ})))
    for path in (f"/v1/calls/{cid}", "/v1/calls"):
        r = await client.get(path, headers=reader)
        assert "+14155550134" not in r.text and "5550134" not in r.text
    masked = (await client.get(f"/v1/calls/{cid}", headers=reader)).json()["call"]
    assert masked["remote_number"] == "•••• 0134" and masked["remote_number_masked"] is True
    listed = (await client.get("/v1/calls", headers=reader)).json()["items"][0]
    assert listed["remote_number"] == "•••• 0134"
