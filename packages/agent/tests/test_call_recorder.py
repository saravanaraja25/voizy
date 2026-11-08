from __future__ import annotations

import uuid

import psycopg
import pytest
from voizy_agent.call_recorder import CallRecorder
from voizy_core.db.pool import open_pool
from voizy_core.domain.agent_config import PolicyConfig


def make_agent(admin: psycopg.Connection, wid: uuid.UUID) -> uuid.UUID:
    row = admin.execute(
        "INSERT INTO agents (workspace_id, name) VALUES (%s, 'x') RETURNING id", (wid,)
    ).fetchone()
    assert row is not None
    return row[0]  # type: ignore[no-any-return]


@pytest.mark.asyncio
async def test_records_in_order_redacts_and_closes(
    admin_dsn: str, admin: psycopg.Connection, two_workspaces: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, _ = two_workspaces
    pool = await open_pool(admin_dsn)
    try:
        rec = CallRecorder(
            pool, a, agent_id=make_agent(admin, a), version=3, room="r1", policy=PolicyConfig()
        )
        rec.start()
        rec.turn("user", "my mail is a@b.io")
        rec.turn("tool", tool_name="lookup", tool_ok=False, tool_ms=12)
        rec.turn("agent", "ok", latency={"e2e": 640})
        await rec.close(reason="ended")
    finally:
        await pool.close()

    call = admin.execute(
        "SELECT status, agent_version, turn_count, latency_p50_ms FROM calls"
    ).fetchone()
    assert call == ("completed", 3, 2, 640)
    rows = admin.execute("SELECT seq, role, text FROM call_turns ORDER BY seq").fetchall()
    assert rows == [(0, "user", "my mail is [email]"), (1, "tool", ""), (2, "agent", "ok")]


@pytest.mark.asyncio
async def test_database_failure_never_raises(admin_dsn: str) -> None:
    pool = await open_pool(admin_dsn)
    await pool.close()  # every write now fails
    rec = CallRecorder(
        pool,
        uuid.uuid4(),
        agent_id=uuid.uuid4(),
        version=1,
        room="r",
        policy=PolicyConfig(),
    )
    rec.start()
    rec.turn("user", "hello")
    await rec.close()
