"""Building the Twilio + LiveKit SIP clients for a workspace from its stored keys."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from psycopg_pool import AsyncConnectionPool
from voizy_core.services import secrets_store as store

from voizy_api.livekit import LiveKitSettings, resolve_livekit
from voizy_api.telephony import NotConfiguredError, Telephony, TwilioCreds

if TYPE_CHECKING:
    from voizy_api.settings import Settings

TWILIO_FIELDS = ("twilio_account_sid", "twilio_auth_token")


async def telephony_for(
    pool: AsyncConnectionPool,
    settings: Settings,
    env_livekit: LiveKitSettings | None,
    workspace_id: uuid.UUID,
) -> Telephony:
    """Raises NotConfiguredError (with a message for the operator) when keys are missing."""
    if settings.secret_box is None:
        raise NotConfiguredError("Secret storage is not configured on the server.")
    async with pool.connection() as conn:
        values = await store.get_integration_values(
            conn, settings.secret_box, workspace_id, TWILIO_FIELDS
        )
    if len(values) != len(TWILIO_FIELDS):
        raise NotConfiguredError("Connect your Twilio account in Settings first.")
    lk = await resolve_livekit(pool, settings.secret_box, env_livekit, workspace_id)
    if lk is None:
        raise NotConfiguredError("Connect LiveKit in Settings first.")
    return settings.telephony(lk, TwilioCreds(values[TWILIO_FIELDS[0]], values[TWILIO_FIELDS[1]]))
