"""Integrations an operator can connect: which secrets each one needs and how they are validated.

Everything is stored encrypted in the workspace's secret store under these reserved names, which
tool credentials may never use or reference.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class IntegrationField:
    name: str  # also the secret's name in the store
    label: str
    secret: bool = True  # False: not sensitive, shown back to the operator as typed
    pattern: str = r"^.{1,512}$"
    placeholder: str = ""
    help: str = ""

    def valid(self, value: str) -> bool:
        return bool(re.match(self.pattern, value)) and "\n" not in value and "\r" not in value


@dataclass(frozen=True)
class Integration:
    id: str
    label: str
    description: str
    fields: tuple[IntegrationField, ...]
    used_for: str


INTEGRATIONS: tuple[Integration, ...] = (
    Integration(
        "livekit",
        "LiveKit",
        "Real-time audio rooms, and (optionally) hosted speech and language models.",
        (
            IntegrationField(
                "livekit_url",
                "Project URL",
                secret=False,
                pattern=r"^wss://[A-Za-z0-9.-]+(:\d+)?$",
                placeholder="wss://your-project.livekit.cloud",
                help="Starts with wss://. Find it in your LiveKit Cloud project settings.",
            ),
            IntegrationField(
                "livekit_api_key",
                "API key",
                pattern=r"^[A-Za-z0-9_-]{6,128}$",
                placeholder="APIxxxxxxxxxxxx",
            ),
            IntegrationField(
                "livekit_api_secret",
                "API secret",
                pattern=r"^[A-Za-z0-9_+/=-]{16,256}$",
            ),
        ),
        "Test calls from the dashboard and the voice agent's connection.",
    ),
    Integration(
        "twilio",
        "Twilio",
        "Phone numbers and calls.",
        (
            IntegrationField(
                "twilio_account_sid",
                "Account SID",
                secret=False,
                pattern=r"^AC[0-9a-fA-F]{32}$",
                placeholder="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            ),
            IntegrationField("twilio_auth_token", "Auth token", pattern=r"^[0-9a-fA-F]{32}$"),
        ),
        "Phone numbers: Voizy connects numbers in this account to LiveKit and places calls.",
    ),
    Integration(
        "openai",
        "OpenAI",
        "Language models, used directly instead of through LiveKit.",
        (
            IntegrationField(
                "openai_api_key",
                "API key",
                pattern=r"^sk-[A-Za-z0-9_-]{16,300}$",
                placeholder="sk-...",
            ),
        ),
        "Agents whose language model is from OpenAI.",
    ),
    Integration(
        "google",
        "Google AI",
        "Gemini language models, used directly instead of through LiveKit.",
        (
            IntegrationField(
                "google_api_key",
                "API key",
                pattern=r"^[A-Za-z0-9_-]{20,200}$",
                placeholder="AIza...",
            ),
        ),
        "Agents whose language model is from Google.",
    ),
    Integration(
        "deepgram",
        "Deepgram",
        "Speech recognition, used directly instead of through LiveKit.",
        (IntegrationField("deepgram_api_key", "API key", pattern=r"^[A-Za-z0-9]{20,100}$"),),
        "Agents whose speech recognition is from Deepgram.",
    ),
    Integration(
        "cartesia",
        "Cartesia",
        "Voices, used directly instead of through LiveKit.",
        (IntegrationField("cartesia_api_key", "API key", pattern=r"^[A-Za-z0-9_-]{16,200}$"),),
        "Agents whose voice is from Cartesia.",
    ),
)

BY_ID: dict[str, Integration] = {i.id: i for i in INTEGRATIONS}
RESERVED_SECRET_NAMES: frozenset[str] = frozenset(f.name for i in INTEGRATIONS for f in i.fields)
