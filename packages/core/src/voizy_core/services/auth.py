"""Who is calling: an API key or a signed-in user, always scoped to one workspace."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from psycopg import AsyncConnection

from voizy_core.domain.permissions import Permission
from voizy_core.security.apikeys import TOKEN_RE, hash_token


@dataclass(frozen=True)
class Principal:
    workspace_id: uuid.UUID
    permissions: frozenset[Permission]
    api_key_id: uuid.UUID | None = None  # set when authenticated by API key
    user_id: uuid.UUID | None = None  # set when authenticated by session
    csrf_token: str | None = None  # session callers only; required on unsafe requests

    @property
    def via_session(self) -> bool:
        return self.user_id is not None


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
    return Principal(workspace_id, frozenset(perms), api_key_id=key_id)
