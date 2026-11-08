"""Shared pytest plugin: database fixtures.

Set VOIZY_TEST_ADMIN_URL to a superuser URL on a disposable server; each session creates and
drops its own database, so nothing else on the server is touched.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

MIGRATIONS = Path(__file__).parent / "db" / "migrations"


@pytest.fixture(scope="session")
def admin_dsn() -> Iterator[str]:
    """Superuser DSN for a freshly migrated, throwaway database."""
    base = os.environ.get("VOIZY_TEST_ADMIN_URL")
    if not base:
        pytest.skip("VOIZY_TEST_ADMIN_URL not set")
    name = f"voizy_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(base, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    dsn = make_conninfo(base, dbname=name)
    with psycopg.connect(dsn, autocommit=True) as conn:
        for f in sorted(MIGRATIONS.glob("*.sql")):
            conn.execute(f.read_text())
    try:
        yield dsn
    finally:
        with psycopg.connect(base, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )


@pytest.fixture
def admin(admin_dsn: str) -> Iterator[psycopg.Connection]:
    """Superuser connection (bypasses RLS) for seeding."""
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        yield conn
        conn.execute(
            "TRUNCATE audit_log, agent_versions, agents, secrets, api_keys, memberships, "
            "role_permissions, roles, workspaces, users CASCADE"
        )


@pytest.fixture
def two_workspaces(admin: psycopg.Connection) -> tuple[uuid.UUID, uuid.UUID]:
    a, b = uuid.uuid4(), uuid.uuid4()
    for wid, name in ((a, "A"), (b, "B")):
        admin.execute("INSERT INTO workspaces (id, name) VALUES (%s, %s)", (wid, name))
    return a, b


def app_conn(dsn: str) -> psycopg.Connection:
    """Connection acting as the unprivileged application role."""
    conn = psycopg.connect(dsn)
    conn.execute("SET ROLE voizy_app")
    conn.commit()
    return conn
