"""'Test connection' for each integration. Each makes one cheap authenticated read-only call.

Messages are written for the operator and never contain a key, a response body or an exception.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx
from livekit import api as livekit_api
from voizy_core.security.ssrf import STRICT, SsrfError, SsrfPolicy, resolve_safe

TIMEOUT_S = 10.0


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    message: str


Checker = Callable[[str, dict[str, str]], Awaitable[CheckResult]]


async def _livekit(values: dict[str, str], policy: SsrfPolicy) -> CheckResult:
    url = values["livekit_url"].replace("wss://", "https://", 1)
    try:  # the URL is operator-supplied, so it gets the same destination checks as tool calls
        await asyncio.to_thread(resolve_safe, url, policy=policy)
    except SsrfError:
        return CheckResult(False, "That URL points somewhere Voizy is not allowed to connect to.")
    try:
        async with livekit_api.LiveKitAPI(
            url, values["livekit_api_key"], values["livekit_api_secret"]
        ) as lk:
            await asyncio.wait_for(lk.room.list_rooms(livekit_api.ListRoomsRequest()), TIMEOUT_S)
    except livekit_api.TwirpError as exc:
        if exc.status in (401, 403) or exc.code in ("unauthenticated", "permission_denied"):
            return CheckResult(False, "LiveKit rejected the API key or secret.")
        return CheckResult(False, f"LiveKit answered with an error ({exc.status}).")
    except (TimeoutError, OSError):
        return CheckResult(False, "Could not reach LiveKit at that URL.")
    except Exception:  # noqa: BLE001 - any other client failure is still just "could not verify"
        return CheckResult(False, "Could not verify the connection to LiveKit.")
    return CheckResult(True, "Connected to LiveKit.")


async def _http_check(
    client: httpx.AsyncClient, name: str, url: str, *, ok_message: str, **kwargs: object
) -> CheckResult:
    try:
        r = await client.get(url, timeout=TIMEOUT_S, follow_redirects=False, **kwargs)  # type: ignore[arg-type]
    except httpx.TimeoutException:
        return CheckResult(False, f"{name} did not answer in time.")
    except httpx.HTTPError:
        return CheckResult(False, f"Could not reach {name}.")
    if r.status_code == 200:
        return CheckResult(True, ok_message)
    if r.status_code in (400, 401, 403):
        return CheckResult(False, f"{name} rejected the credentials.")
    return CheckResult(False, f"{name} answered with an unexpected status ({r.status_code}).")


async def _twilio(client: httpx.AsyncClient, values: dict[str, str]) -> CheckResult:
    sid = values["twilio_account_sid"]
    try:
        r = await client.get(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}.json",
            auth=(sid, values["twilio_auth_token"]),
            timeout=TIMEOUT_S,
            follow_redirects=False,
        )
    except httpx.TimeoutException:
        return CheckResult(False, "Twilio did not answer in time.")
    except httpx.HTTPError:
        return CheckResult(False, "Could not reach Twilio.")
    if r.status_code == 401:
        return CheckResult(False, "Twilio rejected the credentials.")
    if r.status_code != 200:
        return CheckResult(False, f"Twilio answered with an unexpected status ({r.status_code}).")
    status = (
        r.json().get("status")
        if r.headers.get("content-type", "").startswith("application/json")
        else None
    )
    if status != "active":
        return CheckResult(False, f"The Twilio account is {status or 'not active'}.")
    return CheckResult(True, "Connected to Twilio; the account is active.")


def make_checker(
    http: httpx.AsyncClient | None = None, ssrf_policy: SsrfPolicy = STRICT
) -> Checker:
    async def check(integration_id: str, values: dict[str, str]) -> CheckResult:
        client = http or httpx.AsyncClient()
        try:
            if integration_id == "livekit":
                return await _livekit(values, ssrf_policy)
            if integration_id == "twilio":
                return await _twilio(client, values)
            if integration_id == "openai":
                return await _http_check(
                    client,
                    "OpenAI",
                    "https://api.openai.com/v1/models",
                    ok_message="OpenAI accepted the key.",
                    headers={"Authorization": f"Bearer {values['openai_api_key']}"},
                )
            if integration_id == "google":
                return await _http_check(
                    client,
                    "Google AI",
                    "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1",
                    ok_message="Google AI accepted the key.",
                    headers={"x-goog-api-key": values["google_api_key"]},
                )
            if integration_id == "deepgram":
                return await _http_check(
                    client,
                    "Deepgram",
                    "https://api.deepgram.com/v1/projects",
                    ok_message="Deepgram accepted the key.",
                    headers={"Authorization": f"Token {values['deepgram_api_key']}"},
                )
            if integration_id == "cartesia":
                return await _http_check(
                    client,
                    "Cartesia",
                    "https://api.cartesia.ai/voices?limit=1",
                    ok_message="Cartesia accepted the key.",
                    headers={
                        "X-API-Key": values["cartesia_api_key"],
                        "Cartesia-Version": "2025-04-16",
                    },
                )
            return CheckResult(False, "This integration cannot be tested.")
        finally:
            if http is None:
                await client.aclose()

    return check
