"""API-key authentication: resolve a bearer token to a workspace-scoped principal."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from psycopg import AsyncConnection

from voizy_core.domain.permissions import Permission
from voizy_core.security.apikeys import TOKEN_RE, hash_token


@dataclass(frozen=True)
class Principal:
    workspace_id: uuid.UUID
    api_key_id: uuid.UUID
    permissions: frozenset[Permission]


async def authenticate_api_key(conn: AsyncConnection, token: str) -> Principal | None:
    """Resolve a bearer token to a principal, or None. Never distinguishes failure reasons."""
    if not TOKEN_RE.match(token):
        return None
    async with conn.transaction():
        await conn.execute(
            "SELECT set_config('app.api_key_hash', %s, true)", (hash_token(token).hex(),)
        )
        cur = await conn.execute(
            "SELECT workspace_id, id, permissions FROM api_keys "
            "WHERE key_hash = decode(%s, 'hex') AND revoked_at IS NULL "
            "AND (expires_at IS NULL OR expires_at > now())",
            (hash_token(token).hex(),),
        )
        row = await cur.fetchone()
    if row is None:
        return None
    workspace_id, key_id, raw_perms = row
    perms: set[Permission] = set()
    for value in raw_perms:
        try:
            perms.add(Permission(value))
        except ValueError:
            continue  # a stored permission we no longer define grants nothing
    return Principal(workspace_id, key_id, frozenset(perms))
