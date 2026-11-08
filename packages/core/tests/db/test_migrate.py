from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from voizy_core.db import migrate as migrate_module
from voizy_core.db.migrate import MigrationError, migrate


@pytest.fixture
def blank_dsn(admin_dsn: str) -> Iterator[str]:
    """A second empty database on the same throwaway server."""
    name = f"voizy_mig_{uuid.uuid4().hex[:10]}"
    base = psycopg.conninfo.make_conninfo(admin_dsn, dbname="postgres")
    with psycopg.connect(base, autocommit=True) as c:
        c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    yield psycopg.conninfo.make_conninfo(admin_dsn, dbname=name)
    with psycopg.connect(base, autocommit=True) as c:
        c.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.mark.asyncio
async def test_applies_once_is_idempotent_and_detects_edits(
    blank_dsn: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async with await psycopg.AsyncConnection.connect(blank_dsn) as conn:
        first = await migrate(conn)
        assert first[0] == "0001_init.sql" and len(first) >= 2
        assert await migrate(conn) == []

    fake = tmp_path / "m"
    fake.mkdir()
    (fake / "0001_init.sql").write_text("SELECT 1;")
    monkeypatch.setattr(migrate_module, "MIGRATIONS_DIR", fake)
    async with await psycopg.AsyncConnection.connect(blank_dsn) as conn:
        with pytest.raises(MigrationError, match="modified"):
            await migrate(conn)


@pytest.mark.asyncio
async def test_failed_migration_rolls_back_and_is_not_recorded(
    blank_dsn: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = tmp_path / "m"
    fake.mkdir()
    (fake / "0001_bad.sql").write_text("CREATE TABLE t (a int); SELECT 1/0;")
    monkeypatch.setattr(migrate_module, "MIGRATIONS_DIR", fake)
    async with await psycopg.AsyncConnection.connect(blank_dsn) as conn:
        with pytest.raises(psycopg.errors.DivisionByZero):
            await migrate(conn)
        await conn.rollback()
        assert (await (await conn.execute("SELECT to_regclass('t')")).fetchone()) == (None,)
        assert (
            await (await conn.execute("SELECT count(*) FROM schema_migrations")).fetchone()
        ) == (0,)
