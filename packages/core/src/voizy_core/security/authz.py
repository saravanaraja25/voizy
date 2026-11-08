"""Pure authorization rules: permission checks, escalation prevention, last-owner protection."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from voizy_core.domain.permissions import ALL_PERMISSIONS, Permission


class AuthzError(Exception):
    """Raised when an action would violate an authorization rule."""


@dataclass(frozen=True)
class RoleView:
    id: str
    name: str
    permissions: frozenset[Permission]
    is_locked: bool = False

    @property
    def is_superadmin(self) -> bool:
        return self.permissions == ALL_PERMISSIONS


def parse_permissions(values: Iterable[str]) -> frozenset[Permission]:
    """Parse untrusted permission strings; unknown values are rejected, never ignored."""
    parsed: set[Permission] = set()
    for value in values:
        try:
            parsed.add(Permission(value))
        except ValueError as exc:
            raise AuthzError(f"unknown permission: {value!r}") from exc
    return frozenset(parsed)


def can(held: frozenset[Permission], needed: Permission) -> bool:
    return needed in held


def check_can_grant(actor: frozenset[Permission], requested: frozenset[Permission]) -> None:
    """An actor may only grant permissions they hold themselves."""
    excess = requested - actor
    if excess:
        names = ", ".join(sorted(p.value for p in excess))
        raise AuthzError(f"cannot grant permissions you do not hold: {names}")


def check_can_edit_role(actor: frozenset[Permission], target: RoleView) -> None:
    """Editing or assigning a role requires holding every permission that role carries."""
    if target.is_locked:
        raise AuthzError(f"role {target.name!r} is locked")
    if not target.permissions <= actor:
        raise AuthzError(f"role {target.name!r} outranks you")


def check_can_assign_role(actor: frozenset[Permission], role: RoleView) -> None:
    """Assigning (not editing) is allowed for locked roles only to someone who holds them."""
    if not role.permissions <= actor:
        raise AuthzError(f"role {role.name!r} outranks you")


def check_member_change_keeps_owner(
    member_roles: dict[str, RoleView], user_id: str, new_role: RoleView | None
) -> None:
    """Block removal or demotion of the last superadmin. new_role=None means removal."""
    current = member_roles.get(user_id)
    if current is None or not current.is_superadmin:
        return
    if new_role is not None and new_role.is_superadmin:
        return
    others = [uid for uid, r in member_roles.items() if uid != user_id and r.is_superadmin]
    if not others:
        raise AuthzError("a workspace must keep at least one superadmin")


def api_key_permissions(
    creator: frozenset[Permission], requested: frozenset[Permission]
) -> frozenset[Permission]:
    """API keys can never exceed their creator; exceeding requests are rejected."""
    check_can_grant(creator, requested)
    return requested
