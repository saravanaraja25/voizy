"""The campaign scheduler: a loop in the API process that places the next calls.

Single-deployment scope like retention: it serves the primary workspace. Each tick, for every
running campaign: turn finished calls into outcomes, claim the contacts that are due (window,
do-not-call and concurrency are decided in SQL), dial them, and close the campaign when nothing
is left. A dial that fails is counted as an attempt and retried later.
"""

from __future__ import annotations

import asyncio
import logging

from psycopg_pool import AsyncConnectionPool
from voizy_core.domain.dispatch import DispatchTarget
from voizy_core.services import campaigns

from voizy_api.livekit import LiveKitSettings
from voizy_api.settings import Settings
from voizy_api.telephony import TelephonyError
from voizy_api.telephony_access import telephony_for

log = logging.getLogger("uvicorn.error")
TICK_S = 5.0


async def run_once(
    pool: AsyncConnectionPool, settings: Settings, env_livekit: LiveKitSettings | None
) -> int:
    """One scheduling pass. Returns how many calls were started."""
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT primary_workspace_id FROM instance_settings")
        row = await cur.fetchone()
    if row is None or row[0] is None:
        return 0
    workspace_id = row[0]
    async with pool.connection() as conn:
        running = await campaigns.running_campaign_ids(conn, workspace_id)
    started = 0
    for campaign_id in running:
        async with pool.connection() as conn:
            await campaigns.resolve_finished(conn, workspace_id, campaign_id)
        async with pool.connection() as conn:
            claims = await campaigns.claim_due(conn, workspace_id, campaign_id)
        if claims:
            try:
                tel = await telephony_for(pool, settings, env_livekit, workspace_id)
            except TelephonyError as exc:
                for claim in claims:
                    async with pool.connection() as conn:
                        await campaigns.release_failed(
                            conn, workspace_id, claim.contact_id, str(exc)
                        )
                claims = []
        for claim in claims:
            try:
                await tel.sip.dial(
                    claim.lk_outbound_trunk_id,
                    claim.e164,
                    DispatchTarget(
                        workspace_id, claim.agent_id, None, "outbound", claim.e164, claim.contact_id
                    ),
                )
                started += 1
            except Exception as exc:  # noqa: BLE001 - one bad dial must not stop the others
                async with pool.connection() as conn:
                    await campaigns.release_failed(
                        conn, workspace_id, claim.contact_id, str(exc) or type(exc).__name__
                    )
        async with pool.connection() as conn:
            await campaigns.maybe_complete(conn, workspace_id, campaign_id)
    return started


async def campaign_loop(
    pool: AsyncConnectionPool, settings: Settings, env_livekit: LiveKitSettings | None
) -> None:
    while True:
        await asyncio.sleep(TICK_S)
        try:
            await run_once(pool, settings, env_livekit)
        except Exception as exc:  # noqa: BLE001 - the scheduler must outlive any single failure
            log.warning("campaign scheduler error (%s)", type(exc).__name__)
