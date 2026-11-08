"""Who am I, version listing, and browser test calls."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from voizy_core.db.pool import workspace_tx
from voizy_core.domain.dispatch import DispatchTarget
from voizy_core.domain.permissions import Permission
from voizy_core.services.auth import Principal

from voizy_api.livekit import mint_test_session
from voizy_api.schemas.session import MeOut, TestSessionOut, VersionSummary
from voizy_api.web.auth import current_principal, require
from voizy_api.web.common import audit, not_found, returned

router = APIRouter(prefix="/v1", tags=["session"])


@router.get("/me", response_model=MeOut)
async def me(request: Request, p: Annotated[Principal, Depends(current_principal)]) -> MeOut:
    async with workspace_tx(request.app.state.pool, p.workspace_id) as conn:
        cur = await conn.execute("SELECT name FROM workspaces WHERE id = %s", (p.workspace_id,))
        name = returned(await cur.fetchone())[0]
    return MeOut(
        workspace_id=p.workspace_id,
        workspace_name=name,
        api_key_id=p.api_key_id,
        permissions=sorted(p.permissions),
    )


@router.get("/agents/{agent_id}/versions", response_model=list[VersionSummary])
async def list_versions(
    agent_id: uuid.UUID,
    request: Request,
    p: Annotated[Principal, Depends(require(Permission.AGENTS_READ))],
) -> list[VersionSummary]:
    async with workspace_tx(request.app.state.pool, p.workspace_id) as conn:
        cur = await conn.execute("SELECT 1 FROM agents WHERE id = %s", (agent_id,))
        if await cur.fetchone() is None:
            raise not_found()
        cur = await conn.execute(
            "SELECT version, is_published, published_at, created_at FROM agent_versions "
            "WHERE agent_id = %s ORDER BY version DESC LIMIT 200",
            (agent_id,),
        )
        return [
            VersionSummary(version=r[0], is_published=r[1], published_at=r[2], created_at=r[3])
            for r in await cur.fetchall()
        ]


@router.post(
    "/agents/{agent_id}/versions/{version}/test-session",
    response_model=TestSessionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_test_session(
    agent_id: uuid.UUID,
    version: int,
    request: Request,
    p: Annotated[Principal, Depends(require(Permission.AGENTS_TEST))],
) -> TestSessionOut:
    settings = request.app.state.livekit
    if settings is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "voice runtime is not configured")
    async with workspace_tx(request.app.state.pool, p.workspace_id) as conn:
        cur = await conn.execute(
            "SELECT 1 FROM agent_versions v JOIN agents a "
            "ON a.workspace_id = v.workspace_id AND a.id = v.agent_id "
            "WHERE v.agent_id = %s AND v.version = %s AND a.archived_at IS NULL",
            (agent_id, version),
        )
        if await cur.fetchone() is None:
            raise not_found()
        session = mint_test_session(settings, DispatchTarget(p.workspace_id, agent_id, version))
        await audit(
            conn, p, "agent.test_session", "agent", agent_id, version=version, room=session.room
        )
    return TestSessionOut(
        url=session.url,
        token=session.token,
        room=session.room,
        identity=session.identity,
        expires_in_s=session.expires_in_s,
    )
