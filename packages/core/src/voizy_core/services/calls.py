"""Call history: recording, listing, deletion and retention.

What is stored is decided here, before any row is written: transcripts only if the agent's policy
keeps them, text redacted if the policy asks, tool turns without arguments or results, and an
expiry on every call.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from voizy_core.db.tx import owned_tx, set_local
from voizy_core.domain.agent_config import PolicyConfig
from voizy_core.security.redact import redact

Source = Literal["test", "inbound", "outbound"]
Status = Literal["in_progress", "completed", "failed"]
METADATA_RETENTION_DAYS = 30  # call metadata is kept this long when transcripts are not
MAX_TEXT = 8000


@dataclass(frozen=True)
class CallRow:
    id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: str
    agent_version: int
    source: str
    room: str
    status: str
    started_at: dt.datetime
    ended_at: dt.datetime | None
    duration_s: int | None
    end_reason: str
    turn_count: int
    latency_p50_ms: int | None
    transcript_stored: bool


@dataclass(frozen=True)
class TurnRow:
    seq: int
    role: str
    text: str
    tool_name: str | None
    tool_ok: bool | None
    tool_ms: int | None
    latency: dict[str, int] | None
    at: dt.datetime


_CALL_COLS = (
    "c.id, c.agent_id, a.name, c.agent_version, c.source, c.room, c.status, c.started_at, "
    "c.ended_at, c.duration_s, c.end_reason, c.turn_count, c.latency_p50_ms, c.transcript_stored"
)
_CALL_FROM = "FROM calls c JOIN agents a ON a.workspace_id = c.workspace_id AND a.id = c.agent_id"


async def start_call(
    conn: AsyncConnection,
    workspace_id: uuid.UUID,
    *,
    agent_id: uuid.UUID,
    version: int,
    source: Source,
    room: str,
    policy: PolicyConfig,
) -> uuid.UUID:
    keep_transcript = policy.save_transcripts and policy.retention_days > 0
    days = policy.retention_days if policy.retention_days > 0 else METADATA_RETENTION_DAYS
    async with owned_tx(conn):
        await set_local(conn, "app.workspace_id", str(workspace_id))
        cur = await conn.execute(
            "INSERT INTO calls (workspace_id, agent_id, agent_version, source, room, "
            "transcript_stored, expires_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, now() + %s * interval '1 day') "
            "RETURNING id",
            (workspace_id, agent_id, version, source, room[:200], keep_transcript, days),
        )
        row = await cur.fetchone()
    if row is None:
        raise RuntimeError("call insert returned no row")
    return row[0]  # type: ignore[no-any-return]


async def add_turn(
    conn: AsyncConnection,
    workspace_id: uuid.UUID,
    call_id: uuid.UUID,
    seq: int,
    role: Literal["user", "agent", "tool"],
    *,
    text: str = "",
    redact_pii: bool = True,
    tool_name: str | None = None,
    tool_ok: bool | None = None,
    tool_ms: int | None = None,
    latency: dict[str, int] | None = None,
) -> bool:
    """Append a turn. Returns False when the call keeps no transcript (nothing was written).

    Agent turns' latency is kept even then: timings carry no personal data.
    """
    async with owned_tx(conn):
        await set_local(conn, "app.workspace_id", str(workspace_id))
        cur = await conn.execute(
            "SELECT transcript_stored FROM calls WHERE id = %s AND status = 'in_progress'",
            (call_id,),
        )
        row = await cur.fetchone()
        if row is None:
            return False
        keep_text = bool(row[0])
        if not keep_text and not (role == "agent" and latency):
            return False
        stored = (redact(text) if redact_pii else text)[:MAX_TEXT] if keep_text else ""
        await conn.execute(
            "INSERT INTO call_turns (workspace_id, call_id, seq, role, text, tool_name, tool_ok, "
            "tool_ms, latency) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT DO NOTHING",
            (
                workspace_id,
                call_id,
                seq,
                role,
                stored,
                tool_name,
                tool_ok,
                tool_ms,
                Jsonb(latency) if latency else None,
            ),
        )
    return True


async def finish_call(
    conn: AsyncConnection,
    workspace_id: uuid.UUID,
    call_id: uuid.UUID,
    *,
    status: Literal["completed", "failed"] = "completed",
    end_reason: str = "",
) -> None:
    """Close an in-progress call and compute its totals. Safe to call twice."""
    async with owned_tx(conn):
        await set_local(conn, "app.workspace_id", str(workspace_id))
        await conn.execute(
            "UPDATE calls SET status = %s, ended_at = now(), end_reason = %s, "
            "duration_s = greatest(0, extract(epoch FROM now() - started_at))::int, "
            "turn_count = (SELECT count(*) FROM call_turns t "
            "WHERE t.workspace_id = calls.workspace_id "
            "AND t.call_id = calls.id AND t.role IN ('user', 'agent')), "
            "latency_p50_ms = (SELECT percentile_disc(0.5) "
            "WITHIN GROUP (ORDER BY (latency->>'e2e')::int) "
            "FROM call_turns t WHERE t.workspace_id = calls.workspace_id AND t.call_id = calls.id "
            "AND latency ? 'e2e') "
            "WHERE id = %s AND status = 'in_progress'",
            (status, end_reason[:200], call_id),
        )


def _call(r: tuple[Any, ...]) -> CallRow:
    return CallRow(*r)


async def list_calls(
    conn: AsyncConnection,
    workspace_id: uuid.UUID,
    *,
    agent_id: uuid.UUID | None = None,
    status: str | None = None,
    source: str | None = None,
    room: str | None = None,
    before: tuple[dt.datetime, uuid.UUID] | None = None,
    limit: int = 50,
) -> list[CallRow]:
    """Newest first, keyset-paginated: pass the last row's (started_at, id) as `before`."""
    where: list[str] = ["true"]
    params: list[Any] = []
    for clause, value in (
        ("c.agent_id = %s", agent_id),
        ("c.status = %s", status),
        ("c.source = %s", source),
        ("c.room = %s", room),
    ):
        if value is not None:
            where.append(clause)
            params.append(value)
    if before is not None:
        where.append("(c.started_at, c.id) < (%s, %s)")
        params.extend(before)
    async with owned_tx(conn):
        await set_local(conn, "app.workspace_id", str(workspace_id))
        cur = await conn.execute(
            f"SELECT {_CALL_COLS} {_CALL_FROM} WHERE {' AND '.join(where)} "
            "ORDER BY c.started_at DESC, c.id DESC LIMIT %s",
            (*params, max(1, min(limit, 200))),
        )
        return [_call(r) for r in await cur.fetchall()]


async def get_call(
    conn: AsyncConnection, workspace_id: uuid.UUID, call_id: uuid.UUID, *, with_turns: bool = True
) -> tuple[CallRow, list[TurnRow]] | None:
    async with owned_tx(conn):
        await set_local(conn, "app.workspace_id", str(workspace_id))
        cur = await conn.execute(
            f"SELECT {_CALL_COLS} {_CALL_FROM} WHERE c.id = %s",
            (call_id,),  # noqa: S608
        )
        row = await cur.fetchone()
        if row is None:
            return None
        turns: list[TurnRow] = []
        if with_turns:
            cur = await conn.execute(
                "SELECT seq, role, text, tool_name, tool_ok, tool_ms, latency, at "
                "FROM call_turns WHERE call_id = %s ORDER BY seq",
                (call_id,),
            )
            turns = [TurnRow(*r) for r in await cur.fetchall()]
    return _call(row), turns


async def delete_call(conn: AsyncConnection, workspace_id: uuid.UUID, call_id: uuid.UUID) -> bool:
    async with owned_tx(conn):
        await set_local(conn, "app.workspace_id", str(workspace_id))
        cur = await conn.execute("DELETE FROM calls WHERE id = %s RETURNING id", (call_id,))
        return await cur.fetchone() is not None


async def purge_expired(conn: AsyncConnection, workspace_id: uuid.UUID) -> int:
    """Delete calls past their expiry (and their turns). Returns how many were removed."""
    async with owned_tx(conn):
        await set_local(conn, "app.workspace_id", str(workspace_id))
        cur = await conn.execute(
            "DELETE FROM calls WHERE expires_at IS NOT NULL AND expires_at < now()"
        )
        return cur.rowcount


async def fail_stale(
    conn: AsyncConnection,
    workspace_id: uuid.UUID,
    *,
    older_than: dt.timedelta = dt.timedelta(hours=2),
) -> int:
    """Calls still 'in progress' long after they began were cut off (a crashed worker)."""
    async with owned_tx(conn):
        await set_local(conn, "app.workspace_id", str(workspace_id))
        cur = await conn.execute(
            "UPDATE calls SET status = 'failed', ended_at = now(), end_reason = 'worker stopped' "
            "WHERE status = 'in_progress' AND started_at < now() - %s",
            (older_than,),
        )
        return cur.rowcount


@dataclass(frozen=True)
class CallSummary:
    total: int
    completed: int
    failed: int
    avg_duration_s: int | None
    median_latency_ms: int | None


async def summary(
    conn: AsyncConnection, workspace_id: uuid.UUID, *, since: dt.datetime
) -> CallSummary:
    async with owned_tx(conn):
        await set_local(conn, "app.workspace_id", str(workspace_id))
        cur = await conn.execute(
            "SELECT count(*), count(*) FILTER (WHERE status = 'completed'), "
            "count(*) FILTER (WHERE status = 'failed'), "
            "avg(duration_s)::int, percentile_disc(0.5) WITHIN GROUP (ORDER BY latency_p50_ms) "
            "FROM calls WHERE started_at >= %s",
            (since,),
        )
        row = await cur.fetchone()
    if row is None:
        return CallSummary(0, 0, 0, None, None)
    return CallSummary(*row)
