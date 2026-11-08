"""The workspace's encrypted secret store: integration keys and tool credentials.

Values are AES-GCM encrypted with the workspace and secret name bound in, so a ciphertext copied
to another workspace or name will not decrypt. The API never returns a value: only a masked hint.
"""

from __future__ import annotations

import datetime as dt
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from psycopg import AsyncConnection

from voizy_core.db.tx import owned_tx, set_local
from voizy_core.domain.integrations import RESERVED_SECRET_NAMES
from voizy_core.security.hosts import valid_host_pattern
from voizy_core.security.secretbox import SecretBox, SecretError

Kind = Literal["integration", "tool"]
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
MAX_VALUE = 4096


class SecretStoreError(ValueError):
    """The request is invalid; the message is safe to show."""


@dataclass(frozen=True)
class SecretInfo:
    name: str
    kind: str
    description: str
    allowed_hosts: tuple[str, ...]
    hint: str
    updated_at: dt.datetime


@dataclass(frozen=True)
class ResolvedSecret:
    value: str
    allowed_hosts: tuple[str, ...]


def hint_for(value: str) -> str:
    """Enough to recognise a key, never enough to use it."""
    return "••••" + value[-4:] if len(value) >= 12 else "••••"


def _validate_value(value: str) -> None:
    if not value or len(value) > MAX_VALUE:
        raise SecretStoreError(f"A value of 1-{MAX_VALUE} characters is required.")
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise SecretStoreError("The value must not contain control characters or line breaks.")


def validate_hosts(hosts: Iterable[str]) -> tuple[str, ...]:
    cleaned = tuple(dict.fromkeys(h.strip().lower() for h in hosts if h.strip()))
    if not cleaned:
        raise SecretStoreError("List at least one host this credential may be sent to.")
    if len(cleaned) > 10:
        raise SecretStoreError("At most 10 hosts.")
    bad = [h for h in cleaned if not valid_host_pattern(h)]
    if bad:
        raise SecretStoreError(f"Not a valid host: {bad[0]}. Use api.example.com or *.example.com.")
    return cleaned


def _check_name(name: str, kind: Kind) -> None:
    if not NAME_RE.match(name):
        raise SecretStoreError("Names use lowercase letters, digits and underscores.")
    reserved = name in RESERVED_SECRET_NAMES
    if kind == "tool" and reserved:
        raise SecretStoreError("That name is reserved for an integration.")
    if kind == "integration" and not reserved:
        raise SecretStoreError("Not an integration field.")


async def put_secret(
    conn: AsyncConnection,
    box: SecretBox,
    workspace_id: uuid.UUID,
    name: str,
    value: str,
    *,
    kind: Kind,
    allowed_hosts: Iterable[str] = (),
    description: str = "",
) -> None:
    _check_name(name, kind)
    _validate_value(value)
    hosts = validate_hosts(allowed_hosts) if kind == "tool" else ()
    ciphertext = box.encrypt(value, workspace_id=str(workspace_id), name=name)
    async with owned_tx(conn):
        await set_local(conn, "app.workspace_id", str(workspace_id))
        cur = await conn.execute(
            "INSERT INTO secrets (workspace_id, name, ciphertext, kind, allowed_hosts, "
            "description, hint) VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (workspace_id, name) DO UPDATE SET ciphertext = EXCLUDED.ciphertext, "
            "allowed_hosts = EXCLUDED.allowed_hosts, description = EXCLUDED.description, "
            "hint = EXCLUDED.hint, updated_at = now() WHERE secrets.kind = EXCLUDED.kind "
            "RETURNING name",
            (workspace_id, name, ciphertext, kind, list(hosts), description[:200], hint_for(value)),
        )
        if await cur.fetchone() is None:
            raise SecretStoreError("That name is already used for a different kind of secret.")


async def update_tool_secret_meta(
    conn: AsyncConnection,
    workspace_id: uuid.UUID,
    name: str,
    *,
    allowed_hosts: Iterable[str],
    description: str,
) -> bool:
    """Change where a tool credential may be sent without re-entering its value."""
    hosts = validate_hosts(allowed_hosts)
    async with owned_tx(conn):
        await set_local(conn, "app.workspace_id", str(workspace_id))
        cur = await conn.execute(
            "UPDATE secrets SET allowed_hosts = %s, description = %s, updated_at = now() "
            "WHERE name = %s AND kind = 'tool' RETURNING name",
            (list(hosts), description[:200], name),
        )
        return await cur.fetchone() is not None


async def list_secrets(
    conn: AsyncConnection, workspace_id: uuid.UUID, kind: Kind
) -> list[SecretInfo]:
    async with owned_tx(conn):
        await set_local(conn, "app.workspace_id", str(workspace_id))
        cur = await conn.execute(
            "SELECT name, kind, description, allowed_hosts, hint, updated_at FROM secrets "
            "WHERE kind = %s ORDER BY name",
            (kind,),
        )
        return [SecretInfo(r[0], r[1], r[2], tuple(r[3]), r[4], r[5]) for r in await cur.fetchall()]


async def get_secret(
    conn: AsyncConnection, box: SecretBox, workspace_id: uuid.UUID, name: str, *, kind: Kind
) -> ResolvedSecret | None:
    async with owned_tx(conn):
        await set_local(conn, "app.workspace_id", str(workspace_id))
        cur = await conn.execute(
            "SELECT ciphertext, allowed_hosts FROM secrets WHERE name = %s AND kind = %s",
            (name, kind),
        )
        row = await cur.fetchone()
    if row is None:
        return None
    try:
        value = box.decrypt(row[0], workspace_id=str(workspace_id), name=name)
    except SecretError:
        return None  # unreadable (wrong key, tampered): treat as not configured, never leak why
    return ResolvedSecret(value, tuple(row[1]))


async def get_integration_values(
    conn: AsyncConnection, box: SecretBox, workspace_id: uuid.UUID, names: Iterable[str]
) -> dict[str, str]:
    """Decrypted values for the given integration fields that are set and readable."""
    wanted = [n for n in names if n in RESERVED_SECRET_NAMES]
    async with owned_tx(conn):
        await set_local(conn, "app.workspace_id", str(workspace_id))
        cur = await conn.execute(
            "SELECT name, ciphertext FROM secrets WHERE kind = 'integration' AND name = ANY(%s)",
            (wanted,),
        )
        rows = await cur.fetchall()
    out: dict[str, str] = {}
    for name, ciphertext in rows:
        try:
            out[name] = box.decrypt(ciphertext, workspace_id=str(workspace_id), name=name)
        except SecretError:
            continue
    return out


async def delete_secret(
    conn: AsyncConnection, workspace_id: uuid.UUID, names: Iterable[str], *, kind: Kind
) -> int:
    async with owned_tx(conn):
        await set_local(conn, "app.workspace_id", str(workspace_id))
        cur = await conn.execute(
            "DELETE FROM secrets WHERE kind = %s AND name = ANY(%s)", (kind, list(names))
        )
        return cur.rowcount
