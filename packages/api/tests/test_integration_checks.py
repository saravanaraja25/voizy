"""The 'test connection' checks, against a mocked network. No real key or request is involved."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from livekit import api as livekit_api
from voizy_api import integration_checks as ic

VALUES: dict[str, dict[str, str]] = {
    "twilio": {"twilio_account_sid": "AC" + "a" * 32, "twilio_auth_token": "b" * 32},
    "openai": {"openai_api_key": "sk-" + "z" * 40},
    "google": {"google_api_key": "AIza" + "y" * 30},
    "deepgram": {"deepgram_api_key": "d" * 40},
    "cartesia": {"cartesia_api_key": "c" * 30},
}


def client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("name", ["openai", "google", "deepgram", "cartesia"])
async def test_provider_keys_pass_when_the_provider_says_ok(name: str) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": []})

    r = await ic.make_checker(client(handler))(name, VALUES[name])
    assert r.ok and "accepted the key" in r.message
    # The key travels in a header to the provider's own host, never in the URL.
    (req,) = seen
    secret = next(iter(VALUES[name].values()))
    assert secret not in str(req.url) and secret in " ".join(req.headers.values())


@pytest.mark.parametrize("name", ["openai", "google", "deepgram", "cartesia"])
@pytest.mark.parametrize("status", [400, 401, 403])
async def test_rejected_keys_are_reported_without_the_key(name: str, status: int) -> None:
    r = await ic.make_checker(client(lambda _: httpx.Response(status, text="secret in body?")))(
        name, VALUES[name]
    )
    assert not r.ok and "rejected the credentials" in r.message
    assert next(iter(VALUES[name].values())) not in r.message and "secret in body" not in r.message


@pytest.mark.parametrize("name", ["openai", "google", "deepgram", "cartesia", "twilio"])
async def test_unexpected_statuses_and_network_failures_are_plain(name: str) -> None:
    odd = await ic.make_checker(client(lambda _: httpx.Response(503)))(name, VALUES[name])
    assert not odd.ok and "unexpected status (503)" in odd.message

    def boom(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns failure for api.example")

    down = await ic.make_checker(client(boom))(name, VALUES[name])
    assert not down.ok and "Could not reach" in down.message and "dns failure" not in down.message

    def slow(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("took forever")

    late = await ic.make_checker(client(slow))(name, VALUES[name])
    assert not late.ok and "in time" in late.message


async def test_twilio_requires_an_active_account() -> None:
    def respond(status: str) -> Callable[[httpx.Request], httpx.Response]:
        return lambda _: httpx.Response(200, json={"status": status})

    ok = await ic.make_checker(client(respond("active")))("twilio", VALUES["twilio"])
    suspended = await ic.make_checker(client(respond("suspended")))("twilio", VALUES["twilio"])
    denied = await ic.make_checker(client(lambda _: httpx.Response(401)))(
        "twilio", VALUES["twilio"]
    )
    assert ok.ok and "active" in ok.message
    assert not suspended.ok and "suspended" in suspended.message
    assert not denied.ok and "rejected" in denied.message


async def test_twilio_uses_basic_auth_to_its_own_account_url() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"status": "active"})

    await ic.make_checker(client(handler))("twilio", VALUES["twilio"])
    (req,) = seen
    assert req.url.host == "api.twilio.com" and "/Accounts/AC" in req.url.path
    assert req.headers["authorization"].startswith("Basic ")
    assert VALUES["twilio"]["twilio_auth_token"] not in str(req.url)


async def test_redirects_are_not_followed_so_a_key_cannot_be_forwarded() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        return httpx.Response(302, headers={"location": "https://evil.example/steal"})

    r = await ic.make_checker(client(handler))("openai", VALUES["openai"])
    assert not r.ok and calls == ["api.openai.com"]


class _FakeLiveKit:
    """A stand-in for livekit.api.LiveKitAPI: records who connected and what they used."""

    behaviour: Callable[[], None] = staticmethod(lambda: None)
    created: list[tuple[str, str, str]] = []

    def __init__(self, url: str, key: str, secret: str) -> None:
        _FakeLiveKit.created.append((url, key, secret))
        self.room = self

    async def __aenter__(self) -> _FakeLiveKit:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def list_rooms(self, _: Any) -> None:
        _FakeLiveKit.behaviour()


LK = {
    "livekit_url": "wss://proj.livekit.cloud",
    "livekit_api_key": "APIkeyForTests1",
    "livekit_api_secret": "sekret-value-for-livekit-tests-0001",
}
PUBLIC = lambda host, port: ["93.184.216.34"]  # noqa: E731


async def test_livekit_connects_over_https_with_the_stored_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("voizy_api.integration_checks.livekit_api.LiveKitAPI", _FakeLiveKit)
    monkeypatch.setattr(ic, "resolve_safe", lambda url, policy: None)
    _FakeLiveKit.created.clear()
    _FakeLiveKit.behaviour = staticmethod(lambda: None)
    r = await ic.make_checker()("livekit", LK)
    assert r.ok and _FakeLiveKit.created == [
        ("https://proj.livekit.cloud", LK["livekit_api_key"], LK["livekit_api_secret"])
    ]


async def test_livekit_errors_are_mapped_to_plain_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("voizy_api.integration_checks.livekit_api.LiveKitAPI", _FakeLiveKit)
    monkeypatch.setattr(ic, "resolve_safe", lambda url, policy: None)

    def deny() -> None:
        raise livekit_api.TwirpError("unauthenticated", "invalid token", status=401)

    def unreachable() -> None:
        raise OSError("connection refused to 10.1.2.3")

    cases = [
        (deny, "rejected the API key or secret"),
        (unreachable, "Could not reach LiveKit"),
    ]
    for behaviour, expected in cases:
        _FakeLiveKit.behaviour = staticmethod(behaviour)
        r = await ic.make_checker()("livekit", LK)
        assert not r.ok and expected in r.message
        assert LK["livekit_api_secret"] not in r.message and "10.1.2.3" not in r.message


async def test_livekit_url_gets_the_same_destination_checks_as_tool_calls() -> None:
    # A real resolution of a private literal: refused before any connection is attempted.
    private = {**LK, "livekit_url": "wss://127.0.0.1"}
    r = await ic.make_checker()("livekit", private)
    assert not r.ok and "not allowed to connect" in r.message


async def test_unknown_integrations_cannot_be_tested() -> None:
    r = await ic.make_checker()("mystery", {})
    assert not r.ok
