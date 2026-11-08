"""Connection pool and tenant-scoped transactions."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from psycopg import AsyncConnection, sql
from psycopg_pool import AsyncConnectionPool


async def open_pool(
    dsn: str, *, role: str | None = "voizy_app", max_size: int = 10
) -> AsyncConnectionPool:
    """Open a pool whose connections act as the unprivileged app role (RLS applies)."""

    async def configure(conn: AsyncConnection) -> None:
        if role:
            await conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
        await conn.commit()

    pool = AsyncConnectionPool(dsn, min_size=1, max_size=max_size, open=False, configure=configure)
    await pool.open(wait=True)
    return pool


@asynccontextmanager
async def workspace_tx(
    pool: AsyncConnectionPool, workspace_id: uuid.UUID
) -> AsyncIterator[AsyncConnection]:
    """One transaction scoped to a workspace; the setting disappears at commit or rollback."""
    async with pool.connection() as conn, conn.transaction():
        await conn.execute("SELECT set_config('app.workspace_id', %s, true)", (str(workspace_id),))
        yield conn
