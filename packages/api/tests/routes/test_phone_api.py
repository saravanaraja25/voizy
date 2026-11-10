"""Phone numbers and outbound calls, against fake Twilio and LiveKit SIP clients."""

from __future__ import annotations

import itertools
from typing import Any

import httpx
import psycopg
import pytest
from voizy_api.settings import Settings
from voizy_api.telephony import Telephony, TelephonyError
from voizy_api.testing import MakeKey, agent_body, bearer
from voizy_core.domain.dispatch import DispatchTarget
from voizy_core.domain.permissions import Permission
from voizy_core.security.throttle import Throttle
from voizy_core.services.bootstrap import BootstrapResult

pytestmark = pytest.mark.asyncio
NUMBER = "+14155550134"
OTHER = "+14155550199"


class FakeTwilio:
    def __init__(self, log: list[tuple[str, ...]]) -> None:
        self.log, self.n = log, itertools.count(1)
        self.urls: list[tuple[str, str]] = []

    async def find_number(self, e164: str) -> str:
        self.log.append(("twilio.find", e164))
        if e164 == "+19999999999":
            raise TelephonyError("+19999999999 is not a number in this Twilio account.")
        return f"PN{e164[-4:]}"

    async def create_trunk(self, friendly_name: str, domain_name: str) -> str:
        self.log.append(("twilio.create_trunk", domain_name))
        return "TK1"

    async def add_origination(self, trunk_sid: str, sip_url: str) -> None:
        self.log.append(("twilio.origination", sip_url))
        self.urls.append((f"OU{len(self.urls) + 1}", sip_url))

    async def list_origination_urls(self, trunk_sid: str) -> list[tuple[str, str]]:
        return list(self.urls)

    async def delete_origination(self, trunk_sid: str, origination_sid: str) -> None:
        self.log.append(("twilio.del_origination", origination_sid))
        self.urls = [u for u in self.urls if u[0] != origination_sid]

    async def create_credential_list(self, friendly_name: str) -> str:
        self.log.append(("twilio.cred_list",))
        return "CL1"

    async def attach_credential_list(self, trunk_sid: str, list_sid: str) -> None:
        self.log.append(("twilio.attach_list", trunk_sid, list_sid))

    async def add_credential(self, list_sid: str, username: str, password: str) -> str:
        self.log.append(("twilio.add_cred", username))
        return f"CR{next(self.n)}"

    async def delete_credential(self, list_sid: str, credential_sid: str) -> None:
        self.log.append(("twilio.del_cred", credential_sid))

    async def attach_number(self, trunk_sid: str, number_sid: str) -> None:
        self.log.append(("twilio.attach_number", number_sid))

    async def detach_number(self, trunk_sid: str, number_sid: str) -> None:
        self.log.append(("twilio.detach_number", number_sid))


class FakeSip:
    def __init__(self, log: list[tuple[str, ...]]) -> None:
        self.log, self.n, self.fail_outbound = log, itertools.count(1), False

    async def create_inbound(
        self, e164: str, target: DispatchTarget | None, allowed: tuple[str, ...]
    ) -> tuple[str, str]:
        self.log.append(("lk.inbound", e164, "agent" if target else "none"))
        return f"IT{next(self.n)}", ("RULE1" if target else "")

    async def create_outbound(self, e164: str, address: str, user: str, password: str) -> str:
        if self.fail_outbound:
            raise TelephonyError("LiveKit refused the outbound trunk.")
        self.log.append(("lk.outbound", e164, address))
        return f"OT{next(self.n)}"

    async def replace_rule(self, trunk_id: str, old_rule_id: str, target: DispatchTarget) -> str:
        self.log.append(("lk.replace_rule", trunk_id, old_rule_id))
        return "RULE2"

    async def remove_rule(self, rule_id: str) -> None:
        self.log.append(("lk.remove_rule", rule_id))

    async def delete_inbound(self, trunk_id: str, rule_id: str) -> None:
        self.log.append(("lk.del_inbound", trunk_id, rule_id))

    async def delete_outbound(self, trunk_id: str) -> None:
        self.log.append(("lk.del_outbound", trunk_id))

    async def dial(self, trunk_id: str, to: str, target: DispatchTarget) -> str:
        self.log.append(("lk.dial", trunk_id, to))
        return "out-room-1"


class Env:
    def __init__(self) -> None:
        self.log: list[tuple[str, ...]] = []
        self.sip = FakeSip(self.log)
        self.twilio = FakeTwilio(self.log)

    def names(self) -> list[str]:
        return [e[0] for e in self.log]


@pytest.fixture(autouse=True)
def _clean_between_tests(admin: psycopg.Connection) -> None:
    """Depending on `admin` truncates everything after each test (numbers are globally unique)."""


@pytest.fixture
def env(app_settings: Settings) -> Env:
    e = Env()
    app_settings.telephony_factory = lambda lk, tw: Telephony(
        twilio=e.twilio, sip=e.sip, sip_host="proj.sip.livekit.cloud"
    )
    app_settings.outbound_throttle = Throttle(3, 3600)
    return e


async def connect_providers(client: httpx.AsyncClient, h: dict[str, str]) -> None:
    lk = {
        "livekit_url": "wss://proj-abc.livekit.cloud",
        "livekit_api_key": "APIkeyForTests1",
        "livekit_api_secret": "sekret-value-for-livekit-tests-0001",
    }
    assert (
        await client.put("/v1/integrations/livekit", headers=h, json={"values": lk})
    ).status_code == 200
    tw = {"twilio_account_sid": "AC" + "a" * 32, "twilio_auth_token": "b" * 32}
    assert (
        await client.put("/v1/integrations/twilio", headers=h, json={"values": tw})
    ).status_code == 200


async def live_agent(client: httpx.AsyncClient, h: dict[str, str], publish: bool = True) -> str:
    r = await client.post("/v1/agents", headers=h, json=agent_body())
    agent_id: str = r.json()["id"]
    if publish:
        assert (
            await client.post(f"/v1/agents/{agent_id}/versions/1/publish", headers=h)
        ).status_code == 200
    return agent_id


async def test_needs_twilio_and_livekit_first(
    client: httpx.AsyncClient, workspace_a: BootstrapResult, env: Env
) -> None:
    h = bearer(workspace_a.token)
    r = await client.post("/v1/phone-numbers", headers=h, json={"e164": NUMBER})
    assert r.status_code == 409 and "Twilio" in r.json()["detail"]
    assert env.log == []


async def test_connect_builds_trunk_once_and_lists_numbers(
    client: httpx.AsyncClient, workspace_a: BootstrapResult, env: Env, admin: psycopg.Connection
) -> None:
    h = bearer(workspace_a.token)
    await connect_providers(client, h)
    agent = await live_agent(client, h)
    r = await client.post(
        "/v1/phone-numbers", headers=h, json={"e164": NUMBER, "agent_id": agent, "label": "Main"}
    )
    assert r.status_code == 201, r.text
    assert r.json()["agent_name"] == "Receptionist" and r.json()["e164"] == NUMBER
    assert env.names().count("twilio.create_trunk") == 1
    assert ("twilio.origination", "sip:proj.sip.livekit.cloud;transport=tcp") in env.log

    r2 = await client.post("/v1/phone-numbers", headers=h, json={"e164": OTHER})
    assert r2.status_code == 201 and r2.json()["agent_id"] is None
    assert env.names().count("twilio.create_trunk") == 1  # the second number reuses the trunk
    assert ("lk.inbound", OTHER, "none") in env.log

    listed = (await client.get("/v1/phone-numbers", headers=h)).json()
    assert [n["e164"] for n in listed] == [NUMBER, OTHER]
    assert (
        "twilio_number_sid" not in r.text and "lk_" not in r.text
    )  # provider ids stay server-side
    assert admin.execute(
        "SELECT count(*) FROM audit_log WHERE action='phone_number.connect'"
    ).fetchone() == (2,)


async def test_unpublished_agent_and_unowned_number_are_refused(
    client: httpx.AsyncClient, workspace_a: BootstrapResult, env: Env
) -> None:
    h = bearer(workspace_a.token)
    await connect_providers(client, h)
    draft = await live_agent(client, h, publish=False)
    r = await client.post("/v1/phone-numbers", headers=h, json={"e164": NUMBER, "agent_id": draft})
    assert r.status_code == 422 and "Publish the agent first" in r.json()["detail"]
    r = await client.post("/v1/phone-numbers", headers=h, json={"e164": "+19999999999"})
    assert r.status_code == 502 and "not a number in this Twilio account" in r.json()["detail"]
    assert (
        await client.post("/v1/phone-numbers", headers=h, json={"e164": "4155550134"})
    ).status_code == 422
    assert (await client.get("/v1/phone-numbers", headers=h)).json() == []


async def test_failure_part_way_undoes_what_was_created(
    client: httpx.AsyncClient, workspace_a: BootstrapResult, env: Env
) -> None:
    h = bearer(workspace_a.token)
    await connect_providers(client, h)
    env.sip.fail_outbound = True
    r = await client.post("/v1/phone-numbers", headers=h, json={"e164": NUMBER})
    assert r.status_code == 502 and "outbound trunk" in r.json()["detail"]
    assert "lk.del_inbound" in env.names() and "twilio.detach_number" in env.names()
    assert "twilio.del_cred" in env.names()
    assert (await client.get("/v1/phone-numbers", headers=h)).json() == []


async def test_a_number_can_only_be_connected_once(
    client: httpx.AsyncClient, workspace_a: BootstrapResult, env: Env
) -> None:
    h = bearer(workspace_a.token)
    await connect_providers(client, h)
    assert (
        await client.post("/v1/phone-numbers", headers=h, json={"e164": NUMBER})
    ).status_code == 201
    again = await client.post("/v1/phone-numbers", headers=h, json={"e164": NUMBER})
    assert again.status_code == 409 and "already connected" in again.json()["detail"]
    assert (
        env.names().count("lk.del_inbound") == 1
    )  # the duplicate's provider resources were removed


async def test_reassign_unassign_and_disconnect(
    client: httpx.AsyncClient, workspace_a: BootstrapResult, env: Env
) -> None:
    h = bearer(workspace_a.token)
    await connect_providers(client, h)
    agent = await live_agent(client, h)
    n = (await client.post("/v1/phone-numbers", headers=h, json={"e164": NUMBER})).json()
    p = await client.patch(f"/v1/phone-numbers/{n['id']}", headers=h, json={"agent_id": agent})
    assert (
        p.status_code == 200 and p.json()["agent_id"] == agent and "lk.replace_rule" in env.names()
    )
    p = await client.patch(f"/v1/phone-numbers/{n['id']}", headers=h, json={"agent_id": None})
    assert p.json()["agent_id"] is None and ("lk.remove_rule", "RULE2") in env.log
    p = await client.patch(f"/v1/phone-numbers/{n['id']}", headers=h, json={"label": "Support"})
    assert p.json()["label"] == "Support"

    env.log.clear()
    assert (await client.delete(f"/v1/phone-numbers/{n['id']}", headers=h)).status_code == 204
    assert {"lk.del_inbound", "lk.del_outbound", "twilio.detach_number", "twilio.del_cred"} <= set(
        env.names()
    )
    assert (await client.get("/v1/phone-numbers", headers=h)).json() == []
    assert (await client.delete(f"/v1/phone-numbers/{n['id']}", headers=h)).status_code == 404


async def test_outbound_requires_consent_a_live_agent_and_respects_the_cap(
    client: httpx.AsyncClient, workspace_a: BootstrapResult, env: Env, make_key: MakeKey
) -> None:
    h = bearer(workspace_a.token)
    await connect_providers(client, h)
    agent = await live_agent(client, h)
    n = (await client.post("/v1/phone-numbers", headers=h, json={"e164": NUMBER})).json()
    body: dict[str, Any] = {
        "from_number_id": n["id"],
        "agent_id": agent,
        "to": OTHER,
        "consent_confirmed": True,
    }

    assert (
        await client.post(
            "/v1/calls/outbound", headers=h, json={**body, "consent_confirmed": False}
        )
    ).status_code == 422
    assert (
        await client.post("/v1/calls/outbound", headers=h, json={**body, "to": NUMBER})
    ).status_code == 422
    draft = await live_agent(client, h, publish=False)
    assert (
        await client.post("/v1/calls/outbound", headers=h, json={**body, "agent_id": draft})
    ).status_code == 422
    assert "lk.dial" not in env.names()

    for _ in range(3):
        ok = await client.post("/v1/calls/outbound", headers=h, json=body)
        assert ok.status_code == 202 and ok.json() == {"room": "out-room-1"}
    assert ("lk.dial", "OT3", OTHER) in env.log or any(
        e[0] == "lk.dial" and e[2] == OTHER for e in env.log
    )
    capped = await client.post("/v1/calls/outbound", headers=h, json=body)
    assert capped.status_code == 429

    weak = bearer(make_key(workspace_a.workspace_id, frozenset({Permission.NUMBERS_READ})))
    assert (await client.post("/v1/calls/outbound", headers=weak, json=body)).status_code == 403
    assert (
        await client.post("/v1/phone-numbers", headers=weak, json={"e164": OTHER})
    ).status_code == 403
    assert (await client.get("/v1/phone-numbers", headers=weak)).status_code == 200


async def test_audit_never_records_the_full_dialed_number(
    client: httpx.AsyncClient, workspace_a: BootstrapResult, env: Env, admin: psycopg.Connection
) -> None:
    h = bearer(workspace_a.token)
    await connect_providers(client, h)
    agent = await live_agent(client, h)
    n = (await client.post("/v1/phone-numbers", headers=h, json={"e164": NUMBER})).json()
    await client.post(
        "/v1/calls/outbound",
        headers=h,
        json={"from_number_id": n["id"], "agent_id": agent, "to": OTHER, "consent_confirmed": True},
    )
    detail = admin.execute(
        "SELECT detail::text FROM audit_log WHERE action='call.outbound'"
    ).fetchone()
    assert detail is not None and OTHER not in detail[0] and OTHER[-4:] in detail[0]


async def test_reconnecting_after_a_livekit_project_change_repoints_the_twilio_trunk(
    client: httpx.AsyncClient, workspace_a: BootstrapResult, env: Env
) -> None:
    h = bearer(workspace_a.token)
    await connect_providers(client, h)
    assert (
        await client.post("/v1/phone-numbers", headers=h, json={"e164": NUMBER})
    ).status_code == 201
    # The workspace now points at a different LiveKit project: its SIP address changes.
    env.twilio.urls = [("OU-old", "sip:old-project.sip.livekit.cloud;transport=tcp")]
    env.log.clear()
    assert (
        await client.post("/v1/phone-numbers", headers=h, json={"e164": OTHER})
    ).status_code == 201
    assert ("twilio.origination", "sip:proj.sip.livekit.cloud;transport=tcp") in env.log
    assert ("twilio.del_origination", "OU-old") in env.log
    assert [u for _, u in env.twilio.urls] == ["sip:proj.sip.livekit.cloud;transport=tcp"]
    env.log.clear()
    assert (
        await client.post("/v1/phone-numbers", headers=h, json={"e164": "+14155550177"})
    ).status_code == 201
    assert "twilio.origination" not in env.names()  # already correct: left alone
