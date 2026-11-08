"""Where a call gets its AgentConfig from.

Job metadata is set server-side when a call is dispatched, so it is trusted to name a workspace
and agent. It is still parsed strictly: only two UUIDs are accepted, nothing else.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from psycopg_pool import AsyncConnectionPool
from pydantic import ValidationError
from voizy_core.db.pool import workspace_tx
from voizy_core.domain.agent_config import AgentConfig


class ConfigNotFoundError(Exception):
    pass


def parse_job_metadata(raw: str | None) -> tuple[uuid.UUID, uuid.UUID] | None:
    """Return (workspace_id, agent_id) or None when there is no usable dispatch metadata."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) != {"workspace_id", "agent_id"}:
            return None
        return uuid.UUID(str(data["workspace_id"])), uuid.UUID(str(data["agent_id"]))
    except (ValueError, TypeError):
        return None


async def load_published_config(
    pool: AsyncConnectionPool, workspace_id: uuid.UUID, agent_id: uuid.UUID
) -> AgentConfig:
    async with workspace_tx(pool, workspace_id) as conn:
        cur = await conn.execute(
            "SELECT v.config FROM agents a "
            "JOIN agent_versions v ON v.workspace_id = a.workspace_id "
            "AND v.id = a.published_version_id "
            "WHERE a.id = %s AND a.archived_at IS NULL",
            (agent_id,),
        )
        row = await cur.fetchone()
    if row is None:
        raise ConfigNotFoundError("agent not found, archived, or has no published version")
    return AgentConfig.model_validate(row[0])


def load_dev_config(path: str | Path) -> AgentConfig:
    """Local development only: read an AgentConfig from a JSON file."""
    try:
        return AgentConfig.model_validate_json(Path(path).read_text())
    except (OSError, ValidationError) as exc:
        raise ConfigNotFoundError(f"cannot load dev config {path}: {exc}") from exc
