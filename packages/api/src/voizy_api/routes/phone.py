"""Phone numbers (Twilio via SIP into LiveKit) and outbound calls."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from voizy_core.db.pool import workspace_tx
from voizy_core.domain.dispatch import DispatchTarget
from voizy_core.domain.permissions import Permission
from voizy_core.services import telephony as numbers
from voizy_core.services.auth import Principal

from voizy_api.schemas.phone import (
    OutboundCall,
    OutboundCallOut,
    PhoneNumberCreate,
    PhoneNumberOut,
    PhoneNumberUpdate,
)
from voizy_api.settings import Settings
from voizy_api.telephony import Telephony, TelephonyError, new_sip_credentials
from voizy_api.telephony_access import telephony_for
from voizy_api.web.auth import require
from voizy_api.web.common import audit, not_found

log = logging.getLogger("uvicorn.error")
router = APIRouter(prefix="/v1", tags=["phone"])
Reader = Annotated[Principal, Depends(require(Permission.NUMBERS_READ))]
Manager = Annotated[Principal, Depends(require(Permission.NUMBERS_MANAGE))]
Dialer = Annotated[Principal, Depends(require(Permission.CALLS_PLACE_OUTBOUND))]


def _out(n: numbers.PhoneNumber) -> PhoneNumberOut:
    return PhoneNumberOut(
        id=n.id,
        e164=n.e164,
        label=n.label,
        agent_id=n.agent_id,
        agent_name=n.agent_name,
        created_at=n.created_at,
    )


async def _telephony(request: Request, p: Principal) -> Telephony:
    settings: Settings = request.app.state.settings
    if settings.secret_box is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Secret storage is not configured on the server."
        )
    try:
        return await telephony_for(
            request.app.state.pool, settings, request.app.state.livekit, p.workspace_id
        )
    except TelephonyError as exc:  # not connected yet, or the SIP host cannot be worked out
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


async def ensure_live_agent(request: Request, p: Principal, agent_id: uuid.UUID) -> None:
    """The agent must exist, be live (published) and not archived, or callers would hear silence."""
    async with workspace_tx(request.app.state.pool, p.workspace_id) as tx:
        cur = await tx.execute(
            "SELECT published_version_id IS NOT NULL, archived_at IS NOT NULL "
            "FROM agents WHERE id = %s",
            (agent_id,),
        )
        row = await cur.fetchone()
    if row is None or row[1]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That agent does not exist.")
    if not row[0]:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Publish the agent first. Phone callers only reach published versions.",
        )


@router.get("/phone-numbers", response_model=list[PhoneNumberOut])
async def list_numbers(request: Request, p: Reader) -> list[PhoneNumberOut]:
    async with request.app.state.pool.connection() as conn:
        return [_out(n) for n in await numbers.list_numbers(conn, p.workspace_id)]


@router.post("/phone-numbers", response_model=PhoneNumberOut, status_code=status.HTTP_201_CREATED)
async def connect_number(body: PhoneNumberCreate, request: Request, p: Manager) -> PhoneNumberOut:
    pool = request.app.state.pool
    if body.agent_id is not None:
        await ensure_live_agent(request, p, body.agent_id)
    tel = await _telephony(request, p)
    target = DispatchTarget(p.workspace_id, body.agent_id) if body.agent_id else None

    undo: list[Callable[[], Awaitable[None]]] = []  # compensation for a partial failure
    try:
        number_sid = await tel.twilio.find_number(body.e164)
        async with pool.connection() as conn:
            trunk = await numbers.get_trunk(conn, p.workspace_id)
        if trunk is None:
            domain = f"voizy-{uuid.uuid4().hex[:12]}.pstn.twilio.com"
            trunk_sid = await tel.twilio.create_trunk("Voizy", domain)
            await tel.twilio.add_origination(trunk_sid, f"sip:{tel.sip_host};transport=tcp")
            list_sid = await tel.twilio.create_credential_list("Voizy")
            await tel.twilio.attach_credential_list(trunk_sid, list_sid)
            trunk = numbers.Trunk(trunk_sid, domain, list_sid)
            async with pool.connection() as conn:
                await numbers.save_trunk(conn, p.workspace_id, trunk)
        else:
            await _refresh_origination(tel, trunk.twilio_trunk_sid)
        await tel.twilio.attach_number(trunk.twilio_trunk_sid, number_sid)
        undo.append(partial(tel.twilio.detach_number, trunk.twilio_trunk_sid, number_sid))
        user, password = new_sip_credentials()
        cred_sid = await tel.twilio.add_credential(trunk.twilio_credential_list_sid, user, password)
        undo.append(
            partial(tel.twilio.delete_credential, trunk.twilio_credential_list_sid, cred_sid)
        )
        inbound_id, rule_id = await tel.sip.create_inbound(body.e164, target, tel.allowed_addresses)
        undo.append(partial(tel.sip.delete_inbound, inbound_id, rule_id))
        outbound_id = await tel.sip.create_outbound(
            body.e164, trunk.termination_domain, user, password
        )
        undo.append(partial(tel.sip.delete_outbound, outbound_id))
        async with pool.connection() as conn:
            new_id = await numbers.add_number(
                conn,
                p.workspace_id,
                e164=body.e164,
                label=body.label,
                agent_id=body.agent_id,
                twilio_number_sid=number_sid,
                twilio_credential_sid=cred_sid,
                lk_inbound_trunk_id=inbound_id,
                lk_dispatch_rule_id=rule_id,
                lk_outbound_trunk_id=outbound_id,
            )
    except numbers.NumberTakenError:
        await _rollback(undo)
        raise HTTPException(status.HTTP_409_CONFLICT, "That number is already connected.") from None
    except TelephonyError as exc:
        await _rollback(undo)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    except Exception:
        await _rollback(undo)
        log.exception("connecting a number failed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Could not finish connecting the number. Nothing was kept."
        ) from None
    async with workspace_tx(pool, p.workspace_id) as conn:
        await audit(conn, p, "phone_number.connect", "phone_number", new_id, e164=body.e164)
    async with pool.connection() as conn:
        created = await numbers.get_number(conn, p.workspace_id, new_id)
    if created is None:
        raise not_found()
    return _out(created)


async def _refresh_origination(tel: Telephony, trunk_sid: str) -> None:
    """Point an existing Twilio trunk at the current LiveKit SIP address.

    A workspace reuses one trunk. If the LiveKit project changed since it was created, the trunk
    would keep sending incoming calls to the old project's address.
    """
    wanted = f"sip:{tel.sip_host};transport=tcp"
    existing = await tel.twilio.list_origination_urls(trunk_sid)
    if any(url == wanted for _, url in existing):
        return
    await tel.twilio.add_origination(trunk_sid, wanted)
    for sid, _ in existing:
        await tel.twilio.delete_origination(trunk_sid, sid)


async def _rollback(undo: list[Callable[[], Awaitable[None]]]) -> None:
    """Best effort: remove whatever was created before the failure, newest first."""
    for step in reversed(undo):
        try:
            await step()
        except Exception:  # noqa: BLE001 - cleanup must not mask the original error
            log.warning("cleanup after a failed number connect: a step failed")


@router.patch("/phone-numbers/{number_id}", response_model=PhoneNumberOut)
async def update_number(
    number_id: uuid.UUID, body: PhoneNumberUpdate, request: Request, p: Manager
) -> PhoneNumberOut:
    pool = request.app.state.pool
    async with pool.connection() as conn:
        current = await numbers.get_number(conn, p.workspace_id, number_id)
    if current is None:
        raise not_found()
    agent_id, rule_id = current.agent_id, current.lk_dispatch_rule_id
    if "agent_id" in body.model_fields_set and body.agent_id != current.agent_id:
        tel = await _telephony(request, p)
        try:
            if body.agent_id is None:
                if rule_id:
                    await tel.sip.remove_rule(rule_id)
                rule_id = ""
            else:
                await ensure_live_agent(request, p, body.agent_id)
                rule_id = await tel.sip.replace_rule(
                    current.lk_inbound_trunk_id,
                    rule_id,
                    DispatchTarget(p.workspace_id, body.agent_id),
                )
        except TelephonyError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
        agent_id = body.agent_id
    async with pool.connection() as conn:
        await numbers.update_assignment(
            conn,
            p.workspace_id,
            number_id,
            agent_id=agent_id,
            label=body.label,
            lk_dispatch_rule_id=rule_id,
        )
    async with workspace_tx(pool, p.workspace_id) as conn:
        await audit(
            conn,
            p,
            "phone_number.update",
            "phone_number",
            number_id,
            agent_id=str(agent_id) if agent_id else None,
        )
    async with pool.connection() as conn:
        updated = await numbers.get_number(conn, p.workspace_id, number_id)
    if updated is None:
        raise not_found()
    return _out(updated)


@router.delete("/phone-numbers/{number_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_number(number_id: uuid.UUID, request: Request, p: Manager) -> Response:
    pool = request.app.state.pool
    async with pool.connection() as conn:
        n = await numbers.get_number(conn, p.workspace_id, number_id)
        trunk = await numbers.get_trunk(conn, p.workspace_id)
    if n is None:
        raise not_found()
    tel = await _telephony(request, p)
    problems: list[str] = []
    steps = [
        (
            "LiveKit inbound trunk",
            tel.sip.delete_inbound(n.lk_inbound_trunk_id, n.lk_dispatch_rule_id),
        ),
        ("LiveKit outbound trunk", tel.sip.delete_outbound(n.lk_outbound_trunk_id)),
    ]
    if trunk is not None:
        steps += [
            (
                "Twilio number",
                tel.twilio.detach_number(trunk.twilio_trunk_sid, n.twilio_number_sid),
            ),
            (
                "Twilio credential",
                tel.twilio.delete_credential(
                    trunk.twilio_credential_list_sid, n.twilio_credential_sid
                ),
            ),
        ]
    for name, step in steps:
        try:
            await step
        except Exception as exc:  # noqa: BLE001 - keep going so as much as possible is removed
            problems.append(f"{name}: {exc}"[:160])
    async with pool.connection() as conn:
        await numbers.delete_number(conn, p.workspace_id, number_id)
    async with workspace_tx(pool, p.workspace_id) as conn:
        await audit(
            conn, p, "phone_number.disconnect", "phone_number", number_id, problems=problems
        )
    if problems:
        log.warning("number disconnected with leftovers: %s", problems)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/calls/outbound", response_model=OutboundCallOut, status_code=status.HTTP_202_ACCEPTED
)
async def place_call(body: OutboundCall, request: Request, p: Dialer) -> OutboundCallOut:
    if not body.consent_confirmed:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Confirm that you have permission to call this person.",
        )
    settings: Settings = request.app.state.settings
    key = str(p.workspace_id)
    if settings.outbound_throttle.retry_after(key) > 0:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many outbound calls. Try again later."
        )
    pool = request.app.state.pool
    async with pool.connection() as conn:
        n = await numbers.get_number(conn, p.workspace_id, body.from_number_id)
    if n is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown calling number.")
    if body.to == n.e164:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Cannot call the same number.")
    await ensure_live_agent(request, p, body.agent_id)
    tel = await _telephony(request, p)
    settings.outbound_throttle.record_failure(key)  # counts attempts, not failures
    try:
        room = await tel.sip.dial(
            n.lk_outbound_trunk_id, body.to, DispatchTarget(p.workspace_id, body.agent_id)
        )
    except TelephonyError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    async with workspace_tx(pool, p.workspace_id) as conn:
        await audit(
            conn,
            p,
            "call.outbound",
            "phone_number",
            n.id,
            agent_id=str(body.agent_id),
            to_last4=body.to[-4:],
        )
    return OutboundCallOut(room=room)
