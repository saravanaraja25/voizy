"""The default mode: one role (Superadmin) and superadmin-only invitations."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

import httpx
import psycopg
import pytest_asyncio
from psycopg_pool import AsyncConnectionPool
from voizy_api.app import create_app
from voizy_api.settings import Settings
from voizy_api.testing import DASHBOARD_ORIGIN, SETUP_TOKEN
from voizy_core.domain.permissions import ALL_PERMISSIONS

PASSWORD = "correct horse battery staple"  # noqa: S105 - test value
Maker = Callable[[], httpx.AsyncClient]


@pytest_asyncio.fixture
async def make(pool: AsyncConnectionPool) -> AsyncIterator[Maker]:
    settings = Settings(
        cors_origins=[DASHBOARD_ORIGIN], cookie_secure=False, setup_token=SETUP_TOKEN
    )
    assert settings.custom_roles is False  # the default
    app = create_app(pool, settings=settings)
    made: list[httpx.AsyncClient] = []

    def factory() -> httpx.AsyncClient:
        c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        made.append(c)
        return c

    yield factory
    for c in made:
        await c.aclose()


async def setup(make: Maker) -> tuple[httpx.AsyncClient, dict[str, str]]:
    c = make()
    r = await c.post(
        "/v1/setup",
        json={
            "setup_token": SETUP_TOKEN,
            "workspace_name": "Acme",
            "email": "owner@example.com",
            "display_name": "Owner",
            "password": PASSWORD,
        },
    )
    assert r.status_code == 201, r.text
    return c, {"X-CSRF-Token": r.json()["csrf_token"]}


async def test_a_new_workspace_has_exactly_one_role(
    make: Maker, fresh_instance: None, admin: psycopg.Connection
) -> None:
    owner, _ = await setup(make)
    workspace = (await owner.get("/v1/me")).json()["workspace_id"]
    rows = admin.execute(
        "SELECT name, is_locked FROM roles WHERE workspace_id = %s", (workspace,)
    ).fetchall()
    assert rows == [("Superadmin", True)]


async def test_role_management_routes_are_not_mounted(make: Maker, fresh_instance: None) -> None:
    c, h = await setup(make)
    for method, path in (
        ("GET", "/v1/roles"),
        ("POST", "/v1/roles"),
        ("GET", "/v1/permissions"),
        ("GET", "/v1/assignable-roles"),
        ("PUT", "/v1/members/00000000-0000-0000-0000-000000000000/role"),
    ):
        r = await c.request(method, path, headers=h, json={})
        assert r.status_code == 404, (method, path)


async def test_invites_need_only_an_email_and_create_superadmins(
    make: Maker, fresh_instance: None
) -> None:
    owner, h = await setup(make)
    inv = await owner.post("/v1/invites", headers=h, json={"email": "Two@Example.com"})
    assert inv.status_code == 201 and inv.json()["role_name"] == "Superadmin"

    joiner = make()
    r = await joiner.post(
        f"/v1/invites/{inv.json()['token']}/accept",
        json={"display_name": "Two", "password": PASSWORD},
    )
    assert r.status_code == 201
    assert set(r.json()["permissions"]) == {p.value for p in ALL_PERMISSIONS}
    members = (await owner.get("/v1/members")).json()
    assert [(m["email"], m["role_name"]) for m in members] == [
        ("owner@example.com", "Superadmin"),
        ("two@example.com", "Superadmin"),
    ]


async def test_asking_for_any_other_role_is_refused(make: Maker, fresh_instance: None) -> None:
    owner, h = await setup(make)
    r = await owner.post(
        "/v1/invites",
        headers=h,
        json={"email": "x@example.com", "role_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert r.status_code == 422 and "superadmin" in r.json()["detail"].lower()


async def test_the_last_superadmin_rule_still_holds(make: Maker, fresh_instance: None) -> None:
    owner, h = await setup(make)
    me = (await owner.get("/v1/me")).json()["user_id"]
    assert (await owner.delete(f"/v1/members/{me}", headers=h)).status_code == 403

    inv = (await owner.post("/v1/invites", headers=h, json={"email": "two@example.com"})).json()
    second = make()
    joined = await second.post(
        f"/v1/invites/{inv['token']}/accept", json={"display_name": "T", "password": PASSWORD}
    )
    h2 = {"X-CSRF-Token": joined.json()["csrf_token"]}
    # With two superadmins, either can remove the other; the survivor can never be removed.
    assert (
        await owner.delete(f"/v1/members/{joined.json()['user_id']}", headers=h)
    ).status_code == 204
    assert (await owner.delete(f"/v1/members/{me}", headers=h)).status_code == 403
    assert (await second.get("/v1/me")).status_code == 401  # the removed one is signed out
    assert h2


async def test_the_flag_turns_custom_roles_back_on(
    pool: AsyncConnectionPool, fresh_instance: None
) -> None:
    app = create_app(
        pool,
        settings=Settings(cookie_secure=False, setup_token=SETUP_TOKEN, custom_roles=True),
    )
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    r = await c.post(
        "/v1/setup",
        json={
            "setup_token": SETUP_TOKEN,
            "workspace_name": "Acme",
            "email": "owner@example.com",
            "display_name": "Owner",
            "password": PASSWORD,
        },
    )
    assert r.status_code == 201
    roles = (await c.get("/v1/roles")).json()
    assert {x["name"] for x in roles} == {"Superadmin", "Admin", "Builder", "Operator", "Analyst"}
    await c.aclose()
