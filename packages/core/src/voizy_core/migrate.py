"""Forward-only SQL migration runner. Each file runs once, in its own transaction."""

from __future__ import annotations

import hashlib
from pathlib import Path

from psycopg import AsyncConnection, sql

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_LOCK_KEY = 7_212_001  # arbitrary constant: serializes concurrent migrators


class MigrationError(Exception):
    pass


async def migrate(conn: AsyncConnection, *, login_role: str | None = None) -> list[str]:
    """Apply pending migrations; return the names applied. Detects edited applied files."""
    applied_now: list[str] = []
    await conn.execute("SELECT pg_advisory_lock(%s)", (_LOCK_KEY,))
    await conn.commit()
    try:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "name text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz DEFAULT now())"
        )
        await conn.commit()
        cur = await conn.execute("SELECT name, checksum FROM schema_migrations")
        done: dict[str, str] = {name: checksum for name, checksum in await cur.fetchall()}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            text = path.read_text()
            checksum = hashlib.sha256(text.encode()).hexdigest()
            if path.name in done:
                if done[path.name] != checksum:
                    raise MigrationError(f"{path.name} was modified after it was applied")
                continue
            async with conn.transaction():
                await conn.execute(text.encode())
                await conn.execute(
                    "INSERT INTO schema_migrations (name, checksum) VALUES (%s, %s)",
                    (path.name, checksum),
                )
            applied_now.append(path.name)
        if login_role:
            # Let the application's login role act as the unprivileged voizy_app role.
            await conn.execute(sql.SQL("GRANT voizy_app TO {}").format(sql.Identifier(login_role)))
            await conn.commit()
    finally:
        await conn.execute("SELECT pg_advisory_unlock(%s)", (_LOCK_KEY,))
        await conn.commit()
    return applied_now
