import pytest
from voizy_core.domain.permissions import ALL_PERMISSIONS, SEED_ROLES, Permission
from voizy_core.security.authz import (
    AuthzError,
    RoleView,
    api_key_permissions,
    can,
    check_can_assign_role,
    check_can_edit_role,
    check_can_grant,
    check_member_change_keeps_owner,
    parse_permissions,
)

P = Permission
SUPER = RoleView("r-super", "Superadmin", ALL_PERMISSIONS, is_locked=True)
BUILDER = RoleView("r-b", "Builder", frozenset({P.AGENTS_READ, P.AGENTS_EDIT}))
ADMIN = RoleView("r-a", "Admin", ALL_PERMISSIONS - {P.ROLES_MANAGE})


def test_seed_roles_only_use_known_permissions_and_superadmin_is_locked_and_full() -> None:
    names = {r.name for r in SEED_ROLES}
    assert {"Superadmin", "Admin", "Builder", "Operator", "Analyst"} == names
    superadmin = next(r for r in SEED_ROLES if r.name == "Superadmin")
    assert superadmin.is_locked and superadmin.permissions == ALL_PERMISSIONS


def test_can() -> None:
    assert can(BUILDER.permissions, P.AGENTS_EDIT)
    assert not can(BUILDER.permissions, P.AGENTS_PUBLISH)


def test_cannot_grant_permission_you_do_not_hold() -> None:
    with pytest.raises(AuthzError, match="agents:publish"):
        check_can_grant(BUILDER.permissions, frozenset({P.AGENTS_EDIT, P.AGENTS_PUBLISH}))


def test_can_grant_subset() -> None:
    check_can_grant(BUILDER.permissions, frozenset({P.AGENTS_READ}))


def test_cannot_edit_locked_role_even_as_superadmin() -> None:
    with pytest.raises(AuthzError, match="locked"):
        check_can_edit_role(ALL_PERMISSIONS, SUPER)


def test_cannot_edit_role_that_outranks_you() -> None:
    with pytest.raises(AuthzError, match="outranks"):
        check_can_edit_role(BUILDER.permissions, ADMIN)


def test_admin_without_roles_manage_cannot_assign_superadmin() -> None:
    with pytest.raises(AuthzError, match="outranks"):
        check_can_assign_role(ADMIN.permissions, SUPER)


def test_unknown_permission_string_rejected() -> None:
    with pytest.raises(AuthzError, match="unknown permission"):
        parse_permissions(["agents:read", "agents:everything"])


def test_last_superadmin_cannot_be_removed_or_demoted() -> None:
    members = {"u1": SUPER, "u2": BUILDER}
    with pytest.raises(AuthzError, match="at least one superadmin"):
        check_member_change_keeps_owner(members, "u1", None)
    with pytest.raises(AuthzError, match="at least one superadmin"):
        check_member_change_keeps_owner(members, "u1", BUILDER)


def test_superadmin_can_be_demoted_when_another_exists() -> None:
    members = {"u1": SUPER, "u2": SUPER}
    check_member_change_keeps_owner(members, "u1", BUILDER)


def test_non_superadmin_changes_are_unrestricted_by_owner_rule() -> None:
    check_member_change_keeps_owner({"u1": SUPER, "u2": BUILDER}, "u2", None)


def test_api_key_cannot_exceed_creator() -> None:
    with pytest.raises(AuthzError):
        api_key_permissions(BUILDER.permissions, frozenset({P.PROVIDER_KEYS_MANAGE}))
    assert api_key_permissions(BUILDER.permissions, frozenset({P.AGENTS_READ})) == {P.AGENTS_READ}


def test_default_roles_are_just_the_superadmin_and_templates_stay_available() -> None:
    from voizy_core.domain.permissions import DEFAULT_ROLES

    assert [r.name for r in DEFAULT_ROLES] == ["Superadmin"]
    assert DEFAULT_ROLES[0].permissions == ALL_PERMISSIONS and DEFAULT_ROLES[0].is_locked
    assert {r.name for r in SEED_ROLES} - {"Superadmin"} == {
        "Admin",
        "Builder",
        "Operator",
        "Analyst",
    }
