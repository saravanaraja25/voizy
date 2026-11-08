"""Tenant isolation and DB-level guarantees, exercised as the unprivileged app role."""

from __future__ import annotations

import json
import uuid

import psycopg
import pytest

from tests.conftest import app_conn


def use_workspace(conn: psycopg.Connection, wid: uuid.UUID) -> None:
    conn.execute("SELECT set_config('app.workspace_id', %s, true)", (str(wid),))


def seed_agent(admin: psycopg.Connection, wid: uuid.UUID, name: str) -> uuid.UUID:
    aid = uuid.uuid4()
    admin.execute(
        "INSERT INTO agents (workspace_id, id, name) VALUES (%s, %s, %s)", (wid, aid, name)
    )
    return aid


def test_no_workspace_set_returns_no_rows(
    admin_dsn: str, admin: psycopg.Connection, two_workspaces: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, _ = two_workspaces
    seed_agent(admin, a, "alpha")
    with app_conn(admin_dsn) as conn:
        assert conn.execute("SELECT count(*) FROM agents").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM workspaces").fetchone() == (0,)


def test_workspace_sees_only_its_own_rows(
    admin_dsn: str, admin: psycopg.Connection, two_workspaces: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, b = two_workspaces
    seed_agent(admin, a, "alpha")
    seed_agent(admin, b, "bravo")
    with app_conn(admin_dsn) as conn:
        use_workspace(conn, a)
        assert conn.execute("SELECT name FROM agents").fetchall() == [("alpha",)]
        assert conn.execute("SELECT name FROM workspaces").fetchall() == [("A",)]


def test_setting_is_transaction_local_and_does_not_leak(
    admin_dsn: str, admin: psycopg.Connection, two_workspaces: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, _ = two_workspaces
    seed_agent(admin, a, "alpha")
    with app_conn(admin_dsn) as conn:
        use_workspace(conn, a)
        assert conn.execute("SELECT count(*) FROM agents").fetchone() == (1,)
        conn.commit()
        assert conn.execute("SELECT count(*) FROM agents").fetchone() == (0,)


def test_cannot_insert_into_another_workspace(
    admin_dsn: str, two_workspaces: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, b = two_workspaces
    with app_conn(admin_dsn) as conn:
        use_workspace(conn, a)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("INSERT INTO agents (workspace_id, name) VALUES (%s, 'evil')", (b,))


def test_cannot_update_or_delete_other_workspace_rows(
    admin_dsn: str, admin: psycopg.Connection, two_workspaces: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, b = two_workspaces
    victim = seed_agent(admin, b, "bravo")
    with app_conn(admin_dsn) as conn:
        use_workspace(conn, a)
        assert conn.execute("UPDATE agents SET name='x' WHERE id=%s", (victim,)).rowcount == 0
        assert conn.execute("DELETE FROM agents WHERE id=%s", (victim,)).rowcount == 0
    assert admin.execute("SELECT name FROM agents WHERE id=%s", (victim,)).fetchone() == ("bravo",)


def test_cannot_move_row_to_another_workspace(
    admin_dsn: str, admin: psycopg.Connection, two_workspaces: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, b = two_workspaces
    mine = seed_agent(admin, a, "alpha")
    with app_conn(admin_dsn) as conn:
        use_workspace(conn, a)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE agents SET workspace_id=%s WHERE id=%s", (b, mine))


def test_cross_tenant_foreign_key_is_rejected(
    admin: psycopg.Connection, two_workspaces: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """Even a superuser cannot attach workspace A's membership to workspace B's role."""
    a, b = two_workspaces
    role_b, user = uuid.uuid4(), uuid.uuid4()
    admin.execute("INSERT INTO roles (workspace_id, id, name) VALUES (%s, %s, 'R')", (b, role_b))
    admin.execute("INSERT INTO users (id, email) VALUES (%s, 'u@example.com')", (user,))
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        admin.execute(
            "INSERT INTO memberships (workspace_id, user_id, role_id) VALUES (%s, %s, %s)",
            (a, user, role_b),
        )


def test_audit_log_is_append_only_for_app_role(
    admin_dsn: str, two_workspaces: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, _ = two_workspaces
    with app_conn(admin_dsn) as conn:
        use_workspace(conn, a)
        conn.execute(
            "INSERT INTO audit_log (workspace_id, action, target_type) VALUES (%s, 'x', 'y')", (a,)
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE audit_log SET action='tampered'")
        conn.rollback()
        use_workspace(conn, a)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM audit_log")


def test_app_role_cannot_write_users_or_bypass_rls(admin_dsn: str) -> None:
    with app_conn(admin_dsn) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("INSERT INTO users (email) VALUES ('x@example.com')")
        conn.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("ALTER TABLE agents DISABLE ROW LEVEL SECURITY")
        conn.rollback()
        row = conn.execute(
            "SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname='voizy_app'"
        ).fetchone()
        assert row == (False, False)


def test_published_agent_version_is_immutable(
    admin: psycopg.Connection, two_workspaces: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, _ = two_workspaces
    aid = seed_agent(admin, a, "alpha")
    vid = uuid.uuid4()
    admin.execute(
        "INSERT INTO agent_versions (workspace_id, id, agent_id, version, config, is_published) "
        "VALUES (%s, %s, %s, 1, %s::jsonb, true)",
        (a, vid, aid, json.dumps({"name": "v1"})),
    )
    with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        admin.execute("UPDATE agent_versions SET config='{}'::jsonb WHERE id=%s", (vid,))
    with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        admin.execute("UPDATE agent_versions SET is_published=false WHERE id=%s", (vid,))
