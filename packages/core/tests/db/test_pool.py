from __future__ import annotations

import uuid

import psycopg
import pytest
from voizy_core.db.pool import open_pool, workspace_tx


@pytest.mark.asyncio
async def test_workspace_tx_scopes_rows_and_does_not_leak_across_pool_reuse(
    admin_dsn: str,
    admin: psycopg.Connection,
    two_workspaces: tuple[uuid.UUID, uuid.UUID],
) -> None:
    a, b = two_workspaces
    admin.execute(
        "INSERT INTO agents (workspace_id, name) VALUES (%s, 'alpha'), (%s, 'bravo')", (a, b)
    )
    pool = await open_pool(admin_dsn, max_size=1)  # max_size=1 forces connection reuse
    try:
        async with workspace_tx(pool, a) as conn:
            rows = await (await conn.execute("SELECT name FROM agents")).fetchall()
            assert rows == [("alpha",)]
        async with pool.connection() as conn:  # same connection, no workspace set
            assert await (await conn.execute("SELECT count(*) FROM agents")).fetchone() == (0,)
        with pytest.raises(RuntimeError):
            async with workspace_tx(pool, b) as conn:
                await conn.execute(
                    "INSERT INTO agents (workspace_id, name) VALUES (%s, 'tmp')", (b,)
                )
                raise RuntimeError("rollback")
        async with workspace_tx(pool, b) as conn:
            names = await (await conn.execute("SELECT name FROM agents ORDER BY name")).fetchall()
            assert names == [("bravo",)]
    finally:
        await pool.close()


async def test_an_unreachable_database_fails_with_a_clear_message() -> None:
    import pytest
    from voizy_core.db.pool import DatabaseUnavailableError

    with pytest.raises(DatabaseUnavailableError, match="Could not connect to the database"):
        await open_pool("postgresql://nobody@127.0.0.1:1/none", timeout=1.0)
