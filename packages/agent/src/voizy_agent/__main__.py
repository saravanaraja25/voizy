import asyncio
import logging
import sys

from livekit import agents

from voizy_agent.startup import StartupError, adopt_stored_livekit

# Commands that connect to LiveKit and so need credentials. `start` is the long-running worker:
# it waits for the connection to be saved in the dashboard. Interactive modes try once and go on.
_CONNECTING = {"start": None, "dev": 1, "connect": 1, "console": 1}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command in _CONNECTING:
        try:
            asyncio.run(adopt_stored_livekit(max_attempts=_CONNECTING[command]))
        except StartupError as exc:
            if command == "start":
                sys.exit(str(exc))  # a worker with nothing to connect to has no use for retrying
    from voizy_agent.worker import server  # imported late: it reads the environment

    agents.cli.run_app(server)
