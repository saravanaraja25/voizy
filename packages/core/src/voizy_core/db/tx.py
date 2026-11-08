"""Transactions that own their security context."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from psycopg import AsyncConnection
from psycopg.pq import TransactionStatus


@asynccontextmanager
async def owned_tx(conn: AsyncConnection) -> AsyncIterator[None]:
    """A real top-level transaction, or an error.

    Inside an already-open transaction, conn.transaction() would only be a savepoint: nothing
    would commit, and the transaction-local security context (app.user_id, app.workspace_id, ...)
    would leak into whatever the caller runs next. So refuse instead of silently degrading.
    """
    if conn.info.transaction_status != TransactionStatus.IDLE:
        raise RuntimeError("this function needs an idle connection (commit or roll back first)")
    async with conn.transaction():
        yield


async def set_local(conn: AsyncConnection, name: str, value: str) -> None:
    """Set a transaction-local setting (the context that row-level security reads)."""
    await conn.execute("SELECT set_config(%s, %s, true)", (name, value))
