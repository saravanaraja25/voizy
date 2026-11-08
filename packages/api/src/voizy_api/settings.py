"""Runtime settings for the API, read once at startup."""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field

from voizy_core.security.secretbox import SecretBox, SecretError
from voizy_core.security.ssrf import SsrfPolicy
from voizy_core.security.throttle import Throttle

from voizy_api.integration_checks import Checker, make_checker
from voizy_api.livekit import LiveKitSettings
from voizy_api.telephony import (
    TWILIO_SIGNALING_CIDRS,
    LiveKitSip,
    Telephony,
    TwilioApi,
    TwilioCreds,
    sip_host,
)


@dataclass
class Settings:
    cors_origins: list[str] = field(default_factory=list)
    # Cookies are Secure unless explicitly disabled for plain-http local development.
    cookie_secure: bool = True
    setup_token: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    # Off by default: a workspace has one role (Superadmin) and invitations are superadmin-only.
    # On: role templates are seeded, roles can be managed, and invitations may pick a role.
    custom_roles: bool = False
    # Encrypts stored integration keys and tool credentials. None = secret storage is unavailable.
    secret_box: SecretBox | None = None
    # 'Test connection' for each integration; replaceable in tests.
    integration_checker: Checker | None = None
    # Builds the Twilio + LiveKit SIP clients for one workspace; replaceable in tests.
    telephony_factory: Callable[[LiveKitSettings, TwilioCreds], Telephony] | None = None
    sip_host_override: str | None = None
    sip_allowed_addresses: tuple[str, ...] = TWILIO_SIGNALING_CIDRS
    # Outbound dialing is a toll-fraud target: cap calls placed per workspace.
    outbound_throttle: Throttle = field(default_factory=lambda: Throttle(30, 3600))
    # Per-account and per-address failure limits for login-style endpoints.
    email_throttle: Throttle = field(default_factory=lambda: Throttle(5, 900))
    ip_throttle: Throttle = field(default_factory=lambda: Throttle(30, 900))

    def telephony(self, lk: LiveKitSettings, twilio: TwilioCreds) -> Telephony:
        if self.telephony_factory is not None:
            built: Telephony = self.telephony_factory(lk, twilio)
            return built
        return Telephony(
            twilio=TwilioApi(twilio),
            sip=LiveKitSip(lk),
            sip_host=sip_host(lk.url, self.sip_host_override),
            allowed_addresses=self.sip_allowed_addresses,
        )

    @classmethod
    def from_env(cls) -> Settings:
        raw = os.environ.get("VOIZY_CORS_ORIGINS", "")
        origins = [o.strip() for o in raw.split(",") if o.strip() and o.strip() != "*"]
        box: SecretBox | None = None
        if raw_keys := os.environ.get("VOIZY_SECRET_KEYS"):
            try:
                box = SecretBox.from_env_value(raw_keys)
            except SecretError:
                box = None  # reported by the endpoints as 'not configured', never a crash
        dev_local = os.environ.get("VOIZY_DEV_ALLOW_LOCAL_TOOLS") == "1"
        settings = cls(
            secret_box=box,
            integration_checker=make_checker(ssrf_policy=SsrfPolicy(allow_loopback=dev_local)),
            cors_origins=origins,
            cookie_secure=os.environ.get("VOIZY_COOKIE_SECURE", "1") != "0",
            custom_roles=os.environ.get("VOIZY_ENABLE_ROLES") == "1",
        )
        settings.sip_host_override = os.environ.get("VOIZY_LIVEKIT_SIP_HOST") or None
        if allowed := os.environ.get("VOIZY_SIP_ALLOWED_ADDRESSES"):
            settings.sip_allowed_addresses = tuple(
                a.strip() for a in allowed.split(",") if a.strip()
            )
        if token := os.environ.get("VOIZY_SETUP_TOKEN"):
            settings.setup_token = token
        return settings
