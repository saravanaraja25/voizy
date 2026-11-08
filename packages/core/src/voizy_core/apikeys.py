"""API keys: 256-bit random tokens, stored only as SHA-256, shown once at creation."""

from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from dataclasses import dataclass

from psycopg import AsyncConnection

from voizy_core.permissions import Permission

TOKEN_RE = re.compile(r"^vz_[A-Za-z0-9_-]{43}$")  # 32 random bytes, urlsafe base64, no padding


@dataclass(frozen=True)
class NewApiKey:
    token: str  # show to the user once; never persisted
    prefix: str  # safe to display, helps users identify a key
    key_hash: bytes


@dataclass(frozen=True)
class Principal:
    workspace_id: uuid.UUID
    api_key_id: uuid.UUID
    permissions: frozenset[Permission]


def generate_api_key() -> NewApiKey:
    token = "vz_" + secrets.token_urlsafe(32)
    return NewApiKey(token=token, prefix=token[:11], key_hash=hash_token(token))


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


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
