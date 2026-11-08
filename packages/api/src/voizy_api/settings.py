"""Runtime settings for the API, read once at startup."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field

from voizy_core.security.throttle import Throttle


@dataclass
class Settings:
    cors_origins: list[str] = field(default_factory=list)
    # Cookies are Secure unless explicitly disabled for plain-http local development.
    cookie_secure: bool = True
    setup_token: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    # Off by default: a workspace has one role (Superadmin) and invitations are superadmin-only.
    # On: role templates are seeded, roles can be managed, and invitations may pick a role.
    custom_roles: bool = False
    # Per-account and per-address failure limits for login-style endpoints.
    email_throttle: Throttle = field(default_factory=lambda: Throttle(5, 900))
    ip_throttle: Throttle = field(default_factory=lambda: Throttle(30, 900))

    @classmethod
    def from_env(cls) -> Settings:
        raw = os.environ.get("VOIZY_CORS_ORIGINS", "")
        origins = [o.strip() for o in raw.split(",") if o.strip() and o.strip() != "*"]
        settings = cls(
            cors_origins=origins,
            cookie_secure=os.environ.get("VOIZY_COOKIE_SECURE", "1") != "0",
            custom_roles=os.environ.get("VOIZY_ENABLE_ROLES") == "1",
        )
        if token := os.environ.get("VOIZY_SETUP_TOKEN"):
            settings.setup_token = token
        return settings
