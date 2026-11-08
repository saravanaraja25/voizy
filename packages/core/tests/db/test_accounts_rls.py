"""Row-level security for accounts: users, sessions, invites, first-run setup."""

from __future__ import annotations

import uuid

import psycopg
import pytest
from voizy_core.testing import app_conn


def seed_user(admin: psycopg.Connection, email: str) -> uuid.UUID:
    uid = uuid.uuid4()
    admin.execute("INSERT INTO users (id, email) VALUES (%s, %s)", (uid, email))
    return uid


def seed_member(admin: psycopg.Connection, wid: uuid.UUID, uid: uuid.UUID) -> uuid.UUID:
    rid = uuid.uuid4()
    admin.execute("INSERT INTO roles (workspace_id, id, name) VALUES (%s, %s, 'R')", (wid, rid))
    admin.execute(
        "INSERT INTO memberships (workspace_id, user_id, role_id) VALUES (%s, %s, %s)",
        (wid, uid, rid),
    )
    return rid


def setting(conn: psycopg.Connection, name: str, value: str) -> None:
    conn.execute("SELECT set_config(%s, %s, true)", (name, value))


def test_users_are_invisible_without_a_context(
    admin_dsn: str, admin: psycopg.Connection, two_workspaces: tuple[uuid.UUID, uuid.UUID]
) -> None:
    seed_user(admin, "a@example.com")
    with app_conn(admin_dsn) as conn:
        assert conn.execute("SELECT count(*) FROM users").fetchone() == (0,)


def test_workspace_sees_only_its_own_members(
    admin_dsn: str, admin: psycopg.Connection, two_workspaces: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, b = two_workspaces
    ua, ub = seed_user(admin, "a@example.com"), seed_user(admin, "b@example.com")
    seed_member(admin, a, ua)
    seed_member(admin, b, ub)
    with app_conn(admin_dsn) as conn:
        setting(conn, "app.workspace_id", str(a))
        assert conn.execute("SELECT email FROM users").fetchall() == [("a@example.com",)]


def test_login_lookup_exposes_exactly_the_presented_email(
    admin_dsn: str, admin: psycopg.Connection, two_workspaces: tuple[uuid.UUID, uuid.UUID]
) -> None:
    seed_user(admin, "Alice@Example.com")
    seed_user(admin, "bob@example.com")
    with app_conn(admin_dsn) as conn:
        setting(conn, "app.login_email", "alice@example.com")
        assert conn.execute("SELECT count(*) FROM users").fetchone() == (1,)
        # Lookup grants no write path.
        assert conn.execute("UPDATE users SET display_name = 'x'").rowcount == 0


def test_user_can_update_only_allowed_columns_of_themself(
    admin_dsn: str, admin: psycopg.Connection, two_workspaces: tuple[uuid.UUID, uuid.UUID]
) -> None:
    me, other = seed_user(admin, "me@example.com"), seed_user(admin, "o@example.com")
    with app_conn(admin_dsn) as conn:
        setting(conn, "app.user_id", str(me))
        assert conn.execute("UPDATE users SET display_name = 'Me'").rowcount == 1
        with pytest.raises(psycopg.errors.InsufficientPrivilege):  # column-level grant
            conn.execute("UPDATE users SET is_platform_superadmin = true")
        conn.rollback()
        setting(conn, "app.user_id", str(me))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE users SET email = 'x@example.com'")
    assert admin.execute("SELECT display_name FROM users WHERE id=%s", (other,)).fetchone() == ("",)


def test_user_creation_is_limited_to_the_declared_email_and_safe_columns(
    admin_dsn: str, two_workspaces: tuple[uuid.UUID, uuid.UUID]
) -> None:
    with app_conn(admin_dsn) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):  # nothing declared
            conn.execute("INSERT INTO users (email) VALUES ('a@example.com')")
        conn.rollback()
        setting(conn, "app.creating_email", "a@example.com")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):  # different email
            conn.execute("INSERT INTO users (email) VALUES ('evil@example.com')")
        conn.rollback()
        setting(conn, "app.creating_email", "a@example.com")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):  # privilege flag not grantable
            conn.execute(
                "INSERT INTO users (email, is_platform_superadmin) VALUES ('a@example.com', true)"
            )
        conn.rollback()
        uid = uuid.uuid4()
        setting(conn, "app.creating_email", "a@example.com")
        setting(conn, "app.user_id", str(uid))
        conn.execute("INSERT INTO users (id, email) VALUES (%s, 'a@example.com')", (uid,))


def test_sessions_are_reachable_only_by_their_token_hash(
    admin_dsn: str, admin: psycopg.Connection, two_workspaces: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, _ = two_workspaces
    uid = seed_user(admin, "a@example.com")
    seed_member(admin, a, uid)
    admin.execute(
        "INSERT INTO sessions (token_hash, user_id, workspace_id, csrf_token, expires_at) "
        "VALUES (decode('aa', 'hex'), %s, %s, 'c', now() + interval '1 day')",
        (uid, a),
    )
    with app_conn(admin_dsn) as conn:
        assert conn.execute("SELECT count(*) FROM sessions").fetchone() == (0,)
        setting(conn, "app.session_hash", "bb")
        assert conn.execute("SELECT count(*) FROM sessions").fetchone() == (0,)
        setting(conn, "app.session_hash", "aa")
        assert conn.execute("SELECT count(*) FROM sessions").fetchone() == (1,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):  # only last_seen_at is writable
            conn.execute("UPDATE sessions SET expires_at = now() + interval '10 years'")


def test_removing_a_membership_ends_the_users_sessions(
    admin: psycopg.Connection, two_workspaces: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, _ = two_workspaces
    uid = seed_user(admin, "a@example.com")
    seed_member(admin, a, uid)
    admin.execute(
        "INSERT INTO sessions (token_hash, user_id, workspace_id, csrf_token, expires_at) "
        "VALUES (decode('aa', 'hex'), %s, %s, 'c', now() + interval '1 day')",
        (uid, a),
    )
    admin.execute("DELETE FROM memberships WHERE user_id = %s", (uid,))
    assert admin.execute("SELECT count(*) FROM sessions").fetchone() == (0,)


def test_invite_is_reachable_by_its_secret_and_isolated_by_workspace(
    admin_dsn: str, admin: psycopg.Connection, two_workspaces: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, b = two_workspaces
    role = uuid.uuid4()
    admin.execute("INSERT INTO roles (workspace_id, id, name) VALUES (%s, %s, 'R')", (a, role))
    admin.execute(
        "INSERT INTO invites (workspace_id, email, role_id, token_hash, expires_at) "
        "VALUES (%s, 'n@example.com', %s, decode('cc', 'hex'), now() + interval '1 day')",
        (a, role),
    )
    with app_conn(admin_dsn) as conn:
        setting(conn, "app.workspace_id", str(b))
        assert conn.execute("SELECT count(*) FROM invites").fetchone() == (0,)
        conn.rollback()
        setting(conn, "app.invite_hash", "dd")
        assert conn.execute("SELECT count(*) FROM invites").fetchone() == (0,)
        setting(conn, "app.invite_hash", "cc")
        assert conn.execute("SELECT count(*) FROM invites").fetchone() == (1,)


def test_one_pending_invite_per_email(
    admin: psycopg.Connection, two_workspaces: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, _ = two_workspaces
    role = uuid.uuid4()
    admin.execute("INSERT INTO roles (workspace_id, id, name) VALUES (%s, %s, 'R')", (a, role))
    sql = (
        "INSERT INTO invites (workspace_id, email, role_id, token_hash, expires_at) "
        "VALUES (%s, %s, %s, %s, now() + interval '1 day')"
    )
    admin.execute(sql, (a, "n@example.com", role, b"\x01"))
    with pytest.raises(psycopg.errors.UniqueViolation):
        admin.execute(sql, (a, "N@Example.com", role, b"\x02"))


def test_setup_can_be_claimed_once_and_never_reopened(
    admin_dsn: str, admin: psycopg.Connection
) -> None:
    admin.execute("UPDATE instance_settings SET setup_completed_at = NULL")
    with app_conn(admin_dsn) as conn:
        claim = (
            "UPDATE instance_settings SET setup_completed_at = now() "
            "WHERE setup_completed_at IS NULL"
        )
        assert conn.execute(claim).rowcount == 1
        assert conn.execute(claim).rowcount == 0  # a second claimant loses
        conn.commit()
        with pytest.raises(psycopg.errors.RaiseException, match="only be completed once"):
            conn.execute("UPDATE instance_settings SET setup_completed_at = NULL")
