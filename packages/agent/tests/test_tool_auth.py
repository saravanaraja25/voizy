"""Tool credentials: injected from the secret store, only where they are allowed to go."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from voizy_agent.devtools.mock_clinic import DEV_API_KEY as CLINIC_KEY
from voizy_agent.http_tool import HttpToolExecutor
from voizy_core.domain.agent_config import HttpTool
from voizy_core.security.ssrf import SsrfPolicy
from voizy_core.services.secrets_store import ResolvedSecret

pytestmark = pytest.mark.asyncio
DEV = SsrfPolicy(allow_loopback=True)


def tool(port: int, auth: dict[str, Any] | None, path: str = "/whoami", **over: object) -> HttpTool:
    fields: dict[str, object] = {
        "name": "t",
        "description": "d",
        "url": f"http://127.0.0.1:{port}{path}",
        "method": "GET",
        "auth": auth,
        **over,
    }
    return HttpTool.model_validate(fields)


def resolver(value: str | None, hosts: tuple[str, ...] = ("127.0.0.1",)) -> Any:
    async def resolve(name: str) -> ResolvedSecret | None:
        return None if value is None else ResolvedSecret(value, hosts)

    return resolve


def hits(app: FastAPI) -> list[str]:
    return list(app.state.hits)


@pytest.mark.parametrize(
    ("auth", "value", "scheme"),
    [
        ({"kind": "bearer", "secret": "k"}, CLINIC_KEY, "bearer"),
        ({"kind": "header", "secret": "k", "header_name": "X-Api-Key"}, CLINIC_KEY, "header"),
        ({"kind": "basic", "secret": "k"}, f"clinic:{CLINIC_KEY}", "basic"),
    ],
)
async def test_each_scheme_authenticates(
    secure_clinic_port: int, auth: dict[str, Any], value: str, scheme: str
) -> None:
    r = await HttpToolExecutor(DEV).execute(tool(secure_clinic_port, auth), {}, resolver(value))
    assert r.ok and scheme in r.text


async def test_without_auth_the_secured_backend_rejects_the_call(secure_clinic_port: int) -> None:
    r = await HttpToolExecutor(DEV).execute(tool(secure_clinic_port, None), {}, None)
    assert not r.ok and r.status == 401


async def test_a_wrong_secret_is_a_clean_failure_that_never_echoes_it(
    secure_clinic_port: int,
) -> None:
    bad = "definitely-the-wrong-key-xyz"
    r = await HttpToolExecutor(DEV).execute(
        tool(secure_clinic_port, {"kind": "bearer", "secret": "k"}), {}, resolver(bad)
    )
    assert not r.ok and r.status == 401
    assert bad not in r.text and CLINIC_KEY not in r.text


async def test_a_missing_secret_fails_before_any_request_is_made(
    secure_clinic_port: int, secure_clinic_app: FastAPI
) -> None:
    before = len(hits(secure_clinic_app))
    auth = {"kind": "bearer", "secret": "k"}
    none_found = await HttpToolExecutor(DEV).execute(
        tool(secure_clinic_port, auth), {}, resolver(None)
    )
    no_resolver = await HttpToolExecutor(DEV).execute(tool(secure_clinic_port, auth), {}, None)
    for r in (none_found, no_resolver):
        assert not r.ok and r.text == "the tool's credential is not configured"
    assert len(hits(secure_clinic_app)) == before  # nothing was sent


async def test_a_credential_is_never_sent_to_a_host_it_is_not_allowed_for(
    secure_clinic_port: int, secure_clinic_app: FastAPI
) -> None:
    """The exfiltration case: someone repoints a tool at a server they control."""
    before = len(hits(secure_clinic_app))
    r = await HttpToolExecutor(DEV).execute(
        tool(secure_clinic_port, {"kind": "bearer", "secret": "k"}),
        {},
        resolver(CLINIC_KEY, hosts=("api.somewhere-else.example",)),
    )
    assert not r.ok and "not allowed" in r.text
    assert (
        CLINIC_KEY not in r.text and "somewhere-else" not in r.text
    )  # no hint about allowed hosts
    assert len(hits(secure_clinic_app)) == before  # the key never left the process


async def test_the_credential_is_not_forwarded_across_a_redirect(
    secure_clinic_port: int, secure_clinic_app: FastAPI
) -> None:
    r = await HttpToolExecutor(DEV).execute(
        tool(secure_clinic_port, {"kind": "bearer", "secret": "k"}, path="/redirect"),
        {},
        resolver(CLINIC_KEY),
    )
    assert not r.ok and r.status == 302 and "not followed" in r.text
    assert CLINIC_KEY not in r.text


async def test_wildcard_host_allowlists_work_for_subdomains(secure_clinic_port: int) -> None:
    # localhost is not a subdomain of anything, so a wildcard for another domain must not match.
    r = await HttpToolExecutor(DEV).execute(
        tool(secure_clinic_port, {"kind": "bearer", "secret": "k"}),
        {},
        resolver(CLINIC_KEY, hosts=("*.example.com",)),
    )
    assert not r.ok and "not allowed" in r.text


async def test_post_bodies_still_work_with_auth(secure_clinic_port: int) -> None:
    t = tool(
        secure_clinic_port, {"kind": "bearer", "secret": "k"}, path="/appointments", method="POST"
    )
    body = {"name": "Sam", "phone": "5559990000", "date": "2026-11-11", "time": "09:00"}
    r = await HttpToolExecutor(DEV).execute(t, body, resolver(CLINIC_KEY))
    assert r.ok and "BS-" in r.text
