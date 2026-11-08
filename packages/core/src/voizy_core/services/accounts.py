"""Human accounts: first-run setup, login, sessions, invites and members.

Every function runs inside one transaction and declares its context (workspace, user, or the
secret it was handed) with transaction-local settings, so row-level security decides what is
visible. Nothing here can see another workspace's rows or another user's account.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import secrets
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from psycopg import AsyncConnection
from psycopg.pq import TransactionStatus

from voizy_core.domain.permissions import SUPERADMIN_ROLE_NAME, Permission
from voizy_core.security.authz import RoleView
from voizy_core.services.auth import Principal
from voizy_core.services.bootstrap import create_workspace_with_roles

SESSION_ABSOLUTE_TTL = dt.timedelta(days=14)
SESSION_IDLE_TTL = dt.timedelta(days=3)
INVITE_TTL = dt.timedelta(days=7)
_TOUCH_AFTER = dt.timedelta(minutes=5)

SESSION_TOKEN_RE = re.compile(r"^vzs_[A-Za-z0-9_-]{43}$")
INVITE_TOKEN_RE = re.compile(r"^vzi_[A-Za-z0-9_-]{43}$")


@asynccontextmanager
async def _tx(conn: AsyncConnection) -> AsyncIterator[None]:
    """A real top-level transaction, or an error.

    Inside an already-open transaction, conn.transaction() would only be a savepoint: nothing
    would commit, and the transaction-local security context (app.user_id, app.workspace_id, ...)
    would leak into whatever the caller runs next. So refuse instead of silently degrading.
    """
    if conn.info.transaction_status != TransactionStatus.IDLE:
        raise RuntimeError("accounts functions need an idle connection (commit or roll back first)")
    async with conn.transaction():
        yield


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def _set(conn: AsyncConnection, name: str, value: str) -> None:
    await conn.execute("SELECT set_config(%s, %s, true)", (name, value))


def _perms(raw: list[str]) -> frozenset[Permission]:
    out: set[Permission] = set()
    for value in raw:
        try:
            out.add(Permission(value))
        except ValueError:
            continue  # a permission we no longer define grants nothing
    return frozenset(out)


# ---- first-run setup -------------------------------------------------------------------------


async def setup_needed(conn: AsyncConnection) -> bool:
    async with _tx(conn):
        cur = await conn.execute("SELECT setup_completed_at IS NULL FROM instance_settings")
        row = await cur.fetchone()
    return bool(row and row[0])


@dataclass(frozen=True)
class SetupResult:
    workspace_id: uuid.UUID
    user_id: uuid.UUID


async def complete_setup(
    conn: AsyncConnection,
    *,
    workspace_name: str,
    email: str,
    display_name: str,
    password_hash: str,
) -> SetupResult | None:
    """Create the first workspace and its superadmin. Returns None if setup already happened.

    The claim is a single atomic UPDATE, so of two simultaneous attempts exactly one proceeds.
    """
    email = normalize_email(email)
    async with _tx(conn):
        cur = await conn.execute(
            "UPDATE instance_settings SET setup_completed_at = now() "
            "WHERE setup_completed_at IS NULL RETURNING true"
        )
        if await cur.fetchone() is None:
            return None
        ws = await create_workspace_with_roles(conn, workspace_name)
        user_id = uuid.uuid4()
        await _set(conn, "app.creating_email", email)
        await _set(conn, "app.user_id", str(user_id))
        await conn.execute(
            "INSERT INTO users (id, email, display_name, password_hash) VALUES (%s, %s, %s, %s)",
            (user_id, email, display_name, password_hash),
        )
        await conn.execute(
            "INSERT INTO memberships (workspace_id, user_id, role_id) VALUES (%s, %s, %s)",
            (ws.id, user_id, ws.role_ids[SUPERADMIN_ROLE_NAME]),
        )
        await conn.execute(
            "INSERT INTO audit_log (workspace_id, actor_user_id, action, target_type, target_id) "
            "VALUES (%s, %s, 'workspace.setup', 'workspace', %s)",
            (ws.id, user_id, str(ws.id)),
        )
    return SetupResult(ws.id, user_id)


# ---- login and sessions ----------------------------------------------------------------------


@dataclass(frozen=True)
class UserAccount:
    id: uuid.UUID
    email: str
    display_name: str
    password_hash: str | None
    is_active: bool


async def find_user_for_login(conn: AsyncConnection, email: str) -> UserAccount | None:
    async with _tx(conn):
        await _set(conn, "app.login_email", normalize_email(email))
        cur = await conn.execute(
            "SELECT id, email, display_name, password_hash, is_active FROM users "
            "WHERE lower(email) = %s",
            (normalize_email(email),),
        )
        row = await cur.fetchone()
    return UserAccount(*row) if row else None


async def record_login(
    conn: AsyncConnection, user_id: uuid.UUID, *, new_password_hash: str | None = None
) -> None:
    async with _tx(conn):
        await _set(conn, "app.user_id", str(user_id))
        await conn.execute(
            "UPDATE users SET last_login_at = now(), "
            "password_hash = coalesce(%s, password_hash) WHERE id = %s",
            (new_password_hash, user_id),
        )


@dataclass(frozen=True)
class MembershipInfo:
    workspace_id: uuid.UUID
    role_id: uuid.UUID


async def memberships_of(conn: AsyncConnection, user_id: uuid.UUID) -> list[MembershipInfo]:
    async with _tx(conn):
        await _set(conn, "app.user_id", str(user_id))
        cur = await conn.execute(
            "SELECT workspace_id, role_id FROM memberships WHERE user_id = %s ORDER BY created_at",
            (user_id,),
        )
        return [MembershipInfo(*r) for r in await cur.fetchall()]


@dataclass(frozen=True)
class NewSession:
    token: str  # the cookie value; shown once, only its hash is stored
    csrf_token: str
    expires_at: dt.datetime


async def create_session(
    conn: AsyncConnection, user_id: uuid.UUID, workspace_id: uuid.UUID
) -> NewSession:
    token = "vzs_" + secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    expires = dt.datetime.now(dt.UTC) + SESSION_ABSOLUTE_TTL
    async with _tx(conn):
        await _set(conn, "app.user_id", str(user_id))
        await conn.execute(
            "INSERT INTO sessions (token_hash, user_id, workspace_id, csrf_token, expires_at) "
            "VALUES (decode(%s, 'hex'), %s, %s, %s, %s)",
            (_hash(token), user_id, workspace_id, csrf, expires),
        )
    return NewSession(token, csrf, expires)


async def resolve_session(conn: AsyncConnection, token: str) -> Principal | None:
    """Resolve a session cookie to a principal, or None. Never says why it failed."""
    if not SESSION_TOKEN_RE.match(token):
        return None
    now = dt.datetime.now(dt.UTC)
    async with _tx(conn):
        await _set(conn, "app.session_hash", _hash(token))
        cur = await conn.execute(
            "SELECT user_id, workspace_id, csrf_token, expires_at, last_seen_at FROM sessions "
            "WHERE token_hash = decode(%s, 'hex')",
            (_hash(token),),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        user_id, workspace_id, csrf, expires_at, last_seen = row
        if expires_at <= now or now - last_seen > SESSION_IDLE_TTL:
            await conn.execute(
                "DELETE FROM sessions WHERE token_hash = decode(%s, 'hex')", (_hash(token),)
            )
            return None
        await _set(conn, "app.user_id", str(user_id))
        await _set(conn, "app.workspace_id", str(workspace_id))
        cur = await conn.execute("SELECT is_active FROM users WHERE id = %s", (user_id,))
        user = await cur.fetchone()
        cur = await conn.execute(
            "SELECT coalesce(array_agg(rp.permission), '{}') FROM memberships m "
            "JOIN role_permissions rp ON rp.workspace_id = m.workspace_id "
            "AND rp.role_id = m.role_id "
            "WHERE m.user_id = %s AND m.workspace_id = %s",
            (user_id, workspace_id),
        )
        perm_row = await cur.fetchone()
        if user is None or not user[0] or perm_row is None:
            return None
        if now - last_seen > _TOUCH_AFTER:
            await conn.execute(
                "UPDATE sessions SET last_seen_at = now() WHERE token_hash = decode(%s, 'hex')",
                (_hash(token),),
            )
    return Principal(workspace_id, _perms(perm_row[0]), user_id=user_id, csrf_token=csrf)


async def destroy_session(conn: AsyncConnection, token: str) -> None:
    async with _tx(conn):
        await _set(conn, "app.session_hash", _hash(token))
        await conn.execute(
            "DELETE FROM sessions WHERE token_hash = decode(%s, 'hex')", (_hash(token),)
        )


async def destroy_user_sessions(
    conn: AsyncConnection, user_id: uuid.UUID, *, except_token: str | None = None
) -> None:
    async with _tx(conn):
        await _set(conn, "app.user_id", str(user_id))
        if except_token:
            await conn.execute(
                "DELETE FROM sessions WHERE user_id = %s AND token_hash <> decode(%s, 'hex')",
                (user_id, _hash(except_token)),
            )
        else:
            await conn.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))


async def set_password(conn: AsyncConnection, user_id: uuid.UUID, password_hash: str) -> None:
    async with _tx(conn):
        await _set(conn, "app.user_id", str(user_id))
        await conn.execute(
            "UPDATE users SET password_hash = %s WHERE id = %s", (password_hash, user_id)
        )


@dataclass(frozen=True)
class WhoAmI:
    user_id: uuid.UUID
    email: str
    display_name: str
    workspace_name: str


async def who_am_i(conn: AsyncConnection, p: Principal) -> WhoAmI | None:
    if p.user_id is None:
        return None
    async with _tx(conn):
        await _set(conn, "app.user_id", str(p.user_id))
        await _set(conn, "app.workspace_id", str(p.workspace_id))
        cur = await conn.execute(
            "SELECT u.id, u.email, u.display_name, w.name FROM users u, workspaces w "
            "WHERE u.id = %s AND w.id = %s",
            (p.user_id, p.workspace_id),
        )
        row = await cur.fetchone()
    return WhoAmI(*row) if row else None


# ---- invites ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class NewInvite:
    id: uuid.UUID
    token: str  # appears once, inside the link
    expires_at: dt.datetime


async def create_invite(
    conn: AsyncConnection, p: Principal, *, email: str, role_id: uuid.UUID
) -> NewInvite:
    token = "vzi_" + secrets.token_urlsafe(32)
    expires = dt.datetime.now(dt.UTC) + INVITE_TTL
    async with _tx(conn):
        await _set(conn, "app.workspace_id", str(p.workspace_id))
        cur = await conn.execute(
            "INSERT INTO invites "
            "(workspace_id, email, role_id, token_hash, invited_by, expires_at) "
            "VALUES (%s, %s, %s, decode(%s, 'hex'), %s, %s) RETURNING id",
            (p.workspace_id, normalize_email(email), role_id, _hash(token), p.user_id, expires),
        )
        row = await cur.fetchone()
        if row is None:
            raise RuntimeError("invite insert returned no row")
    return NewInvite(row[0], token, expires)


@dataclass(frozen=True)
class InviteInfo:
    workspace_id: uuid.UUID
    workspace_name: str
    email: str
    role_name: str
    expires_at: dt.datetime


async def peek_invite(conn: AsyncConnection, token: str) -> InviteInfo | None:
    """What a link recipient may see before accepting. None for unknown/expired/used links."""
    if not INVITE_TOKEN_RE.match(token):
        return None
    async with _tx(conn):
        await _set(conn, "app.invite_hash", _hash(token))
        cur = await conn.execute(
            "SELECT workspace_id, email, role_id, expires_at FROM invites "
            "WHERE token_hash = decode(%s, 'hex') AND accepted_at IS NULL AND revoked_at IS NULL "
            "AND expires_at > now()",
            (_hash(token),),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        workspace_id, email, role_id, expires_at = row
        await _set(conn, "app.workspace_id", str(workspace_id))
        cur = await conn.execute(
            "SELECT w.name, r.name FROM workspaces w, roles r WHERE w.id = %s AND r.id = %s",
            (workspace_id, role_id),
        )
        names = await cur.fetchone()
    if names is None:
        return None
    return InviteInfo(workspace_id, names[0], email, names[1], expires_at)


class AcceptError(Exception):
    """The invite cannot be accepted; the message is safe to show."""


async def accept_invite(
    conn: AsyncConnection, token: str, *, display_name: str, password_hash: str
) -> uuid.UUID:
    """Create the account and membership for a valid invite. Returns the new user's id."""
    if not INVITE_TOKEN_RE.match(token):
        raise AcceptError("This invitation link is not valid.")
    async with _tx(conn):
        await _set(conn, "app.invite_hash", _hash(token))
        # Row lock: two simultaneous accepts of one link cannot both succeed.
        cur = await conn.execute(
            "SELECT workspace_id, id, email, role_id FROM invites "
            "WHERE token_hash = decode(%s, 'hex') AND accepted_at IS NULL AND revoked_at IS NULL "
            "AND expires_at > now() FOR UPDATE",
            (_hash(token),),
        )
        row = await cur.fetchone()
        if row is None:
            raise AcceptError("This invitation link is invalid, expired, or already used.")
        workspace_id, invite_id, email, role_id = row
        await _set(conn, "app.workspace_id", str(workspace_id))
        await _set(conn, "app.login_email", email)
        cur = await conn.execute("SELECT 1 FROM users WHERE lower(email) = %s", (email,))
        if await cur.fetchone() is not None:
            raise AcceptError(
                "An account with this email already exists. Sign in instead and ask an admin "
                "to add you to the workspace."
            )
        user_id = uuid.uuid4()
        await _set(conn, "app.creating_email", email)
        await _set(conn, "app.user_id", str(user_id))
        await conn.execute(
            "INSERT INTO users (id, email, display_name, password_hash) VALUES (%s, %s, %s, %s)",
            (user_id, email, display_name, password_hash),
        )
        await conn.execute(
            "INSERT INTO memberships (workspace_id, user_id, role_id) VALUES (%s, %s, %s)",
            (workspace_id, user_id, role_id),
        )
        await conn.execute(
            "UPDATE invites SET accepted_at = now() WHERE workspace_id = %s AND id = %s",
            (workspace_id, invite_id),
        )
        await conn.execute(
            "INSERT INTO audit_log (workspace_id, actor_user_id, action, target_type, target_id) "
            "VALUES (%s, %s, 'invite.accept', 'user', %s)",
            (workspace_id, user_id, str(user_id)),
        )
    return user_id


# ---- members ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Member:
    user_id: uuid.UUID
    email: str
    display_name: str
    role_id: uuid.UUID
    role_name: str
    joined_at: dt.datetime
    last_login_at: dt.datetime | None


async def list_members(conn: AsyncConnection, workspace_id: uuid.UUID) -> list[Member]:
    async with _tx(conn):
        await _set(conn, "app.workspace_id", str(workspace_id))
        cur = await conn.execute(
            "SELECT u.id, u.email, u.display_name, r.id, r.name, m.created_at, u.last_login_at "
            "FROM memberships m JOIN users u ON u.id = m.user_id "
            "JOIN roles r ON r.workspace_id = m.workspace_id AND r.id = m.role_id "
            "ORDER BY m.created_at"
        )
        return [Member(*r) for r in await cur.fetchall()]


async def role_views_by_user(conn: AsyncConnection, workspace_id: uuid.UUID) -> dict[str, RoleView]:
    """Each member's current role with its permissions (for escalation and last-owner rules)."""
    async with _tx(conn):
        await _set(conn, "app.workspace_id", str(workspace_id))
        cur = await conn.execute(
            "SELECT m.user_id, r.id, r.name, r.is_locked, "
            "coalesce(array_agg(rp.permission) FILTER (WHERE rp.permission IS NOT NULL), '{}') "
            "FROM memberships m JOIN roles r "
            "ON r.workspace_id = m.workspace_id AND r.id = m.role_id "
            "LEFT JOIN role_permissions rp "
            "ON rp.workspace_id = r.workspace_id AND rp.role_id = r.id "
            "GROUP BY m.user_id, r.id, r.name, r.is_locked"
        )
        return {
            str(uid): RoleView(str(rid), name, _perms(perms), locked)
            for uid, rid, name, locked, perms in await cur.fetchall()
        }


async def role_view(
    conn: AsyncConnection, workspace_id: uuid.UUID, role_id: uuid.UUID
) -> RoleView | None:
    async with _tx(conn):
        await _set(conn, "app.workspace_id", str(workspace_id))
        cur = await conn.execute(
            "SELECT r.id, r.name, r.is_locked, "
            "coalesce(array_agg(rp.permission) FILTER (WHERE rp.permission IS NOT NULL), '{}') "
            "FROM roles r LEFT JOIN role_permissions rp "
            "ON rp.workspace_id = r.workspace_id AND rp.role_id = r.id "
            "WHERE r.id = %s GROUP BY r.workspace_id, r.id",
            (role_id,),
        )
        row = await cur.fetchone()
    return RoleView(str(row[0]), row[1], _perms(row[3]), row[2]) if row else None
