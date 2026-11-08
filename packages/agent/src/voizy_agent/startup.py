"""Worker start-up: find the LiveKit connection before the SDK reads its environment."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable, Mapping, MutableMapping

from voizy_core.db.pool import open_pool

from voizy_agent.credentials import (
    LiveKitCredentials,
    primary_workspace_livekit,
    secret_box_from_env,
)

log = logging.getLogger("voizy.agent")
ENV_NAMES = ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")


class StartupError(RuntimeError):
    """The worker cannot find, or ever hope to find, a LiveKit connection."""


def environment_has_livekit(env: Mapping[str, str]) -> bool:
    return all(env.get(name) for name in ENV_NAMES)


async def _stored_livekit(env: Mapping[str, str]) -> LiveKitCredentials | None:
    box = secret_box_from_env()
    dsn = env.get("VOIZY_DATABASE_URL")
    if box is None or not dsn:
        raise StartupError(
            "No LiveKit connection: set LIVEKIT_URL, LIVEKIT_API_KEY and LIVEKIT_API_SECRET, or "
            "set VOIZY_DATABASE_URL and VOIZY_SECRET_KEYS to use the connection saved in the "
            "dashboard."
        )
    pool = await open_pool(dsn)
    try:
        found = await primary_workspace_livekit(pool, box)
    finally:
        await pool.close()
    return found[1] if found else None


async def adopt_stored_livekit(
    env: MutableMapping[str, str] | None = None,
    *,
    interval_s: float = 10.0,
    max_attempts: int | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> LiveKitCredentials | None:
    """Use the environment's LiveKit settings if all are present; otherwise wait for the primary
    workspace to connect LiveKit in the dashboard, then adopt that. Polling means a freshly started
    stack works as soon as you save the connection, with no restart."""
    env = os.environ if env is None else env
    for name in ENV_NAMES:  # empty values (from compose pass-through) count as unset
        if not env.get(name):
            env.pop(name, None)
    if environment_has_livekit(env):
        return None
    attempt = 0
    while max_attempts is None or attempt < max_attempts:
        attempt += 1
        creds = await _stored_livekit(env)
        if creds:
            env["LIVEKIT_URL"] = creds.url
            env["LIVEKIT_API_KEY"] = creds.api_key
            env["LIVEKIT_API_SECRET"] = creds.api_secret
            log.warning("using the LiveKit connection stored in the dashboard (%s)", creds.url)
            return creds
        if attempt == 1:
            log.warning("waiting for LiveKit to be connected in the dashboard (Settings)")
        await sleep(interval_s)
    return None
