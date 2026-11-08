from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from voizy_core.db.pool import workspace_tx
from voizy_core.domain.agent_config import AgentConfig
from voizy_core.domain.permissions import Permission
from voizy_core.services.auth import Principal

from voizy_api.schemas.agents import AgentCreate, AgentOut, VersionCreate, VersionOut
from voizy_api.web.auth import require
from voizy_api.web.common import audit as _audit
from voizy_api.web.common import not_found as _not_found
from voizy_api.web.common import returned as _returned

router = APIRouter(prefix="/v1/agents", tags=["agents"])

_AGENT_COLS = (
    "a.id, a.name, v.version, a.archived_at IS NOT NULL, a.created_at "
    "FROM agents a LEFT JOIN agent_versions v "
    "ON v.workspace_id = a.workspace_id AND v.id = a.published_version_id"
)


def _agent_out(row: tuple[Any, ...]) -> AgentOut:
    return AgentOut(
        id=row[0], name=row[1], published_version=row[2], archived=row[3], created_at=row[4]
    )


@router.post("", response_model=AgentOut, status_code=status.HTTP_201_CREATED)
async def create_agent(
    body: AgentCreate,
    request: Request,
    p: Annotated[Principal, Depends(require(Permission.AGENTS_CREATE))],
) -> AgentOut:
    async with workspace_tx(request.app.state.pool, p.workspace_id) as conn:
        cur = await conn.execute(
            "INSERT INTO agents (workspace_id, name, created_by) VALUES (%s, %s, NULL) "
            "RETURNING id",
            (p.workspace_id, body.name),
        )
        agent_id: uuid.UUID = _returned(await cur.fetchone())[0]
        await conn.execute(
            "INSERT INTO agent_versions (workspace_id, agent_id, version, config) "
            "VALUES (%s, %s, 1, %s::jsonb)",
            (p.workspace_id, agent_id, body.config.model_dump_json()),
        )
        await _audit(conn, p, "agent.create", "agent", agent_id)
        cur = await conn.execute(f"SELECT {_AGENT_COLS} WHERE a.id = %s", (agent_id,))
        out = _returned(await cur.fetchone())
    return _agent_out(out)


@router.get("", response_model=list[AgentOut])
async def list_agents(
    request: Request,
    p: Annotated[Principal, Depends(require(Permission.AGENTS_READ))],
) -> list[AgentOut]:
    async with workspace_tx(request.app.state.pool, p.workspace_id) as conn:
        cur = await conn.execute(f"SELECT {_AGENT_COLS} ORDER BY a.created_at DESC LIMIT 200")
        return [_agent_out(r) for r in await cur.fetchall()]


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(
    agent_id: uuid.UUID,
    request: Request,
    p: Annotated[Principal, Depends(require(Permission.AGENTS_READ))],
) -> AgentOut:
    async with workspace_tx(request.app.state.pool, p.workspace_id) as conn:
        cur = await conn.execute(f"SELECT {_AGENT_COLS} WHERE a.id = %s", (agent_id,))
        row = await cur.fetchone()
    if row is None:
        raise _not_found()
    return _agent_out(row)


@router.post("/{agent_id}/versions", response_model=VersionOut, status_code=status.HTTP_201_CREATED)
async def create_version(
    agent_id: uuid.UUID,
    body: VersionCreate,
    request: Request,
    p: Annotated[Principal, Depends(require(Permission.AGENTS_EDIT))],
) -> VersionOut:
    async with workspace_tx(request.app.state.pool, p.workspace_id) as conn:
        # Lock the agent row so concurrent creators get distinct version numbers.
        cur = await conn.execute(
            "SELECT archived_at IS NOT NULL FROM agents WHERE id = %s FOR UPDATE", (agent_id,)
        )
        agent = await cur.fetchone()
        if agent is None:
            raise _not_found()
        if agent[0]:
            raise HTTPException(status.HTTP_409_CONFLICT, "agent is archived")
        cur = await conn.execute(
            "INSERT INTO agent_versions (workspace_id, agent_id, version, config) "
            "SELECT %s, %s, coalesce(max(version), 0) + 1, %s::jsonb "
            "FROM agent_versions WHERE agent_id = %s "
            "RETURNING version, is_published, published_at, created_at",
            (p.workspace_id, agent_id, body.config.model_dump_json(), agent_id),
        )
        row = _returned(await cur.fetchone())
        await _audit(conn, p, "agent.version.create", "agent", agent_id, version=row[0])
    return VersionOut(
        version=row[0],
        is_published=row[1],
        published_at=row[2],
        created_at=row[3],
        config=body.config,
    )


@router.get("/{agent_id}/versions/{version}", response_model=VersionOut)
async def get_version(
    agent_id: uuid.UUID,
    version: int,
    request: Request,
    p: Annotated[Principal, Depends(require(Permission.AGENTS_READ))],
) -> VersionOut:
    async with workspace_tx(request.app.state.pool, p.workspace_id) as conn:
        cur = await conn.execute(
            "SELECT version, is_published, published_at, created_at, config "
            "FROM agent_versions WHERE agent_id = %s AND version = %s",
            (agent_id, version),
        )
        row = await cur.fetchone()
    if row is None:
        raise _not_found()
    return VersionOut(
        version=row[0],
        is_published=row[1],
        published_at=row[2],
        created_at=row[3],
        config=AgentConfig.model_validate(row[4]),
    )


@router.post("/{agent_id}/versions/{version}/publish", response_model=AgentOut)
async def publish_version(
    agent_id: uuid.UUID,
    version: int,
    request: Request,
    p: Annotated[Principal, Depends(require(Permission.AGENTS_PUBLISH))],
) -> AgentOut:
    async with workspace_tx(request.app.state.pool, p.workspace_id) as conn:
        cur = await conn.execute(
            "SELECT archived_at IS NOT NULL FROM agents WHERE id = %s FOR UPDATE", (agent_id,)
        )
        agent = await cur.fetchone()
        if agent is None:
            raise _not_found()
        if agent[0]:
            raise HTTPException(status.HTTP_409_CONFLICT, "agent is archived")
        cur = await conn.execute(
            "UPDATE agent_versions SET is_published = true, "
            "published_at = coalesce(published_at, now()) "
            "WHERE agent_id = %s AND version = %s RETURNING id",
            (agent_id, version),
        )
        vrow = await cur.fetchone()
        if vrow is None:
            raise _not_found()
        await conn.execute(
            "UPDATE agents SET published_version_id = %s WHERE id = %s", (vrow[0], agent_id)
        )
        await _audit(conn, p, "agent.publish", "agent", agent_id, version=version)
        cur = await conn.execute(f"SELECT {_AGENT_COLS} WHERE a.id = %s", (agent_id,))
        out = _returned(await cur.fetchone())
    return _agent_out(out)
