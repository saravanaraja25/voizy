"""Code-defined permission registry. Roles are data; permissions are not."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Permission(StrEnum):
    AGENTS_READ = "agents:read"
    AGENTS_CREATE = "agents:create"
    AGENTS_EDIT = "agents:edit"
    AGENTS_PUBLISH = "agents:publish"
    AGENTS_ARCHIVE = "agents:archive"
    AGENTS_TEST = "agents:test"

    TOOLS_READ = "tools:read"
    TOOLS_MANAGE = "tools:manage"
    KB_READ = "kb:read"
    KB_MANAGE = "kb:manage"

    NUMBERS_READ = "numbers:read"
    NUMBERS_MANAGE = "numbers:manage"

    CALLS_READ = "calls:read"
    CALLS_VIEW_TRANSCRIPT = "calls:view_transcript"
    CALLS_VIEW_RECORDING = "calls:view_recording"
    CALLS_VIEW_PII = "calls:view_pii"
    CALLS_EXPORT = "calls:export"
    CALLS_DELETE = "calls:delete"
    CALLS_PLACE_OUTBOUND = "calls:place_outbound"

    CAMPAIGNS_READ = "campaigns:read"
    CAMPAIGNS_CREATE = "campaigns:create"
    CAMPAIGNS_RUN = "campaigns:run"
    CAMPAIGNS_MANAGE_CONTACTS = "campaigns:manage_contacts"
    POLICY_OVERRIDE = "policy:override"

    ANALYTICS_READ = "analytics:read"
    COSTS_READ = "costs:read"

    WEBHOOKS_MANAGE = "webhooks:manage"
    PROVIDER_KEYS_MANAGE = "provider_keys:manage"
    API_KEYS_MANAGE = "api_keys:manage"

    MEMBERS_MANAGE = "members:manage"
    ROLES_MANAGE = "roles:manage"
    SETTINGS_MANAGE = "settings:manage"
    AUDIT_READ = "audit:read"


ALL_PERMISSIONS: frozenset[Permission] = frozenset(Permission)

# Shown with a confirmation step in the UI when granted.
DANGEROUS_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.PROVIDER_KEYS_MANAGE,
        Permission.CALLS_VIEW_PII,
        Permission.CALLS_VIEW_RECORDING,
        Permission.CALLS_DELETE,
        Permission.ROLES_MANAGE,
        Permission.MEMBERS_MANAGE,
        Permission.POLICY_OVERRIDE,
        Permission.API_KEYS_MANAGE,
    }
)

SUPERADMIN_ROLE_NAME = "Superadmin"


@dataclass(frozen=True)
class SeedRole:
    name: str
    permissions: frozenset[Permission]
    is_locked: bool = False


_P = Permission

SEED_ROLES: tuple[SeedRole, ...] = (
    SeedRole(SUPERADMIN_ROLE_NAME, ALL_PERMISSIONS, is_locked=True),
    SeedRole("Admin", ALL_PERMISSIONS - {_P.ROLES_MANAGE}),
    SeedRole(
        "Builder",
        frozenset(
            {
                _P.AGENTS_READ,
                _P.AGENTS_CREATE,
                _P.AGENTS_EDIT,
                _P.AGENTS_PUBLISH,
                _P.AGENTS_ARCHIVE,
                _P.AGENTS_TEST,
                _P.TOOLS_READ,
                _P.TOOLS_MANAGE,
                _P.KB_READ,
                _P.KB_MANAGE,
                _P.NUMBERS_READ,
                _P.CALLS_READ,
                _P.CALLS_VIEW_TRANSCRIPT,
                _P.ANALYTICS_READ,
            }
        ),
    ),
    SeedRole(
        "Operator",
        frozenset(
            {
                _P.AGENTS_READ,
                _P.NUMBERS_READ,
                _P.CALLS_READ,
                _P.CALLS_VIEW_TRANSCRIPT,
                _P.CALLS_VIEW_RECORDING,
                _P.CALLS_VIEW_PII,
                _P.CALLS_PLACE_OUTBOUND,
                _P.CAMPAIGNS_READ,
                _P.CAMPAIGNS_CREATE,
                _P.CAMPAIGNS_RUN,
                _P.CAMPAIGNS_MANAGE_CONTACTS,
                _P.ANALYTICS_READ,
            }
        ),
    ),
    SeedRole(
        "Analyst",
        frozenset(
            {
                _P.AGENTS_READ,
                _P.CALLS_READ,
                _P.CALLS_VIEW_TRANSCRIPT,
                _P.CAMPAIGNS_READ,
                _P.ANALYTICS_READ,
                _P.COSTS_READ,
            }
        ),
    ),
)
