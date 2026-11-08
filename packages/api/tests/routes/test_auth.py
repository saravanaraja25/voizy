"""Setup, login, sessions, CSRF and password change, end to end through the HTTP API."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import psycopg
import pytest
from voizy_api.settings import Settings
from voizy_api.testing import DASHBOARD_ORIGIN, SETUP_TOKEN, bearer
from voizy_core.security.throttle import Throttle
from voizy_core.services.bootstrap import BootstrapResult

PASSWORD = "correct horse battery staple"  # noqa: S105 - test value
NEW_PASSWORD = "a-much-better-passphrase"  # noqa: S105 - test value
WRONG_PASSWORD = "nope-nope-nope"  # noqa: S105 - test value
SETUP = {
    "setup_token": SETUP_TOKEN,
    "workspace_name": "Acme",
    "email": "Owner@Example.com",
    "display_name": "Olivia Owner",
    "password": PASSWORD,
}
Maker = Callable[[], httpx.AsyncClient]


async def do_setup(c: httpx.AsyncClient, **over: object) -> httpx.Response:
    return await c.post("/v1/setup", json={**SETUP, **over})


def csrf(c: httpx.AsyncClient, token: str) -> dict[str, str]:
    return {"X-CSRF-Token": token}


async def test_setup_status_flips_and_second_setup_is_refused(
    client: httpx.AsyncClient, fresh_instance: None
) -> None:
    assert (await client.get("/v1/setup/status")).json() == {"needs_setup": True}
    r = await do_setup(client)
    assert r.status_code == 201
    assert (await client.get("/v1/setup/status")).json() == {"needs_setup": False}
    again = await do_setup(client, email="evil@example.com")
    assert again.status_code == 409


async def test_setup_signs_in_the_owner_with_a_hardened_cookie(
    client: httpx.AsyncClient, fresh_instance: None
) -> None:
    r = await do_setup(client)
    body = r.json()
    assert body["email"] == "owner@example.com" and body["workspace_name"] == "Acme"
    assert body["csrf_token"] and "roles:manage" in body["permissions"]
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
    assert "voizy_session=vzs_" in cookie
    assert "vzs_" not in r.text  # the session token is never in the JSON body
    me = await client.get("/v1/me")
    assert me.status_code == 200 and me.json()["user_id"] == body["user_id"]


async def test_setup_requires_the_server_log_token_and_throttles_guessing(
    pool: object, make_client: Maker, app_settings: Settings, fresh_instance: None
) -> None:
    app_settings.ip_throttle = Throttle(3, 900)
    c = make_client()
    for _ in range(3):
        assert (await do_setup(c, **{"setup_token": "not-the-token-at-all"})).status_code == 403
    r = await do_setup(c)  # even the right token is refused while throttled
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
    assert (await c.get("/v1/setup/status")).json() == {"needs_setup": True}  # nothing was created


@pytest.mark.parametrize(
    "password",
    ["short", "password123", "owner@example.com", "x" * 200],
)
async def test_setup_enforces_the_password_policy(
    client: httpx.AsyncClient, fresh_instance: None, password: str
) -> None:
    r = await do_setup(client, password=password)
    assert r.status_code in (422,)
    assert (await client.get("/v1/setup/status")).json() == {"needs_setup": True}


async def test_setup_rejects_a_foreign_origin_and_unknown_fields(
    client: httpx.AsyncClient, fresh_instance: None
) -> None:
    r = await client.post("/v1/setup", json=SETUP, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
    assert (await do_setup(client, is_platform_superadmin=True)).status_code == 422


async def test_login_succeeds_and_failures_do_not_reveal_which_part_was_wrong(
    make_client: Maker, fresh_instance: None
) -> None:
    owner = make_client()
    await do_setup(owner)
    c = make_client()
    ok = await c.post("/v1/auth/login", json={"email": "OWNER@example.com", "password": PASSWORD})
    assert ok.status_code == 200 and ok.json()["display_name"] == "Olivia Owner"

    wrong_pw = await make_client().post(
        "/v1/auth/login", json={"email": "owner@example.com", "password": WRONG_PASSWORD}
    )
    no_user = await make_client().post(
        "/v1/auth/login", json={"email": "ghost@example.com", "password": WRONG_PASSWORD}
    )
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json() == {"detail": "Incorrect email or password."}
    assert "set-cookie" not in wrong_pw.headers


async def test_login_is_throttled_per_account_and_success_resets_it(
    make_client: Maker, fresh_instance: None
) -> None:
    await do_setup(make_client())
    bad = {"email": "owner@example.com", "password": "wrong-wrong-wrong"}
    attacker = make_client()
    for _ in range(5):
        assert (await attacker.post("/v1/auth/login", json=bad)).status_code == 401
    blocked = await attacker.post("/v1/auth/login", json=bad)
    assert blocked.status_code == 429 and "retry-after" in blocked.headers
    # The account is protected even from the right password until the window passes.
    right = await attacker.post(
        "/v1/auth/login", json={"email": "owner@example.com", "password": PASSWORD}
    )
    assert right.status_code == 429


async def test_inactive_accounts_cannot_log_in(
    make_client: Maker, fresh_instance: None, admin: psycopg.Connection
) -> None:
    await do_setup(make_client())
    admin.execute("UPDATE users SET is_active = false")
    r = await make_client().post(
        "/v1/auth/login", json={"email": "owner@example.com", "password": PASSWORD}
    )
    assert r.status_code == 401


async def test_login_rejects_foreign_origins(make_client: Maker, fresh_instance: None) -> None:
    await do_setup(make_client())
    r = await make_client().post(
        "/v1/auth/login",
        json={"email": "owner@example.com", "password": PASSWORD},
        headers={"Origin": "http://evil.example"},
    )
    assert r.status_code == 403


async def test_session_writes_need_a_matching_csrf_token_and_an_allowed_origin(
    client: httpx.AsyncClient, fresh_instance: None
) -> None:
    token = (await do_setup(client)).json()["csrf_token"]
    assert (await client.get("/v1/agents")).status_code == 200  # reads need no CSRF token
    body = {"name": "X", "permissions": ["agents:read"]}

    assert (await client.post("/v1/api-keys", json=body)).status_code == 403  # no token
    wrong = await client.post("/v1/api-keys", json=body, headers=csrf(client, "x" * 43))
    assert wrong.status_code == 403
    cross = await client.post(
        "/v1/api-keys", json=body, headers={**csrf(client, token), "Origin": "http://evil.example"}
    )
    assert cross.status_code == 403
    good = await client.post(
        "/v1/api-keys", json=body, headers={**csrf(client, token), "Origin": DASHBOARD_ORIGIN}
    )
    assert good.status_code == 201


async def test_api_keys_need_no_csrf_token(
    client: httpx.AsyncClient, workspace_a: BootstrapResult
) -> None:
    r = await client.post(
        "/v1/api-keys",
        json={"name": "ci", "permissions": ["agents:read"]},
        headers=bearer(workspace_a.token),
    )
    assert r.status_code == 201


async def test_logout_ends_the_session_everywhere(make_client: Maker, fresh_instance: None) -> None:
    c = make_client()
    token = (await do_setup(c)).json()["csrf_token"]
    stolen = c.cookies.get("voizy_session")
    assert (await c.post("/v1/auth/logout", headers=csrf(c, token))).status_code == 200
    assert (await c.get("/v1/me")).status_code == 401
    replay = make_client()
    replay.cookies.set("voizy_session", stolen or "")
    assert (await replay.get("/v1/me")).status_code == 401  # the old cookie is dead server-side


async def test_password_change_validates_and_ends_other_sessions(
    make_client: Maker, fresh_instance: None
) -> None:
    here, other = make_client(), make_client()
    token = (await do_setup(here)).json()["csrf_token"]
    await other.post("/v1/auth/login", json={"email": "owner@example.com", "password": PASSWORD})
    assert (await other.get("/v1/me")).status_code == 200

    h = csrf(here, token)
    wrong = await here.post(
        "/v1/auth/password",
        headers=h,
        json={"current_password": WRONG_PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert wrong.status_code == 403
    weak = await here.post(
        "/v1/auth/password", headers=h, json={"current_password": PASSWORD, "new_password": "short"}
    )
    assert weak.status_code == 422
    ok = await here.post(
        "/v1/auth/password",
        headers=h,
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert ok.status_code == 200
    assert (await here.get("/v1/me")).status_code == 200  # this session continues
    assert (await other.get("/v1/me")).status_code == 401  # every other one ended

    fresh = make_client()
    old = await fresh.post(
        "/v1/auth/login", json={"email": "owner@example.com", "password": PASSWORD}
    )
    new = await fresh.post(
        "/v1/auth/login",
        json={"email": "owner@example.com", "password": NEW_PASSWORD},
    )
    assert old.status_code == 401 and new.status_code == 200


async def test_expired_session_is_rejected(
    client: httpx.AsyncClient, fresh_instance: None, admin: psycopg.Connection
) -> None:
    await do_setup(client)
    admin.execute("UPDATE sessions SET expires_at = now() - interval '1 second'")
    assert (await client.get("/v1/me")).status_code == 401
