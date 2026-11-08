"""Credentials the worker resolves per workspace from the encrypted secret store."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

from psycopg_pool import AsyncConnectionPool
from voizy_core.domain.direct import ALL_DIRECT_KEY_NAMES
from voizy_core.security.secretbox import SecretBox, SecretError
from voizy_core.services import secrets_store as store
from voizy_core.services.secrets_store import ResolvedSecret

LIVEKIT_FIELDS = ("livekit_url", "livekit_api_key", "livekit_api_secret")


@dataclass(frozen=True)
class LiveKitCredentials:
    url: str
    api_key: str
    api_secret: str

    def __repr__(self) -> str:  # never print the secret
        return (
            f"LiveKitCredentials(url={self.url!r}, api_key={self.api_key!r}, api_secret=<redacted>)"
        )


def secret_box_from_env() -> SecretBox | None:
    raw = os.environ.get("VOIZY_SECRET_KEYS")
    if not raw:
        return None
    try:
        return SecretBox.from_env_value(raw)
    except SecretError:
        return None


class DbSecretResolver:
    """Looks up one workspace's tool credentials. Integration keys are not reachable from here."""

    def __init__(self, pool: AsyncConnectionPool, box: SecretBox, workspace_id: uuid.UUID) -> None:
        self._pool, self._box, self._workspace_id = pool, box, workspace_id

    async def __call__(self, name: str) -> ResolvedSecret | None:
        async with self._pool.connection() as conn:
            return await store.get_secret(conn, self._box, self._workspace_id, name, kind="tool")


async def load_livekit(
    pool: AsyncConnectionPool, box: SecretBox, workspace_id: uuid.UUID
) -> LiveKitCredentials | None:
    async with pool.connection() as conn:
        values = await store.get_integration_values(conn, box, workspace_id, LIVEKIT_FIELDS)
    if all(f in values for f in LIVEKIT_FIELDS):
        return LiveKitCredentials(
            values["livekit_url"], values["livekit_api_key"], values["livekit_api_secret"]
        )
    return None


async def load_direct_keys(
    pool: AsyncConnectionPool, box: SecretBox, workspace_id: uuid.UUID
) -> dict[str, str]:
    """The workspace's own provider keys, for components set to connect directly."""
    async with pool.connection() as conn:
        return await store.get_integration_values(conn, box, workspace_id, ALL_DIRECT_KEY_NAMES)


async def primary_workspace_livekit(
    pool: AsyncConnectionPool, box: SecretBox
) -> tuple[uuid.UUID, LiveKitCredentials] | None:
    """For start-up when no environment credentials exist: the deployment's primary workspace
    (recorded at first-run setup) owns the worker's LiveKit connection. One worker serves one
    LiveKit project, so this is deployment-wide; set the environment variables to override."""
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT primary_workspace_id FROM instance_settings")
        row = await cur.fetchone()
    if not row or row[0] is None:
        return None
    creds = await load_livekit(pool, box, row[0])
    return (row[0], creds) if creds else None


__all__ = [
    "DbSecretResolver",
    "LiveKitCredentials",
    "load_direct_keys",
    "load_livekit",
    "primary_workspace_livekit",
    "secret_box_from_env",
]
