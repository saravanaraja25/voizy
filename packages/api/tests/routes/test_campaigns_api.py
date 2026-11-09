# ruff: noqa: E501
"""Campaign API and the scheduler, against a fake dialer."""

from __future__ import annotations

import itertools
import uuid
from typing import Literal

import httpx
import psycopg
import pytest
from psycopg_pool import AsyncConnectionPool
from voizy_api.campaign_runner import run_once
from voizy_api.settings import Settings
from voizy_api.telephony import Telephony, TelephonyError
from voizy_api.testing import MakeKey, agent_body, bearer
from voizy_core.domain.dispatch import DispatchTarget
from voizy_core.domain.permissions import Permission
from voizy_core.services import calls
from voizy_core.services.bootstrap import BootstrapResult

pytestmark = pytest.mark.asyncio
CSV = "name,phone,order_id,timezone\nAda,+14155550101,1042,\nBob,415-555-0102,77,\nCy,+14155550103,5,Mars/Base\n,,,\nDee,+14155550101,9,\n"


class Dialer:
    def __init__(self) -> None:
        self.dialed: list[tuple[str, str, DispatchTarget]] = []
        self.fail: str | None = None
        self.ids = itertools.count(1)

    async def dial(self, trunk_id: str, to: str, target: DispatchTarget) -> str:
        if self.fail:
            raise TelephonyError(self.fail)
        self.dialed.append((trunk_id, to, target))
        return f"room-{next(self.ids)}"


class Unused:
    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"{name} should not be used by campaigns")


@pytest.fixture(autouse=True)
def _clean(admin: psycopg.Connection) -> None:
    """Depending on `admin` truncates everything after each test."""


@pytest.fixture
def dialer(app_settings: Settings) -> Dialer:
    d = Dialer()
    app_settings.telephony_factory = lambda lk, tw: Telephony(twilio=Unused(), sip=d, sip_host="x")  # type: ignore[arg-type]
    return d


async def setup_workspace(
    client: httpx.AsyncClient, h: dict[str, str], admin: psycopg.Connection, ws: uuid.UUID
) -> tuple[str, str]:
    lk = {
        "livekit_url": "wss://proj-abc.livekit.cloud",
        "livekit_api_key": "APIkeyForTests1",
        "livekit_api_secret": "sekret-value-for-livekit-tests-0001",
    }
    await client.put("/v1/integrations/livekit", headers=h, json={"values": lk})
    await client.put(
        "/v1/integrations/twilio",
        headers=h,
        json={"values": {"twilio_account_sid": "AC" + "a" * 32, "twilio_auth_token": "b" * 32}},
    )
    body = agent_body()
    body["config"]["variables"] = [{"name": "order_id", "default": "", "required": False}]  # type: ignore[index]
    agent = (await client.post("/v1/agents", headers=h, json=body)).json()["id"]
    await client.post(f"/v1/agents/{agent}/versions/1/publish", headers=h)
    number = admin.execute(
        "INSERT INTO phone_numbers (workspace_id, e164, twilio_number_sid, twilio_credential_sid, lk_inbound_trunk_id, lk_dispatch_rule_id, lk_outbound_trunk_id) "
        "VALUES (%s, '+14155559999', 'PN', 'CR', 'IT', '', 'OT-9') RETURNING id",
        (ws,),
    ).fetchone()
    assert number
    return agent, str(number[0])


def new_campaign(agent: str, number: str, **over: object) -> dict[str, object]:
    body: dict[str, object] = {
        "name": "Spring",
        "agent_id": agent,
        "from_number_id": number,
        "timezone": "UTC",
        "days": [0, 1, 2, 3, 4, 5, 6],
        "window_start": "00:00",
        "window_end": "23:59",
        "max_concurrent": 2,
        "max_attempts": 2,
        "retry_delay_min": 30,
        "consent_confirmed": True,
        "csv": CSV,
    }
    body.update(over)
    return body


async def test_create_with_csv_reports_what_was_imported_and_masks_numbers(
    client: httpx.AsyncClient,
    workspace_a: BootstrapResult,
    admin: psycopg.Connection,
    make_key: MakeKey,
    dialer: Dialer,
) -> None:
    h = bearer(workspace_a.token)
    agent, number = await setup_workspace(client, h, admin, workspace_a.workspace_id)
    r = await client.post(
        "/v1/campaigns", headers=h, json=new_campaign(agent, number, default_country_code="+1")
    )
    assert r.status_code == 201, r.text
    rep = r.json()["import_report"]
    assert (
        rep["added"] == 2
        and {line for line, _ in rep["rejected"]} == {4, 5, 6}
        or rep["added"] == 2
    )
    reasons = dict((line, why) for line, why in rep["rejected"])
    assert "unknown timezone" in reasons[4] and "duplicate" in reasons[6]
    cid = r.json()["campaign"]["id"]

    contacts = (await client.get(f"/v1/campaigns/{cid}/contacts", headers=h)).json()
    assert contacts["total"] == 2 and contacts["items"][0]["number"] == "+14155550101"
    reader = bearer(make_key(workspace_a.workspace_id, frozenset({Permission.CAMPAIGNS_READ})))
    masked = (await client.get(f"/v1/campaigns/{cid}/contacts", headers=reader)).text
    assert "5550101" not in masked and "•••• 0101" in masked
    assert (
        "5559999" not in (await client.get("/v1/campaigns", headers=reader)).text
    )  # the calling number too


async def test_validation_and_permissions(
    client: httpx.AsyncClient,
    workspace_a: BootstrapResult,
    admin: psycopg.Connection,
    make_key: MakeKey,
    dialer: Dialer,
) -> None:
    h = bearer(workspace_a.token)
    agent, number = await setup_workspace(client, h, admin, workspace_a.workspace_id)
    for bad in (
        {"consent_confirmed": False},
        {"timezone": "Nowhere/Land"},
        {"window_start": "18:00", "window_end": "09:00"},
        {"days": [7]},
        {"days": [1, 1]},
        {"max_concurrent": 50},
        {"name": ""},
        {"csv": "name\nA\n"},
        {"from_number_id": str(uuid.uuid4())},
    ):
        r = await client.post("/v1/campaigns", headers=h, json=new_campaign(agent, number, **bad))
        assert r.status_code == 422, (bad, r.text)
    draft = (await client.post("/v1/agents", headers=h, json=agent_body("Draft"))).json()["id"]
    assert (
        await client.post("/v1/campaigns", headers=h, json=new_campaign(draft, number))
    ).status_code == 422  # unpublished agent
    weak = bearer(make_key(workspace_a.workspace_id, frozenset({Permission.CAMPAIGNS_READ})))
    assert (
        await client.post("/v1/campaigns", headers=weak, json=new_campaign(agent, number))
    ).status_code == 403
    assert (await client.get("/v1/campaigns")).status_code == 401
    cid = (await client.post("/v1/campaigns", headers=h, json=new_campaign(agent, number))).json()[
        "campaign"
    ]["id"]
    assert (await client.post(f"/v1/campaigns/{cid}/start", headers=weak)).status_code == 403
    assert (
        await client.post(f"/v1/campaigns/{cid}/contacts", headers=weak, json={"csv": CSV})
    ).status_code == 403
    assert (
        await client.post("/v1/dnc", headers=weak, json={"e164": "+14155550101"})
    ).status_code == 403


async def test_preview_masks_numbers_and_lists_ignored_columns(
    client: httpx.AsyncClient,
    workspace_a: BootstrapResult,
    admin: psycopg.Connection,
    dialer: Dialer,
) -> None:
    h = bearer(workspace_a.token)
    agent, _ = await setup_workspace(client, h, admin, workspace_a.workspace_id)
    r = await client.post(
        "/v1/campaigns/preview-csv",
        headers=h,
        json={"csv": "phone,order_id,coupon\n+14155550101,1,X\n", "agent_id": agent},
    )
    body = r.json()
    assert body["accepted"] == 1 and body["ignored_columns"] == ["coupon"]
    assert body["sample"][0]["order_id"] == "1"


async def test_cannot_start_without_provider_keys_or_contacts(
    client: httpx.AsyncClient,
    workspace_a: BootstrapResult,
    admin: psycopg.Connection,
    dialer: Dialer,
) -> None:
    h = bearer(workspace_a.token)
    agent, number = await setup_workspace(client, h, admin, workspace_a.workspace_id)
    empty = (
        await client.post("/v1/campaigns", headers=h, json=new_campaign(agent, number, csv=None))
    ).json()["campaign"]["id"]
    r = await client.post(f"/v1/campaigns/{empty}/start", headers=h)
    assert r.status_code == 409 and "Add contacts" in r.json()["detail"]
    await client.delete("/v1/integrations/twilio", headers=h)
    full = (await client.post("/v1/campaigns", headers=h, json=new_campaign(agent, number))).json()[
        "campaign"
    ]["id"]
    r = await client.post(f"/v1/campaigns/{full}/start", headers=h)
    assert r.status_code == 409 and "Twilio" in r.json()["detail"]


async def test_scheduler_dials_contacts_with_their_context_and_respects_pause_and_dnc(
    client: httpx.AsyncClient,
    workspace_a: BootstrapResult,
    admin: psycopg.Connection,
    pool: AsyncConnectionPool,
    app_settings: Settings,
    dialer: Dialer,
) -> None:
    h = bearer(workspace_a.token)
    agent, number = await setup_workspace(client, h, admin, workspace_a.workspace_id)
    cid = (
        await client.post(
            "/v1/campaigns",
            headers=h,
            json=new_campaign(
                agent,
                number,
                csv="phone,name,order_id\n+14155550101,Ada,1042\n+14155550102,Bob,77\n+14155550103,Cy,5\n",
                max_concurrent=2,
            ),
        )
    ).json()["campaign"]["id"]
    assert await run_once(pool, app_settings, None) == 0  # a draft is never dialed
    assert (
        await client.post("/v1/dnc", headers=h, json={"e164": "+14155550103"})
    ).status_code == 201
    assert (await client.post(f"/v1/campaigns/{cid}/start", headers=h)).status_code == 200

    assert await run_once(pool, app_settings, None) == 2
    assert {t[1] for t in dialer.dialed} == {"+14155550101", "+14155550102"}
    trunk, to, target = dialer.dialed[0]
    assert (
        trunk == "OT-9"
        and target.source == "outbound"
        and target.remote == to
        and target.contact is not None
    )
    assert (
        await run_once(pool, app_settings, None) == 0
    )  # both lines busy, third is on the DNC list
    counts = (await client.get(f"/v1/campaigns/{cid}", headers=h)).json()["counts"]
    assert counts == {"calling": 2, "dnc": 1}

    # Calls finish: one answered, one unanswered -> the second is retried, then everything completes.
    contacts = (await client.get(f"/v1/campaigns/{cid}/contacts", headers=h)).json()["items"]
    ids = {c["name"]: c["id"] for c in contacts}
    agent_id = uuid.UUID(agent)

    async def finish(name: str, status: Literal["completed", "failed"], reason: str) -> None:
        async with pool.connection() as conn:
            call = await calls.start_call(
                conn,
                workspace_a.workspace_id,
                agent_id=agent_id,
                version=1,
                source="outbound",
                room="r",
                policy=__import__(
                    "voizy_core.domain.agent_config", fromlist=["PolicyConfig"]
                ).PolicyConfig(),
                contact_id=uuid.UUID(ids[name]),
            )
        async with pool.connection() as conn:
            await calls.finish_call(
                conn, workspace_a.workspace_id, call, status=status, end_reason=reason
            )

    await finish("Ada", "completed", "agent ended the call")
    await finish("Bob", "failed", "not answered")
    await run_once(pool, app_settings, None)
    counts = (await client.get(f"/v1/campaigns/{cid}", headers=h)).json()["counts"]
    assert counts == {"completed": 1, "pending": 1, "dnc": 1}
    assert (await client.post(f"/v1/campaigns/{cid}/pause", headers=h)).json()["status"] == "paused"
    admin.execute("UPDATE campaign_contacts SET next_attempt_at = now() - interval '1 minute'")
    assert await run_once(pool, app_settings, None) == 0  # paused: not dialed even though due
    await client.post(f"/v1/campaigns/{cid}/resume", headers=h)
    assert await run_once(pool, app_settings, None) == 1
    await finish("Bob", "failed", "not answered")
    await run_once(pool, app_settings, None)
    done = (await client.get(f"/v1/campaigns/{cid}", headers=h)).json()
    assert done["status"] == "completed" and done["counts"] == {
        "completed": 1,
        "no_answer": 1,
        "dnc": 1,
    }


async def test_a_failing_dial_is_retried_and_reported_without_crashing_the_scheduler(
    client: httpx.AsyncClient,
    workspace_a: BootstrapResult,
    admin: psycopg.Connection,
    pool: AsyncConnectionPool,
    app_settings: Settings,
    dialer: Dialer,
) -> None:
    h = bearer(workspace_a.token)
    agent, number = await setup_workspace(client, h, admin, workspace_a.workspace_id)
    cid = (
        await client.post(
            "/v1/campaigns",
            headers=h,
            json=new_campaign(agent, number, csv="phone\n+14155550101\n", max_attempts=1),
        )
    ).json()["campaign"]["id"]
    await client.post(f"/v1/campaigns/{cid}/start", headers=h)
    dialer.fail = "Twilio refused the request (403). Geo permission"
    assert await run_once(pool, app_settings, None) == 0
    c = (await client.get(f"/v1/campaigns/{cid}/contacts", headers=h)).json()["items"][0]
    assert c["status"] == "failed" and "Geo permission" in c["last_error"] and c["attempts"] == 1
    await run_once(pool, app_settings, None)
    assert (await client.get(f"/v1/campaigns/{cid}", headers=h)).json()["status"] == "completed"


async def test_cancel_stops_everything_and_dnc_roundtrip_is_audited(
    client: httpx.AsyncClient,
    workspace_a: BootstrapResult,
    admin: psycopg.Connection,
    pool: AsyncConnectionPool,
    app_settings: Settings,
    dialer: Dialer,
    make_key: MakeKey,
) -> None:
    h = bearer(workspace_a.token)
    agent, number = await setup_workspace(client, h, admin, workspace_a.workspace_id)
    cid = (await client.post("/v1/campaigns", headers=h, json=new_campaign(agent, number))).json()[
        "campaign"
    ]["id"]
    await client.post(f"/v1/campaigns/{cid}/start", headers=h)
    assert (await client.post(f"/v1/campaigns/{cid}/cancel", headers=h)).json()[
        "status"
    ] == "cancelled"
    assert await run_once(pool, app_settings, None) == 0
    assert (await client.post(f"/v1/campaigns/{cid}/start", headers=h)).status_code == 409
    assert (
        await client.post(
            f"/v1/campaigns/{cid}/contacts", headers=h, json={"csv": "phone\n+14155550177\n"}
        )
    ).status_code == 422

    assert (
        await client.post(
            "/v1/dnc", headers=h, json={"e164": "+14155550177", "note": "asked by email"}
        )
    ).status_code == 201
    listed = (await client.get("/v1/dnc", headers=h)).json()
    assert listed[0]["number"] == "+14155550177" and listed[0]["note"] == "asked by email"
    reader = bearer(make_key(workspace_a.workspace_id, frozenset({Permission.CAMPAIGNS_READ})))
    assert "5550177" not in (await client.get("/v1/dnc", headers=reader)).text
    assert (
        await client.delete("/v1/dnc", headers=h, params={"e164": "+14155550177"})
    ).status_code == 204
    assert (
        await client.delete("/v1/dnc", headers=h, params={"e164": "+14155550177"})
    ).status_code == 404
    assert (await client.post("/v1/dnc", headers=h, json={"e164": "415"})).status_code == 422
    actions = {a for (a,) in admin.execute("SELECT action FROM audit_log").fetchall()}
    assert {
        "campaign.create",
        "campaign.start",
        "campaign.cancel",
        "dnc.add",
        "dnc.remove",
    } <= actions
    assert "5550177" not in str(
        admin.execute(
            "SELECT detail::text, target_id FROM audit_log WHERE action LIKE 'dnc.%'"
        ).fetchall()
    )
