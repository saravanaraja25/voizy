"""Where a call gets its AgentConfig from.

Job metadata is set server-side when a call is dispatched, so it is trusted to name a workspace
and agent. It is still parsed strictly: only two UUIDs are accepted, nothing else.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from psycopg_pool import AsyncConnectionPool
from pydantic import ValidationError
from voizy_core.db.pool import workspace_tx
from voizy_core.domain.agent_config import AgentConfig
from voizy_core.domain.dispatch import DispatchTarget


class ConfigNotFoundError(Exception):
    pass


async def load_published_config(
    pool: AsyncConnectionPool, workspace_id: uuid.UUID, agent_id: uuid.UUID
) -> AgentConfig:
    return await load_config(pool, DispatchTarget(workspace_id, agent_id))


async def load_config(pool: AsyncConnectionPool, target: DispatchTarget) -> AgentConfig:
    """The published version, or the exact version named in a (server-signed) test dispatch."""
    return (await load_config_with_version(pool, target))[0]


async def load_config_with_version(
    pool: AsyncConnectionPool, target: DispatchTarget
) -> tuple[AgentConfig, int]:
    """Like `load_config`, also returning the version number that was resolved."""
    async with workspace_tx(pool, target.workspace_id) as conn:
        if target.version is None:
            cur = await conn.execute(
                "SELECT v.config, v.version FROM agents a "
                "JOIN agent_versions v ON v.workspace_id = a.workspace_id "
                "AND v.id = a.published_version_id "
                "WHERE a.id = %s AND a.archived_at IS NULL",
                (target.agent_id,),
            )
        else:
            cur = await conn.execute(
                "SELECT v.config, v.version FROM agents a "
                "JOIN agent_versions v ON v.workspace_id = a.workspace_id AND v.agent_id = a.id "
                "WHERE a.id = %s AND v.version = %s AND a.archived_at IS NULL",
                (target.agent_id, target.version),
            )
        row = await cur.fetchone()
    if row is None:
        raise ConfigNotFoundError("agent or version not found, archived, or not published")
    return AgentConfig.model_validate(row[0]), int(row[1])


def load_dev_config(path: str | Path) -> AgentConfig:
    """Local development only: read an AgentConfig from a JSON file."""
    try:
        return AgentConfig.model_validate_json(Path(path).read_text())
    except (OSError, ValidationError) as exc:
        raise ConfigNotFoundError(f"cannot load dev config {path}: {exc}") from exc
