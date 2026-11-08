"""Call history. Transcripts need their own permission; deleting a call is audited."""

from __future__ import annotations

import base64
import datetime as dt
import uuid
from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from voizy_core.db.pool import workspace_tx
from voizy_core.domain.permissions import Permission
from voizy_core.services import calls as store
from voizy_core.services.auth import Principal

from voizy_api.schemas.calls import (
    CallDetailOut,
    CallListOut,
    CallOut,
    CallSummaryOut,
    TurnOut,
)
from voizy_api.web.auth import require
from voizy_api.web.common import audit, not_found

router = APIRouter(prefix="/v1/calls", tags=["calls"])
Reader = Annotated[Principal, Depends(require(Permission.CALLS_READ))]
Deleter = Annotated[Principal, Depends(require(Permission.CALLS_DELETE))]


def _encode(row: store.CallRow) -> str:
    raw = f"{row.started_at.isoformat()}|{row.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode(cursor: str) -> tuple[dt.datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        stamp, ident = raw.split("|", 1)
        return dt.datetime.fromisoformat(stamp), uuid.UUID(ident)
    except ValueError:  # includes bad base64, bad UTF-8, bad date and bad UUID
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid cursor") from None


@router.get("", response_model=CallListOut)
async def list_calls(
    request: Request,
    p: Reader,
    agent_id: uuid.UUID | None = None,
    call_status: Annotated[
        Literal["in_progress", "completed", "failed"] | None, Query(alias="status")
    ] = None,
    source: Literal["test", "inbound", "outbound"] | None = None,
    cursor: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> CallListOut:
    before = _decode(cursor) if cursor else None
    async with request.app.state.pool.connection() as conn:
        rows = await store.list_calls(
            conn,
            p.workspace_id,
            agent_id=agent_id,
            status=call_status,
            source=source,
            before=before,
            limit=limit + 1,  # one extra tells us whether there is another page
        )
    page = rows[:limit]
    return CallListOut(
        items=[CallOut(**asdict(r)) for r in page],
        next_cursor=_encode(page[-1]) if len(rows) > limit else None,
    )


@router.get("/summary", response_model=CallSummaryOut)
async def summary(
    request: Request, p: Reader, days: Annotated[int, Query(ge=1, le=90)] = 7
) -> CallSummaryOut:
    since = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)
    async with request.app.state.pool.connection() as conn:
        s = await store.summary(conn, p.workspace_id, since=since)
    return CallSummaryOut(days=days, **asdict(s))


@router.get("/{call_id}", response_model=CallDetailOut)
async def get_call(request: Request, p: Reader, call_id: uuid.UUID) -> CallDetailOut:
    can_view = Permission.CALLS_VIEW_TRANSCRIPT in p.permissions
    async with request.app.state.pool.connection() as conn:
        found = await store.get_call(conn, p.workspace_id, call_id, with_turns=can_view)
    if found is None:
        raise not_found()
    row, turns = found
    return CallDetailOut(
        call=CallOut(**asdict(row)),
        turns=[TurnOut(**asdict(t)) for t in turns],
        transcript_visible=can_view,
    )


@router.delete("/{call_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_call(request: Request, p: Deleter, call_id: uuid.UUID) -> Response:
    pool = request.app.state.pool
    async with pool.connection() as conn:
        deleted = await store.delete_call(conn, p.workspace_id, call_id)
    if not deleted:
        raise not_found()
    async with workspace_tx(pool, p.workspace_id) as conn:
        await audit(conn, p, "call.delete", "call", call_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
