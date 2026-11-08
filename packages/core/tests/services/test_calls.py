from __future__ import annotations

import datetime as dt
import uuid

import psycopg
import pytest
from psycopg import AsyncConnection
from voizy_core.domain.agent_config import PolicyConfig
from voizy_core.services import calls

pytestmark = pytest.mark.asyncio
WS = tuple[uuid.UUID, uuid.UUID]


def make_agent(admin: psycopg.Connection, wid: uuid.UUID, name: str = "alpha") -> uuid.UUID:
    row = admin.execute(
        "INSERT INTO agents (workspace_id, name) VALUES (%s, %s) RETURNING id", (wid, name)
    ).fetchone()
    assert row is not None
    return row[0]  # type: ignore[no-any-return]


async def begin(
    conn: AsyncConnection, wid: uuid.UUID, agent: uuid.UUID, policy: PolicyConfig | None = None
) -> uuid.UUID:
    return await calls.start_call(
        conn,
        wid,
        agent_id=agent,
        version=1,
        source="test",
        room=f"room-{uuid.uuid4().hex[:6]}",
        policy=policy or PolicyConfig(),
    )


async def test_record_redacts_and_finishes_with_totals(
    app_aconn: AsyncConnection, admin: psycopg.Connection, two_workspaces: WS
) -> None:
    a, _ = two_workspaces
    agent = make_agent(admin, a)
    cid = await begin(app_aconn, a, agent)
    await calls.add_turn(app_aconn, a, cid, 0, "user", text="email me at jo@example.com")
    await calls.add_turn(app_aconn, a, cid, 1, "agent", text="Sure.", latency={"e2e": 900})
    await calls.add_turn(app_aconn, a, cid, 2, "tool", tool_name="lookup", tool_ok=True, tool_ms=40)
    await calls.add_turn(app_aconn, a, cid, 3, "agent", text="Done.", latency={"e2e": 700})
    await calls.finish_call(app_aconn, a, cid, end_reason="hangup")
    await calls.finish_call(app_aconn, a, cid, status="failed")  # second close is a no-op

    got = await calls.get_call(app_aconn, a, cid)
    assert got is not None
    row, turns = got
    assert row.status == "completed" and row.end_reason == "hangup"
    assert row.turn_count == 3 and row.latency_p50_ms in (700, 900)
    assert turns[0].text == "email me at [email]"
    assert turns[2].tool_name == "lookup" and turns[2].text == ""


async def test_no_transcript_keeps_only_agent_timings(
    app_aconn: AsyncConnection, admin: psycopg.Connection, two_workspaces: WS
) -> None:
    a, _ = two_workspaces
    agent = make_agent(admin, a)
    cid = await begin(app_aconn, a, agent, PolicyConfig(save_transcripts=False))
    assert not await calls.add_turn(app_aconn, a, cid, 0, "user", text="secret words")
    assert await calls.add_turn(app_aconn, a, cid, 1, "agent", text="reply", latency={"e2e": 800})
    got = await calls.get_call(app_aconn, a, cid)
    assert got is not None
    assert [(t.role, t.text) for t in got[1]] == [("agent", "")]
    assert got[0].transcript_stored is False


async def test_turns_rejected_after_finish(
    app_aconn: AsyncConnection, admin: psycopg.Connection, two_workspaces: WS
) -> None:
    a, _ = two_workspaces
    cid = await begin(app_aconn, a, make_agent(admin, a))
    await calls.finish_call(app_aconn, a, cid)
    assert not await calls.add_turn(app_aconn, a, cid, 0, "user", text="late")


async def test_listing_filters_pages_and_isolates_tenants(
    app_aconn: AsyncConnection, admin: psycopg.Connection, two_workspaces: WS
) -> None:
    a, b = two_workspaces
    agent_a, agent_b = make_agent(admin, a), make_agent(admin, b)
    ids = [await begin(app_aconn, a, agent_a) for _ in range(3)]
    other = await begin(app_aconn, b, agent_b)

    page1 = await calls.list_calls(app_aconn, a, limit=2)
    assert len(page1) == 2
    last = page1[-1]
    page2 = await calls.list_calls(app_aconn, a, limit=2, before=(last.started_at, last.id))
    assert {c.id for c in [*page1, *page2]} == set(ids)
    assert other not in {c.id for c in [*page1, *page2]}
    assert await calls.list_calls(app_aconn, a, status="failed") == []
    assert await calls.get_call(app_aconn, a, other) is None
    assert not await calls.delete_call(app_aconn, a, other)


async def test_delete_purge_and_stale(
    app_aconn: AsyncConnection, admin: psycopg.Connection, two_workspaces: WS
) -> None:
    a, _ = two_workspaces
    agent = make_agent(admin, a)
    gone = await begin(app_aconn, a, agent)
    old = await begin(app_aconn, a, agent)
    stale = await begin(app_aconn, a, agent)
    await calls.add_turn(app_aconn, a, gone, 0, "user", text="hi")
    assert await calls.delete_call(app_aconn, a, gone)
    assert admin.execute("SELECT count(*) FROM call_turns").fetchone() == (0,)

    admin.execute("UPDATE calls SET expires_at = now() - interval '1 day' WHERE id = %s", (old,))
    assert await calls.purge_expired(app_aconn, a) == 1
    admin.execute(
        "UPDATE calls SET started_at = now() - interval '5 hours' WHERE id = %s", (stale,)
    )
    assert await calls.fail_stale(app_aconn, a) == 1
    got = await calls.get_call(app_aconn, a, stale, with_turns=False)
    assert got is not None and got[0].status == "failed"


async def test_summary(
    app_aconn: AsyncConnection, admin: psycopg.Connection, two_workspaces: WS
) -> None:
    a, _ = two_workspaces
    agent = make_agent(admin, a)
    ok, bad = await begin(app_aconn, a, agent), await begin(app_aconn, a, agent)
    await calls.finish_call(app_aconn, a, ok)
    await calls.finish_call(app_aconn, a, bad, status="failed")
    s = await calls.summary(app_aconn, a, since=dt.datetime.now(dt.UTC) - dt.timedelta(days=1))
    assert (s.total, s.completed, s.failed) == (2, 1, 1)
