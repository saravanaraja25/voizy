"""Create a workspace with seeded roles and a first superadmin API key.

Runs with a privileged DSN (not the app role). It sets the workspace context like any other
transaction, so it also works for a non-superuser table owner subject to FORCE ROW LEVEL SECURITY.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from psycopg import AsyncConnection

from voizy_core.domain.permissions import ALL_PERMISSIONS, SEED_ROLES
from voizy_core.security.apikeys import generate_api_key


@dataclass(frozen=True)
class BootstrapResult:
    workspace_id: uuid.UUID
    api_key_id: uuid.UUID
    token: str  # shown once


@dataclass(frozen=True)
class NewWorkspace:
    id: uuid.UUID
    role_ids: dict[str, uuid.UUID]


async def create_workspace_with_roles(conn: AsyncConnection, name: str) -> NewWorkspace:
    """Insert a workspace and the seeded roles. The caller owns the surrounding transaction."""
    workspace_id = uuid.uuid4()
    await conn.execute("SELECT set_config('app.workspace_id', %s, true)", (str(workspace_id),))
    await conn.execute("INSERT INTO workspaces (id, name) VALUES (%s, %s)", (workspace_id, name))
    role_ids: dict[str, uuid.UUID] = {}
    for role in SEED_ROLES:
        cur = await conn.execute(
            "INSERT INTO roles (workspace_id, name, is_system, is_locked) "
            "VALUES (%s, %s, true, %s) RETURNING id",
            (workspace_id, role.name, role.is_locked),
        )
        row = await cur.fetchone()
        if row is None:
            raise RuntimeError("role insert returned no row")
        role_ids[role.name] = row[0]
        for perm in sorted(role.permissions):
            await conn.execute(
                "INSERT INTO role_permissions (workspace_id, role_id, permission) "
                "VALUES (%s, %s, %s)",
                (workspace_id, row[0], perm.value),
            )
    return NewWorkspace(workspace_id, role_ids)


async def bootstrap_workspace(
    conn: AsyncConnection, name: str, *, key_name: str = "bootstrap"
) -> BootstrapResult:
    key = generate_api_key()
    async with conn.transaction():
        ws = await create_workspace_with_roles(conn, name)
        workspace_id = ws.id
        cur = await conn.execute(
            "INSERT INTO api_keys (workspace_id, name, prefix, key_hash, permissions) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (workspace_id, key_name, key.prefix, key.key_hash, sorted(ALL_PERMISSIONS)),
        )
        key_row = await cur.fetchone()
        if key_row is None:
            raise RuntimeError("api key insert returned no row")
        await conn.execute(
            "INSERT INTO audit_log (workspace_id, action, target_type, target_id) "
            "VALUES (%s, 'workspace.bootstrap', 'workspace', %s)",
            (workspace_id, str(workspace_id)),
        )
    return BootstrapResult(workspace_id, key_row[0], key.token)
