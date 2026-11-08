"""Periodic cleanup of call history: expired calls are deleted, abandoned ones are closed.

Single-deployment scope: it covers the primary workspace. A multi-tenant host would iterate
workspaces here.
"""

from __future__ import annotations

import asyncio
import logging

from psycopg_pool import AsyncConnectionPool
from voizy_core.services import calls

log = logging.getLogger("uvicorn.error")
INTERVAL_S = 3600.0


async def run_once(pool: AsyncConnectionPool) -> tuple[int, int]:
    """Returns (purged, failed_stale). Does nothing before first-run setup."""
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT primary_workspace_id FROM instance_settings")
        row = await cur.fetchone()
    if row is None or row[0] is None:
        return 0, 0
    async with pool.connection() as conn:
        purged = await calls.purge_expired(conn, row[0])
    async with pool.connection() as conn:
        stale = await calls.fail_stale(conn, row[0])
    return purged, stale


async def retention_loop(pool: AsyncConnectionPool, interval_s: float = INTERVAL_S) -> None:
    while True:
        await asyncio.sleep(interval_s)
        try:
            purged, stale = await run_once(pool)
            if purged or stale:
                log.info("call retention: purged %d, closed %d stale", purged, stale)
        except Exception as exc:  # noqa: BLE001 - housekeeping must not take the API down
            log.warning("call retention failed (%s)", type(exc).__name__)
