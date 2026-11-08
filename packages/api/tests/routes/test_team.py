"""Invitations and members over HTTP, with the escalation rules."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import psycopg
import pytest
from voizy_api.testing import SETUP_TOKEN
from voizy_core.services.bootstrap import BootstrapResult

PASSWORD = "correct horse battery staple"  # noqa: S105 - test value
Maker = Callable[[], httpx.AsyncClient]


class Person:
    """A signed-in client plus its CSRF header."""

    def __init__(self, client: httpx.AsyncClient, csrf: str, user_id: str) -> None:
        self.c, self.h, self.user_id = client, {"X-CSRF-Token": csrf}, user_id

    async def post(self, path: str, **kw: object) -> httpx.Response:
        return await self.c.post(path, headers=self.h, **kw)  # type: ignore[arg-type]

    async def put(self, path: str, **kw: object) -> httpx.Response:
        return await self.c.put(path, headers=self.h, **kw)  # type: ignore[arg-type]

    async def delete(self, path: str) -> httpx.Response:
        return await self.c.delete(path, headers=self.h)

    async def get(self, path: str) -> httpx.Response:
        return await self.c.get(path)


async def owner(make: Maker) -> Person:
    c = make()
    r = await c.post(
        "/v1/setup",
        json={
            "setup_token": SETUP_TOKEN,
            "workspace_name": "Acme",
            "email": "owner@example.com",
            "display_name": "Olivia Owner",
            "password": PASSWORD,
        },
    )
    assert r.status_code == 201, r.text
    return Person(c, r.json()["csrf_token"], r.json()["user_id"])


async def role_id(p: Person, name: str) -> str:
    roles = (await p.get("/v1/roles")).json()
    return str(next(r["id"] for r in roles if r["name"] == name))


async def join(make: Maker, boss: Person, email: str, role: str) -> Person:
    """Invite by email, accept as a new user, return that user signed in."""
    inv = await boss.post(
        "/v1/invites", json={"email": email, "role_id": await role_id(boss, role)}
    )
    assert inv.status_code == 201, inv.text
    c = make()
    r = await c.post(
        f"/v1/invites/{inv.json()['token']}/accept",
        json={"display_name": email.split("@")[0], "password": PASSWORD},
    )
    assert r.status_code == 201, r.text
    return Person(c, r.json()["csrf_token"], r.json()["user_id"])


async def test_invite_lifecycle_and_the_new_members_role(
    make_client: Maker, fresh_instance: None
) -> None:
    boss = await owner(make_client)
    inv = await boss.post(
        "/v1/invites", json={"email": "New@Example.com", "role_id": await role_id(boss, "Builder")}
    )
    body = inv.json()
    assert inv.status_code == 201 and body["email"] == "new@example.com"
    assert body["invite_path"] == f"/invite/{body['token']}" and body["token"].startswith("vzi_")

    pending = (await boss.get("/v1/invites")).json()
    assert [i["email"] for i in pending] == ["new@example.com"]
    assert "token" not in pending[0]  # the secret is never listed again

    stranger = make_client()  # the invitee has no account or session yet
    preview = await stranger.get(f"/v1/invites/{body['token']}")
    assert preview.json()["workspace_name"] == "Acme" and preview.json()["role_name"] == "Builder"

    accepted = await stranger.post(
        f"/v1/invites/{body['token']}/accept",
        json={"display_name": "Newbie", "password": PASSWORD},
    )
    assert accepted.status_code == 201 and accepted.json()["email"] == "new@example.com"
    assert "agents:publish" in accepted.json()["permissions"]
    assert "members:manage" not in accepted.json()["permissions"]

    members = (await boss.get("/v1/members")).json()
    assert [(m["email"], m["role_name"]) for m in members] == [
        ("owner@example.com", "Superadmin"),
        ("new@example.com", "Builder"),
    ]
    assert (await boss.get("/v1/invites")).json() == []
    # A Builder cannot manage the team.
    assert (await stranger.get("/v1/members")).status_code == 403


async def test_an_invite_link_works_once_and_dies_when_revoked(
    make_client: Maker, fresh_instance: None
) -> None:
    boss = await owner(make_client)
    rid = await role_id(boss, "Analyst")
    one = (await boss.post("/v1/invites", json={"email": "a@example.com", "role_id": rid})).json()
    two = (await boss.post("/v1/invites", json={"email": "b@example.com", "role_id": rid})).json()

    ok = await make_client().post(
        f"/v1/invites/{one['token']}/accept", json={"display_name": "A", "password": PASSWORD}
    )
    assert ok.status_code == 201
    reuse = await make_client().post(
        f"/v1/invites/{one['token']}/accept", json={"display_name": "A2", "password": PASSWORD}
    )
    assert reuse.status_code == 404

    assert (await boss.delete(f"/v1/invites/{two['id']}")).status_code == 204
    dead = await make_client().get(f"/v1/invites/{two['token']}")
    assert dead.status_code == 404
    assert (await boss.delete(f"/v1/invites/{two['id']}")).status_code == 404  # already revoked


async def test_invite_acceptance_enforces_the_password_policy_and_hides_unknown_links(
    make_client: Maker, fresh_instance: None
) -> None:
    boss = await owner(make_client)
    inv = (
        await boss.post(
            "/v1/invites",
            json={"email": "a@example.com", "role_id": await role_id(boss, "Analyst")},
        )
    ).json()
    weak = await make_client().post(
        f"/v1/invites/{inv['token']}/accept", json={"display_name": "A", "password": "short"}
    )
    assert weak.status_code == 422
    # The failed attempt did not burn the link.
    assert (await make_client().get(f"/v1/invites/{inv['token']}")).status_code == 200
    for bad in ("vzi_" + "A" * 43, "garbage", "vzi_short"):
        assert (await make_client().get(f"/v1/invites/{bad}")).status_code == 404


async def test_duplicate_pending_invites_are_refused(
    make_client: Maker, fresh_instance: None
) -> None:
    boss = await owner(make_client)
    body = {"email": "a@example.com", "role_id": await role_id(boss, "Analyst")}
    assert (await boss.post("/v1/invites", json=body)).status_code == 201
    assert (
        await boss.post("/v1/invites", json={**body, "email": "A@EXAMPLE.COM"})
    ).status_code == 409


async def test_nobody_can_invite_above_their_own_rank(
    make_client: Maker, fresh_instance: None
) -> None:
    boss = await owner(make_client)
    # A custom "Recruiter" role that can manage members but little else.
    made = await boss.post(
        "/v1/roles",
        json={"name": "Recruiter", "permissions": ["members:manage", "agents:read"]},
    )
    assert made.status_code == 201
    recruiter = await join(make_client, boss, "rec@example.com", "Recruiter")

    for too_high in ("Admin", "Builder", "Superadmin"):
        r = await recruiter.post(
            "/v1/invites",
            json={
                "email": f"{too_high.lower()}@example.com",
                "role_id": await role_id(boss, too_high),
            },
        )
        assert r.status_code == 403 and "outranks" in r.json()["detail"], too_high
    same = await recruiter.post(
        "/v1/invites",
        json={"email": "peer@example.com", "role_id": await role_id(boss, "Recruiter")},
    )
    assert same.status_code == 201


async def test_role_changes_respect_rank_and_apply_immediately(
    make_client: Maker, fresh_instance: None
) -> None:
    boss = await owner(make_client)
    builder = await join(make_client, boss, "b@example.com", "Builder")
    assert (await builder.post("/v1/agents", json={})).status_code in (
        403,
        422,
    )  # can build, body bad
    r = await boss.put(
        f"/v1/members/{builder.user_id}/role", json={"role_id": await role_id(boss, "Analyst")}
    )
    assert r.status_code == 200 and r.json()["role_name"] == "Analyst"
    # No re-login needed: permissions are read on every request.
    assert (await builder.post("/v1/agents", json={"name": "x"})).status_code == 403
    assert "agents:publish" not in (await builder.get("/v1/me")).json()["permissions"]


async def test_members_cannot_touch_someone_who_outranks_them_or_grant_above_themselves(
    make_client: Maker, fresh_instance: None
) -> None:
    boss = await owner(make_client)
    await boss.post("/v1/roles", json={"name": "Recruiter", "permissions": ["members:manage"]})
    recruiter = await join(make_client, boss, "rec@example.com", "Recruiter")
    victim = await join(make_client, boss, "v@example.com", "Analyst")

    # Cannot promote anyone above the recruiter's own permissions...
    up = await recruiter.put(
        f"/v1/members/{victim.user_id}/role", json={"role_id": await role_id(boss, "Admin")}
    )
    assert up.status_code == 403
    # ...and cannot demote or remove the superadmin who outranks them.
    down = await recruiter.put(
        f"/v1/members/{boss.user_id}/role", json={"role_id": await role_id(boss, "Recruiter")}
    )
    assert down.status_code == 403 and "outranks" in down.json()["detail"]
    assert (await recruiter.delete(f"/v1/members/{boss.user_id}")).status_code == 403


async def test_the_last_superadmin_cannot_be_demoted_or_removed(
    make_client: Maker, fresh_instance: None
) -> None:
    boss = await owner(make_client)
    demote = await boss.put(
        f"/v1/members/{boss.user_id}/role", json={"role_id": await role_id(boss, "Admin")}
    )
    assert demote.status_code == 403 and "superadmin" in demote.json()["detail"]
    leave = await boss.delete(f"/v1/members/{boss.user_id}")
    assert leave.status_code == 403
    assert (await boss.get("/v1/me")).status_code == 200  # still here

    # With a second superadmin, the first may step down.
    second = await join(make_client, boss, "two@example.com", "Superadmin")
    assert second.user_id
    assert (
        await boss.put(
            f"/v1/members/{boss.user_id}/role", json={"role_id": await role_id(boss, "Admin")}
        )
    ).status_code == 200


async def test_removing_a_member_ends_their_session_immediately(
    make_client: Maker, fresh_instance: None
) -> None:
    boss = await owner(make_client)
    guest = await join(make_client, boss, "g@example.com", "Analyst")
    assert (await guest.get("/v1/me")).status_code == 200
    assert (await boss.delete(f"/v1/members/{guest.user_id}")).status_code == 204
    assert (await guest.get("/v1/me")).status_code == 401
    assert (await boss.delete(f"/v1/members/{guest.user_id}")).status_code == 404
    login = await make_client().post(
        "/v1/auth/login", json={"email": "g@example.com", "password": PASSWORD}
    )
    assert login.status_code == 403  # the account exists but belongs to no workspace


async def test_team_endpoints_are_tenant_isolated(
    make_client: Maker, fresh_instance: None, workspace_a: BootstrapResult
) -> None:
    boss = await owner(make_client)
    other = make_client()  # the other workspace, via its bootstrap API key
    h = {"Authorization": f"Bearer {workspace_a.token}"}
    assert (await other.get("/v1/members", headers=h)).json() == []
    rid = await role_id(boss, "Analyst")
    cross = await other.post(
        "/v1/invites", headers=h, json={"email": "x@example.com", "role_id": rid}
    )
    assert cross.status_code == 404  # another workspace's role does not exist here
    assert (await other.delete(f"/v1/members/{boss.user_id}", headers=h)).status_code == 404


async def test_actions_are_audited_with_the_acting_user(
    make_client: Maker, fresh_instance: None, admin: psycopg.Connection
) -> None:
    boss = await owner(make_client)
    await join(make_client, boss, "b@example.com", "Builder")
    actions = admin.execute("SELECT action, actor_user_id FROM audit_log ORDER BY id").fetchall()
    assert [a for a, _ in actions] == ["workspace.setup", "invite.create", "invite.accept"]
    assert str(actions[1][1]) == boss.user_id


@pytest.mark.parametrize("path", ["/v1/members", "/v1/invites"])
async def test_team_endpoints_require_authentication(client: httpx.AsyncClient, path: str) -> None:
    assert (await client.get(path)).status_code == 401


async def test_assignable_roles_are_only_those_the_caller_may_grant(
    make_client: Maker, fresh_instance: None
) -> None:
    boss = await owner(make_client)
    everything = {r["name"] for r in (await boss.get("/v1/assignable-roles")).json()}
    assert everything == {"Superadmin", "Admin", "Builder", "Operator", "Analyst"}

    await boss.post("/v1/roles", json={"name": "Recruiter", "permissions": ["members:manage"]})
    recruiter = await join(make_client, boss, "rec@example.com", "Recruiter")
    mine = {r["name"] for r in (await recruiter.get("/v1/assignable-roles")).json()}
    assert mine == {"Recruiter"}  # nothing that carries a permission they lack
