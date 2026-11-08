"""LiveKit settings and token minting for browser test calls."""

from __future__ import annotations

import datetime as dt
import os
import uuid
from dataclasses import dataclass

from livekit import api
from voizy_core.domain.dispatch import AGENT_WORKER_NAME, DispatchTarget, encode_dispatch

TEST_TOKEN_TTL = dt.timedelta(minutes=10)


@dataclass(frozen=True)
class LiveKitSettings:
    url: str
    api_key: str
    api_secret: str

    @classmethod
    def from_env(cls) -> LiveKitSettings | None:
        url = os.environ.get("LIVEKIT_URL", "")
        key = os.environ.get("LIVEKIT_API_KEY", "")
        secret = os.environ.get("LIVEKIT_API_SECRET", "")
        return cls(url, key, secret) if url and key and secret else None

    def __repr__(self) -> str:  # never print the secret
        return f"LiveKitSettings(url={self.url!r}, api_key={self.api_key!r}, api_secret=<redacted>)"


@dataclass(frozen=True)
class TestSession:
    __test__ = False  # not a pytest class

    url: str
    token: str
    room: str
    identity: str
    expires_in_s: int


def mint_test_session(settings: LiveKitSettings, target: DispatchTarget) -> TestSession:
    """A short-lived token that joins a fresh room and dispatches the agent with signed metadata.

    The agent is requested inside the token, which the API signs, so a browser cannot choose
    a different agent or workspace by editing anything client-side.
    """
    room = f"test-{uuid.uuid4().hex[:12]}"
    identity = f"tester-{uuid.uuid4().hex[:8]}"
    token = (
        api.AccessToken(settings.api_key, settings.api_secret)
        .with_identity(identity)
        .with_ttl(TEST_TOKEN_TTL)
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
            )
        )
        .with_room_config(
            api.RoomConfiguration(
                agents=[
                    api.RoomAgentDispatch(
                        agent_name=AGENT_WORKER_NAME, metadata=encode_dispatch(target)
                    )
                ],
                empty_timeout=60,
                max_participants=2,
            )
        )
        .to_jwt()
    )
    return TestSession(settings.url, token, room, identity, int(TEST_TOKEN_TTL.total_seconds()))
