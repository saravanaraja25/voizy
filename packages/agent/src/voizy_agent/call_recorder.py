"""Writes a call's history without ever touching the call itself.

The audio path only enqueues (never awaits the database). One background task drains the queue; any
failure is logged without content and dropped, because a lost transcript is better than a lost call.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from psycopg_pool import AsyncConnectionPool
from voizy_core.domain.agent_config import PolicyConfig
from voizy_core.services import calls

log = logging.getLogger("livekit.agents.voizy")
QUEUE_LIMIT = 500
CLOSE_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class _Turn:
    role: Literal["user", "agent", "tool"]
    text: str = ""
    tool_name: str | None = None
    tool_ok: bool | None = None
    tool_ms: int | None = None
    latency: dict[str, int] | None = None


@dataclass(frozen=True)
class _Remote:
    number: str


class CallRecorder:
    def __init__(
        self,
        pool: AsyncConnectionPool,
        workspace_id: uuid.UUID,
        *,
        agent_id: uuid.UUID,
        version: int,
        room: str,
        policy: PolicyConfig,
        source: calls.Source = "test",
        campaign_id: uuid.UUID | None = None,
        contact_id: uuid.UUID | None = None,
    ) -> None:
        self._pool = pool
        self._ws = workspace_id
        self._agent_id, self._version, self._room = agent_id, version, room
        self._policy, self._source = policy, source
        self._campaign_id, self._contact_id = campaign_id, contact_id
        self._queue: asyncio.Queue[_Turn | _Remote | None] = asyncio.Queue(QUEUE_LIMIT)
        self._task: asyncio.Task[None] | None = None
        self._call_id: uuid.UUID | None = None
        self._seq = 0
        self._closed = False

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    def remote_number(self, number: str) -> None:
        """Record who was on the other end. Never blocks or raises."""
        try:
            self._queue.put_nowait(_Remote(number))
        except asyncio.QueueFull:
            log.warning("call recorder queue full; dropping the remote number")

    def turn(
        self,
        role: Literal["user", "agent", "tool"],
        text: str = "",
        *,
        tool_name: str | None = None,
        tool_ok: bool | None = None,
        tool_ms: int | None = None,
        latency: dict[str, int] | None = None,
    ) -> None:
        """Queue a turn. Never blocks and never raises; drops when the queue is full."""
        try:
            self._queue.put_nowait(_Turn(role, text, tool_name, tool_ok, tool_ms, latency))
        except asyncio.QueueFull:
            log.warning("call recorder queue full; dropping a turn")

    async def close(self, *, status: calls.FinalStatus = "completed", reason: str = "") -> None:
        """Flush what is queued, then close the call. Bounded so shutdown cannot hang."""
        if self._task is None or self._closed:
            return
        self._closed = True
        try:
            await asyncio.wait_for(self._queue.put(None), CLOSE_TIMEOUT_S)
            await asyncio.wait_for(self._task, CLOSE_TIMEOUT_S)
        except (TimeoutError, asyncio.CancelledError):
            self._task.cancel()
            log.warning("call recorder did not flush in time")
        await self._safely(self._finish, status, reason)

    async def _run(self) -> None:
        await self._safely(self._open)
        while (item := await self._queue.get()) is not None:
            if self._call_id is not None:
                if isinstance(item, _Remote):
                    await self._safely(self._write_remote, item.number)
                else:
                    await self._safely(self._write, item)

    async def _safely(self, fn: Callable[..., Awaitable[None]], *args: Any) -> None:
        try:
            await fn(*args)
        except Exception as exc:  # noqa: BLE001 - recording must never affect the call
            log.warning("call recording failed (%s)", type(exc).__name__)

    async def _open(self) -> None:
        async with self._pool.connection() as conn:
            self._call_id = await calls.start_call(
                conn,
                self._ws,
                agent_id=self._agent_id,
                version=self._version,
                source=self._source,
                room=self._room,
                policy=self._policy,
                campaign_id=self._campaign_id,
                contact_id=self._contact_id,
            )

    async def _write_remote(self, number: str) -> None:
        if self._call_id is None:
            return
        async with self._pool.connection() as conn:
            await calls.set_remote_number(conn, self._ws, self._call_id, number)

    async def _write(self, t: _Turn) -> None:
        if self._call_id is None:
            return
        seq, self._seq = self._seq, self._seq + 1
        async with self._pool.connection() as conn:
            await calls.add_turn(
                conn,
                self._ws,
                self._call_id,
                seq,
                t.role,
                text=t.text,
                redact_pii=self._policy.redact_pii,
                tool_name=t.tool_name,
                tool_ok=t.tool_ok,
                tool_ms=t.tool_ms,
                latency=t.latency,
            )

    async def _finish(self, status: calls.FinalStatus, reason: str) -> None:
        if self._call_id is None:
            return
        async with self._pool.connection() as conn:
            await calls.finish_call(conn, self._ws, self._call_id, status=status, end_reason=reason)
