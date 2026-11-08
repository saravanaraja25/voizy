from __future__ import annotations

import asyncio
import datetime as dt
import uuid

import psycopg
import pytest
from psycopg import AsyncConnection
from voizy_core.domain.permissions import ALL_PERMISSIONS, Permission
from voizy_core.security.passwords import hash_password
from voizy_core.services import accounts as acc

pytestmark = pytest.mark.asyncio
HASH = hash_password("correct horse battery staple")


async def do_setup(conn: AsyncConnection, email: str = "owner@example.com") -> acc.SetupResult:
    result = await acc.complete_setup(
        conn,
        workspace_name="Acme",
        email=email,
        display_name="Owner",
        password_hash=HASH,
        seed_templates=True,
    )
    assert result is not None
    return result


async def test_setup_creates_workspace_roles_superadmin_and_audit(
    app_aconn: AsyncConnection, admin: psycopg.Connection
) -> None:
    assert await acc.setup_needed(app_aconn) is True
    r = await do_setup(app_aconn, "Owner@Example.com")
    assert await acc.setup_needed(app_aconn) is False

    roles = admin.execute("SELECT name FROM roles WHERE workspace_id=%s", (r.workspace_id,))
    assert {n for (n,) in roles.fetchall()} == {
        "Superadmin",
        "Admin",
        "Builder",
        "Operator",
        "Analyst",
    }
    user = admin.execute(
        "SELECT email, password_hash FROM users WHERE id=%s", (r.user_id,)
    ).fetchone()
    assert user is not None and user[0] == "owner@example.com" and user[1].startswith("$argon2id$")
    role = admin.execute(
        "SELECT ro.name FROM memberships m JOIN roles ro ON ro.id = m.role_id WHERE m.user_id=%s",
        (r.user_id,),
    ).fetchone()
    assert role == ("Superadmin",)
    assert admin.execute("SELECT action FROM audit_log").fetchone() == ("workspace.setup",)


async def test_setup_cannot_run_twice(
    app_aconn: AsyncConnection, admin: psycopg.Connection
) -> None:
    await do_setup(app_aconn)
    again = await acc.complete_setup(
        app_aconn,
        workspace_name="Evil",
        email="evil@example.com",
        display_name="E",
        password_hash=HASH,
    )
    assert again is None
    assert admin.execute("SELECT count(*) FROM workspaces").fetchone() == (1,)
    assert admin.execute("SELECT count(*) FROM users").fetchone() == (1,)


async def test_simultaneous_setups_produce_exactly_one_winner(
    admin_dsn: str, admin: psycopg.Connection
) -> None:
    async def attempt(email: str) -> acc.SetupResult | None:
        async with await AsyncConnection.connect(admin_dsn) as conn:
            await conn.execute("SET ROLE voizy_app")
            await conn.commit()
            return await acc.complete_setup(
                conn, workspace_name="W", email=email, display_name="x", password_hash=HASH
            )

    results = await asyncio.gather(*[attempt(f"u{i}@example.com") for i in range(5)])
    assert sum(r is not None for r in results) == 1
    assert admin.execute("SELECT count(*) FROM workspaces").fetchone() == (1,)


async def test_login_lookup_is_case_insensitive_and_unknown_is_none(
    app_aconn: AsyncConnection,
) -> None:
    r = await do_setup(app_aconn)
    found = await acc.find_user_for_login(app_aconn, "  OWNER@example.COM ")
    assert found is not None and found.id == r.user_id and found.is_active
    assert await acc.find_user_for_login(app_aconn, "nobody@example.com") is None


async def test_record_login_updates_timestamp_and_optionally_rehashes(
    app_aconn: AsyncConnection, admin: psycopg.Connection
) -> None:
    r = await do_setup(app_aconn)
    await acc.record_login(app_aconn, r.user_id)
    row = admin.execute("SELECT last_login_at, password_hash FROM users").fetchone()
    assert row is not None and row[0] is not None and row[1] == HASH
    rehashed = "$argon2id$rehashed"
    await acc.record_login(app_aconn, r.user_id, new_password_hash=rehashed)
    assert admin.execute("SELECT password_hash FROM users").fetchone() == (rehashed,)


async def test_session_resolves_to_a_principal_with_the_roles_permissions(
    app_aconn: AsyncConnection,
) -> None:
    r = await do_setup(app_aconn)
    s = await acc.create_session(app_aconn, r.user_id, r.workspace_id)
    assert s.token.startswith("vzs_") and s.csrf_token and s.expires_at > dt.datetime.now(dt.UTC)
    p = await acc.resolve_session(app_aconn, s.token)
    assert p is not None and p.via_session
    assert (p.workspace_id, p.user_id, p.csrf_token) == (r.workspace_id, r.user_id, s.csrf_token)
    assert p.permissions == ALL_PERMISSIONS
    me = await acc.who_am_i(app_aconn, p)
    assert me is not None and me.workspace_name == "Acme" and me.email == "owner@example.com"


@pytest.mark.parametrize("token", ["", "garbage", "vzs_short", "' OR 1=1 --", "vzs_" + "A" * 43])
async def test_unknown_or_malformed_session_tokens_fail_closed(
    app_aconn: AsyncConnection, token: str
) -> None:
    await do_setup(app_aconn)
    assert await acc.resolve_session(app_aconn, token) is None


async def test_expired_idle_and_inactive_sessions_are_rejected(
    app_aconn: AsyncConnection, admin: psycopg.Connection
) -> None:
    r = await do_setup(app_aconn)
    expired = await acc.create_session(app_aconn, r.user_id, r.workspace_id)
    admin.execute("UPDATE sessions SET expires_at = now() - interval '1 second'")
    assert await acc.resolve_session(app_aconn, expired.token) is None
    assert admin.execute("SELECT count(*) FROM sessions").fetchone() == (0,)  # and cleaned up

    idle = await acc.create_session(app_aconn, r.user_id, r.workspace_id)
    admin.execute("UPDATE sessions SET last_seen_at = now() - interval '4 days'")
    assert await acc.resolve_session(app_aconn, idle.token) is None

    live = await acc.create_session(app_aconn, r.user_id, r.workspace_id)
    admin.execute("UPDATE users SET is_active = false")
    assert await acc.resolve_session(app_aconn, live.token) is None


async def test_destroying_sessions(app_aconn: AsyncConnection, admin: psycopg.Connection) -> None:
    r = await do_setup(app_aconn)
    a = await acc.create_session(app_aconn, r.user_id, r.workspace_id)
    b = await acc.create_session(app_aconn, r.user_id, r.workspace_id)
    await acc.destroy_session(app_aconn, a.token)
    assert await acc.resolve_session(app_aconn, a.token) is None
    assert await acc.resolve_session(app_aconn, b.token) is not None
    c = await acc.create_session(app_aconn, r.user_id, r.workspace_id)
    await acc.destroy_user_sessions(app_aconn, r.user_id, except_token=c.token)
    assert await acc.resolve_session(app_aconn, b.token) is None
    assert await acc.resolve_session(app_aconn, c.token) is not None


async def test_membership_removal_ends_the_session(
    app_aconn: AsyncConnection, admin: psycopg.Connection
) -> None:
    r = await do_setup(app_aconn)
    s = await acc.create_session(app_aconn, r.user_id, r.workspace_id)
    admin.execute("DELETE FROM memberships WHERE user_id = %s", (r.user_id,))
    assert await acc.resolve_session(app_aconn, s.token) is None


async def invite(
    conn: AsyncConnection, owner: acc.SetupResult, admin: psycopg.Connection, role: str = "Builder"
) -> acc.NewInvite:
    role_id = admin.execute(
        "SELECT id FROM roles WHERE workspace_id=%s AND name=%s", (owner.workspace_id, role)
    ).fetchone()
    assert role_id is not None
    principal = await acc.resolve_session(
        conn, (await acc.create_session(conn, owner.user_id, owner.workspace_id)).token
    )
    assert principal is not None
    return await acc.create_invite(conn, principal, email="New@Example.com", role_id=role_id[0])


async def test_invite_peek_then_accept_creates_member_with_the_invited_role(
    app_aconn: AsyncConnection, admin: psycopg.Connection
) -> None:
    owner = await do_setup(app_aconn)
    inv = await invite(app_aconn, owner, admin)
    info = await acc.peek_invite(app_aconn, inv.token)
    assert info is not None
    assert (info.workspace_name, info.email, info.role_name) == (
        "Acme",
        "new@example.com",
        "Builder",
    )

    new_id = await acc.accept_invite(
        app_aconn, inv.token, display_name="Newbie", password_hash=HASH
    )
    s = await acc.create_session(app_aconn, new_id, owner.workspace_id)
    p = await acc.resolve_session(app_aconn, s.token)
    assert p is not None and Permission.AGENTS_PUBLISH in p.permissions
    assert Permission.ROLES_MANAGE not in p.permissions  # a Builder is not an owner
    assert await acc.peek_invite(app_aconn, inv.token) is None  # now spent


async def test_an_invite_cannot_be_used_twice_even_concurrently(
    admin_dsn: str, app_aconn: AsyncConnection, admin: psycopg.Connection
) -> None:
    owner = await do_setup(app_aconn)
    inv = await invite(app_aconn, owner, admin)

    async def accept() -> str:
        async with await AsyncConnection.connect(admin_dsn) as c:
            await c.execute("SET ROLE voizy_app")
            await c.commit()
            try:
                await acc.accept_invite(c, inv.token, display_name="x", password_hash=HASH)
            except acc.AcceptError:
                return "rejected"
            return "ok"

    outcomes = await asyncio.gather(*[accept() for _ in range(4)])
    assert outcomes.count("ok") == 1
    assert admin.execute("SELECT count(*) FROM users").fetchone() == (2,)


async def test_expired_revoked_and_unknown_invites_are_rejected(
    app_aconn: AsyncConnection, admin: psycopg.Connection
) -> None:
    owner = await do_setup(app_aconn)
    inv = await invite(app_aconn, owner, admin)
    admin.execute("UPDATE invites SET expires_at = now() - interval '1 second'")
    assert await acc.peek_invite(app_aconn, inv.token) is None
    with pytest.raises(acc.AcceptError):
        await acc.accept_invite(app_aconn, inv.token, display_name="x", password_hash=HASH)

    admin.execute("UPDATE invites SET expires_at = now() + interval '1 day', revoked_at = now()")
    with pytest.raises(acc.AcceptError):
        await acc.accept_invite(app_aconn, inv.token, display_name="x", password_hash=HASH)
    for bad in ("", "nope", "vzi_" + "A" * 43):
        with pytest.raises(acc.AcceptError):
            await acc.accept_invite(app_aconn, bad, display_name="x", password_hash=HASH)


async def test_invite_for_an_existing_account_is_refused_with_guidance(
    app_aconn: AsyncConnection, admin: psycopg.Connection
) -> None:
    owner = await do_setup(app_aconn, "new@example.com")  # the invitee already has an account
    inv = await invite(app_aconn, owner, admin)
    with pytest.raises(acc.AcceptError, match="already exists"):
        await acc.accept_invite(app_aconn, inv.token, display_name="x", password_hash=HASH)


async def test_members_listing_and_role_views(
    app_aconn: AsyncConnection, admin: psycopg.Connection
) -> None:
    owner = await do_setup(app_aconn)
    inv = await invite(app_aconn, owner, admin)
    new_id = await acc.accept_invite(
        app_aconn, inv.token, display_name="Newbie", password_hash=HASH
    )

    members = await acc.list_members(app_aconn, owner.workspace_id)
    assert [(m.email, m.role_name) for m in members] == [
        ("owner@example.com", "Superadmin"),
        ("new@example.com", "Builder"),
    ]
    views = await acc.role_views_by_user(app_aconn, owner.workspace_id)
    assert views[str(owner.user_id)].is_superadmin and not views[str(new_id)].is_superadmin
    rv = await acc.role_view(app_aconn, owner.workspace_id, uuid.UUID(views[str(new_id)].id))
    assert rv is not None and rv.name == "Builder"
    assert await acc.role_view(app_aconn, owner.workspace_id, uuid.uuid4()) is None


async def test_refuses_to_run_inside_an_open_transaction_instead_of_leaking_context(
    app_aconn: AsyncConnection,
) -> None:
    await app_aconn.execute("SELECT 1")  # implicitly opens a transaction
    with pytest.raises(RuntimeError, match="idle connection"):
        await acc.find_user_for_login(app_aconn, "a@example.com")
    await app_aconn.rollback()
    assert await acc.find_user_for_login(app_aconn, "a@example.com") is None
