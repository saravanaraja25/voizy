"""Outbound campaigns, their contacts, and the workspace do-not-call list."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from voizy_core.db.pool import workspace_tx
from voizy_core.domain.permissions import Permission
from voizy_core.services import calls as call_store
from voizy_core.services import campaigns as cp
from voizy_core.services.auth import Principal

from voizy_api.routes.phone import ensure_live_agent
from voizy_api.schemas.campaigns import (
    CampaignCreate,
    CampaignCreated,
    CampaignOut,
    ContactListOut,
    ContactOut,
    CsvPayload,
    CsvPreview,
    DncCreate,
    DncOut,
    ImportReport,
)
from voizy_api.telephony import TelephonyError
from voizy_api.telephony_access import telephony_for
from voizy_api.web.auth import require
from voizy_api.web.common import audit, not_found

router = APIRouter(prefix="/v1/campaigns", tags=["campaigns"])
dnc_router = APIRouter(prefix="/v1/dnc", tags=["campaigns"])
Reader = Annotated[Principal, Depends(require(Permission.CAMPAIGNS_READ))]
Creator = Annotated[Principal, Depends(require(Permission.CAMPAIGNS_CREATE))]
Runner = Annotated[Principal, Depends(require(Permission.CAMPAIGNS_RUN))]
ContactManager = Annotated[Principal, Depends(require(Permission.CAMPAIGNS_MANAGE_CONTACTS))]


def _mask(number: str, p: Principal) -> str:
    return (
        number
        if Permission.CALLS_VIEW_PII in p.permissions
        else call_store.mask_number(number) or ""
    )


def _days(mask: int) -> list[int]:
    return [i for i in range(7) if mask >> i & 1]


def _out(c: cp.Campaign, counts: dict[str, int], p: Principal) -> CampaignOut:
    return CampaignOut(
        id=c.id,
        name=c.name,
        agent_id=c.agent_id,
        agent_name=c.agent_name,
        from_number_id=c.from_number_id,
        from_number=_mask(c.from_e164, p),
        status=c.status,  # type: ignore[arg-type]
        timezone=c.timezone,
        days=_days(c.days_mask),
        window_start=c.window_start.strftime("%H:%M"),
        window_end=c.window_end.strftime("%H:%M"),
        max_concurrent=c.max_concurrent,
        max_attempts=c.max_attempts,
        retry_delay_min=c.retry_delay_min,
        created_at=c.created_at,
        started_at=c.started_at,
        completed_at=c.completed_at,
        counts=counts,
    )


def _unprocessable(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


async def _agent_variables(request: Request, p: Principal, agent_id: uuid.UUID) -> set[str]:
    """Variables the published agent declares: the only CSV columns that reach a prompt."""
    async with workspace_tx(request.app.state.pool, p.workspace_id) as conn:
        cur = await conn.execute(
            "SELECT v.config->'variables' FROM agents a JOIN agent_versions v "
            "ON v.workspace_id = a.workspace_id AND v.id = a.published_version_id WHERE a.id = %s",
            (agent_id,),
        )
        row = await cur.fetchone()
    return {v["name"] for v in (row[0] if row and row[0] else [])}


def _report(parsed: cp.ParsedCsv, added: int, existing: int) -> ImportReport:
    return ImportReport(
        added=added,
        already_in_campaign=existing,
        rejected=parsed.rejected[:200],
        ignored_columns=parsed.ignored_columns,
    )


@router.get("", response_model=list[CampaignOut])
async def list_campaigns(request: Request, p: Reader) -> list[CampaignOut]:
    async with request.app.state.pool.connection() as conn:
        rows = await cp.list_campaigns(conn, p.workspace_id)
    return [_out(c, counts, p) for c, counts in rows]


@router.post("/preview-csv", response_model=CsvPreview)
async def preview_csv(body: CsvPayload, request: Request, p: Creator) -> CsvPreview:
    known = await _agent_variables(request, p, body.agent_id) if body.agent_id else None
    try:
        parsed = cp.parse_contacts_csv(
            body.csv, default_country_code=body.default_country_code, known_variables=known
        )
    except cp.CampaignError as exc:
        raise _unprocessable(exc) from exc
    sample = [
        {"number": _mask(c.e164, p), "name": c.name, **c.variables} for c in parsed.accepted[:5]
    ]
    return CsvPreview(
        accepted=len(parsed.accepted),
        rejected=parsed.rejected[:200],
        ignored_columns=parsed.ignored_columns,
        sample=sample,
    )


@router.post("", response_model=CampaignCreated, status_code=status.HTTP_201_CREATED)
async def create_campaign(body: CampaignCreate, request: Request, p: Creator) -> CampaignCreated:
    pool = request.app.state.pool
    if len(set(body.days)) != len(body.days) or any(d < 0 or d > 6 for d in body.days):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Days must be 0 (Mon) to 6 (Sun)."
        )
    await ensure_live_agent(request, p, body.agent_id)
    parsed: cp.ParsedCsv | None = None
    if body.csv:
        try:
            parsed = cp.parse_contacts_csv(
                body.csv,
                default_country_code=body.default_country_code,
                known_variables=await _agent_variables(request, p, body.agent_id),
            )
        except cp.CampaignError as exc:
            raise _unprocessable(exc) from exc
    try:
        async with pool.connection() as conn:
            cid = await cp.create_campaign(
                conn,
                p.workspace_id,
                name=body.name,
                agent_id=body.agent_id,
                from_number_id=body.from_number_id,
                timezone=body.timezone,
                days_mask=sum(1 << d for d in set(body.days)),
                window_start=dt.time.fromisoformat(body.window_start),
                window_end=dt.time.fromisoformat(body.window_end),
                max_concurrent=body.max_concurrent,
                max_attempts=body.max_attempts,
                retry_delay_min=body.retry_delay_min,
                consent_confirmed=body.consent_confirmed,
                user_id=p.user_id,
            )
    except cp.CampaignError as exc:
        raise _unprocessable(exc) from exc
    except Exception as exc:
        if "foreign key" in str(exc).lower():  # a number or agent id that is not theirs
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown calling number."
            ) from exc
        raise
    report = None
    if parsed is not None:
        async with pool.connection() as conn:
            added, existing = await cp.add_contacts(conn, p.workspace_id, cid, parsed.accepted)
        report = _report(parsed, added, existing)
    async with workspace_tx(pool, p.workspace_id) as conn:
        await audit(
            conn,
            p,
            "campaign.create",
            "campaign",
            cid,
            name=body.name,
            contacts=report.added if report else 0,
        )
    async with pool.connection() as conn:
        created = await cp.get_campaign(conn, p.workspace_id, cid)
        counts = await cp.counts(conn, p.workspace_id, cid)
    if created is None:
        raise not_found()
    return CampaignCreated(campaign=_out(created, counts, p), import_report=report)


@router.get("/{campaign_id}", response_model=CampaignOut)
async def get_campaign(campaign_id: uuid.UUID, request: Request, p: Reader) -> CampaignOut:
    async with request.app.state.pool.connection() as conn:
        c = await cp.get_campaign(conn, p.workspace_id, campaign_id)
        counts = await cp.counts(conn, p.workspace_id, campaign_id)
    if c is None:
        raise not_found()
    return _out(c, counts, p)


@router.post("/{campaign_id}/contacts", response_model=ImportReport)
async def add_contacts(
    campaign_id: uuid.UUID, body: CsvPayload, request: Request, p: ContactManager
) -> ImportReport:
    pool = request.app.state.pool
    async with pool.connection() as conn:
        c = await cp.get_campaign(conn, p.workspace_id, campaign_id)
    if c is None:
        raise not_found()
    try:
        parsed = cp.parse_contacts_csv(
            body.csv,
            default_country_code=body.default_country_code,
            known_variables=await _agent_variables(request, p, c.agent_id),
        )
        async with pool.connection() as conn:
            added, existing = await cp.add_contacts(
                conn, p.workspace_id, campaign_id, parsed.accepted
            )
    except cp.CampaignError as exc:
        raise _unprocessable(exc) from exc
    async with workspace_tx(pool, p.workspace_id) as conn:
        await audit(conn, p, "campaign.contacts", "campaign", campaign_id, added=added)
    return _report(parsed, added, existing)


@router.get("/{campaign_id}/contacts", response_model=ContactListOut)
async def list_contacts(
    campaign_id: uuid.UUID,
    request: Request,
    p: Reader,
    contact_status: Annotated[
        Literal[
            "pending",
            "calling",
            "completed",
            "no_answer",
            "voicemail",
            "failed",
            "opted_out",
            "dnc",
        ]
        | None,
        Query(alias="status"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> ContactListOut:
    async with request.app.state.pool.connection() as conn:
        if await cp.get_campaign(conn, p.workspace_id, campaign_id) is None:
            raise not_found()
        rows, total = await cp.list_contacts(
            conn, p.workspace_id, campaign_id, status=contact_status, limit=limit, offset=offset
        )
    return ContactListOut(
        total=total,
        items=[
            ContactOut(
                id=c.id,
                number=_mask(c.e164, p),
                name=c.name,
                timezone=c.timezone,
                status=c.status,  # type: ignore[arg-type]
                attempts=c.attempts,
                next_attempt_at=c.next_attempt_at,
                last_outcome=c.last_outcome,
                last_error=c.last_error,
                last_call_id=c.last_call_id,
            )
            for c in rows
        ],
    )


async def _transition(
    campaign_id: uuid.UUID, new: str, action: str, request: Request, p: Principal
) -> CampaignOut:
    pool = request.app.state.pool
    async with pool.connection() as conn:
        c = await cp.get_campaign(conn, p.workspace_id, campaign_id)
    if c is None:
        raise not_found()
    if new == "running":  # starting or resuming: make sure the calls can actually be placed
        await ensure_live_agent(request, p, c.agent_id)
        try:
            await telephony_for(
                pool, request.app.state.settings, request.app.state.livekit, p.workspace_id
            )
        except TelephonyError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    try:
        async with pool.connection() as conn:
            await cp.set_status(conn, p.workspace_id, campaign_id, new)
    except cp.CampaignError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    async with workspace_tx(pool, p.workspace_id) as conn:
        await audit(conn, p, f"campaign.{action}", "campaign", campaign_id)
    async with pool.connection() as conn:
        updated = await cp.get_campaign(conn, p.workspace_id, campaign_id)
        counts = await cp.counts(conn, p.workspace_id, campaign_id)
    if updated is None:
        raise not_found()
    return _out(updated, counts, p)


@router.post("/{campaign_id}/start", response_model=CampaignOut)
async def start(campaign_id: uuid.UUID, request: Request, p: Runner) -> CampaignOut:
    return await _transition(campaign_id, "running", "start", request, p)


@router.post("/{campaign_id}/pause", response_model=CampaignOut)
async def pause(campaign_id: uuid.UUID, request: Request, p: Runner) -> CampaignOut:
    return await _transition(campaign_id, "paused", "pause", request, p)


@router.post("/{campaign_id}/resume", response_model=CampaignOut)
async def resume(campaign_id: uuid.UUID, request: Request, p: Runner) -> CampaignOut:
    return await _transition(campaign_id, "running", "resume", request, p)


@router.post("/{campaign_id}/cancel", response_model=CampaignOut)
async def cancel(campaign_id: uuid.UUID, request: Request, p: Runner) -> CampaignOut:
    return await _transition(campaign_id, "cancelled", "cancel", request, p)


# ------------------------------------------------------------------------------------ do not call


@dnc_router.get("", response_model=list[DncOut])
async def list_dnc(request: Request, p: Reader) -> list[DncOut]:
    async with request.app.state.pool.connection() as conn:
        rows = await cp.dnc_list(conn, p.workspace_id)
    return [
        DncOut(number=_mask(n, p), source=s, note=note, created_at=at) for n, s, note, at in rows
    ]


@dnc_router.post("", response_model=DncOut, status_code=status.HTTP_201_CREATED)
async def add_dnc(body: DncCreate, request: Request, p: ContactManager) -> DncOut:
    pool = request.app.state.pool
    try:
        async with pool.connection() as conn:
            await cp.dnc_add(conn, p.workspace_id, body.e164, source="manual", note=body.note)
    except cp.CampaignError as exc:
        raise _unprocessable(exc) from exc
    async with workspace_tx(pool, p.workspace_id) as conn:
        await audit(conn, p, "dnc.add", "dnc", body.e164[-4:])
    return DncOut(
        number=_mask(body.e164, p),
        source="manual",
        note=body.note,
        created_at=dt.datetime.now(dt.UTC),
    )


@dnc_router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def remove_dnc(
    request: Request,
    p: ContactManager,
    e164: Annotated[str, Query(pattern=r"^\+[1-9][0-9]{6,14}$")],
) -> Response:
    pool = request.app.state.pool
    async with pool.connection() as conn:
        removed = await cp.dnc_remove(conn, p.workspace_id, e164)
    if not removed:
        raise not_found()
    async with workspace_tx(pool, p.workspace_id) as conn:
        await audit(conn, p, "dnc.remove", "dnc", e164[-4:])
    return Response(status_code=status.HTTP_204_NO_CONTENT)
