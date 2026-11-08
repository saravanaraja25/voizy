import asyncio
import logging
import os

from livekit import agents
from voizy_core.db.pool import open_pool

from voizy_agent.credentials import primary_workspace_livekit, secret_box_from_env

log = logging.getLogger("voizy.agent")
_ENV = ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")


async def _adopt_stored_livekit() -> None:
    """With no LiveKit environment variables, connect as the deployment's primary workspace."""
    box = secret_box_from_env()
    dsn = os.environ.get("VOIZY_DATABASE_URL")
    if box is None or not dsn:
        return
    pool = await open_pool(dsn)
    try:
        found = await primary_workspace_livekit(pool, box)
    finally:
        await pool.close()
    if found:
        _, creds = found
        os.environ["LIVEKIT_URL"] = creds.url
        os.environ["LIVEKIT_API_KEY"] = creds.api_key
        os.environ["LIVEKIT_API_SECRET"] = creds.api_secret
        log.warning("using the LiveKit connection stored in the dashboard (%s)", creds.url)


if __name__ == "__main__":
    # The SDK reads these from the environment when it starts, so resolve them first.
    if not all(os.environ.get(name) for name in _ENV):
        asyncio.run(_adopt_stored_livekit())
    from voizy_agent.worker import server  # imported late: it reads the environment

    agents.cli.run_app(server)
