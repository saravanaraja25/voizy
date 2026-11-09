# ruff: noqa: E501
from __future__ import annotations

import datetime as dt
import uuid

import psycopg
import pytest
from psycopg import AsyncConnection
from voizy_core.domain.agent_config import PolicyConfig
from voizy_core.services import calls
from voizy_core.services import campaigns as cp

WS = tuple[uuid.UUID, uuid.UUID]


# --------------------------------------------------------------------------------- CSV parsing


def test_csv_accepts_formats_and_turns_extra_columns_into_variables() -> None:
    csv_text = "Name,Phone,Timezone,Order ID,Notes\nAda,+1 (415) 555-0134,America/New_York,1042,\nBob,00442079460958,,77,vip\n"
    parsed = cp.parse_contacts_csv(csv_text)
    assert [c.e164 for c in parsed.accepted] == ["+14155550134", "+442079460958"]
    assert parsed.accepted[0].timezone == "America/New_York"
    assert parsed.accepted[0].variables == {"order_id": "1042"}  # blank 'Notes' skipped
    assert parsed.accepted[1].variables == {"order_id": "77", "notes": "vip"}
    assert parsed.rejected == []


def test_csv_reports_bad_rows_with_reasons_and_never_crashes() -> None:
    csv_text = (
        "phone,name\n+14155550134,A\n,B\n415-555-0134,C\n+14155550134,D\n+1234,E\n+14155550199,F\n"
    )
    parsed = cp.parse_contacts_csv(csv_text)
    assert [c.name for c in parsed.accepted] == ["A", "F"]
    assert dict(parsed.rejected) == {
        3: "no phone number",
        4: "not a valid number (use +country code)",
        5: "duplicate number",
        6: "not a valid number (use +country code)",
    }
    withdefault = cp.parse_contacts_csv(
        "phone\n415-555-0134\n0415555099\n", default_country_code="+1"
    )
    assert [c.e164 for c in withdefault.accepted] == ["+14155550134", "+1415555099"]


def test_csv_rejects_unusable_files_and_bad_timezones() -> None:
    with pytest.raises(cp.CampaignError, match="empty"):
        cp.parse_contacts_csv("")
    with pytest.raises(cp.CampaignError, match="'phone' column"):
        cp.parse_contacts_csv("name,email\nA,a@b.c\n")
    bad_tz = cp.parse_contacts_csv("phone,tz\n+14155550134,Mars/Olympus\n")
    assert bad_tz.accepted == [] and "unknown timezone" in bad_tz.rejected[0][1]
    ignored = cp.parse_contacts_csv(
        "phone,Weird Col!,order\n+14155550134,x,1\n", known_variables={"order"}
    )
    assert "order" not in ignored.ignored_columns
    known = cp.parse_contacts_csv("phone,coupon\n+14155550134,X\n", known_variables={"order"})
    assert known.ignored_columns == ["coupon"]
    with pytest.raises(cp.CampaignError, match="Too many rows"):
        cp.parse_contacts_csv(
            "phone\n" + "\n".join(f"+1415{n:07d}" for n in range(cp.MAX_CONTACTS + 1))
        )


# ------------------------------------------------------------------------------ scheduler rules


async def seed(
    conn: AsyncConnection, admin: psycopg.Connection, wid: uuid.UUID, **over: object
) -> uuid.UUID:
    agent = admin.execute(
        "INSERT INTO agents (workspace_id, name) VALUES (%s, 'A') RETURNING id", (wid,)
    ).fetchone()
    number = admin.execute(
        "INSERT INTO phone_numbers (workspace_id, e164, agent_id, twilio_number_sid, twilio_credential_sid, "
        "lk_inbound_trunk_id, lk_dispatch_rule_id, lk_outbound_trunk_id) "
        "VALUES (%s, %s, NULL, 'PN1', 'CR1', 'IT1', '', 'OT1') RETURNING id",
        (wid, f"+1415{uuid.uuid4().int % 10**7:07d}"),
    ).fetchone()
    assert agent and number
    args: dict[str, object] = dict(
        name="Spring",
        agent_id=agent[0],
        from_number_id=number[0],
        timezone="UTC",
        days_mask=127,
        window_start=dt.time(0, 0),
        window_end=dt.time(23, 59, 59),
        max_concurrent=2,
        max_attempts=2,
        retry_delay_min=30,
        consent_confirmed=True,
        user_id=None,
    )
    args.update(over)
    return await cp.create_campaign(conn, wid, **args)  # type: ignore[arg-type]


def people(n: int, **kw: object) -> list[cp.ContactInput]:
    return [cp.ContactInput(f"+1415555{i:04d}", f"P{i}", **kw) for i in range(n)]  # type: ignore[arg-type]


async def test_cannot_create_or_start_without_consent_contacts_or_valid_window(
    app_aconn: AsyncConnection, admin: psycopg.Connection, two_workspaces: WS
) -> None:
    a, _ = two_workspaces
    with pytest.raises(cp.CampaignError, match="agreed to be called"):
        await seed(app_aconn, admin, a, consent_confirmed=False)
    with pytest.raises(cp.CampaignError, match="window"):
        await seed(app_aconn, admin, a, window_start=dt.time(18), window_end=dt.time(9))
    with pytest.raises(cp.CampaignError, match="timezone"):
        await seed(app_aconn, admin, a, timezone="Nowhere/Land")
    cid = await seed(app_aconn, admin, a)
    with pytest.raises(cp.CampaignError, match="Add contacts"):
        await cp.set_status(app_aconn, a, cid, "running")
    await cp.add_contacts(app_aconn, a, cid, people(1))
    assert await cp.set_status(app_aconn, a, cid, "running") == "running"
    assert await cp.set_status(app_aconn, a, cid, "paused") == "paused"
    with pytest.raises(cp.CampaignError, match="cannot become"):
        await cp.set_status(app_aconn, a, cid, "draft")


async def test_claims_respect_concurrency_and_only_running_campaigns(
    app_aconn: AsyncConnection, admin: psycopg.Connection, two_workspaces: WS
) -> None:
    a, _ = two_workspaces
    cid = await seed(app_aconn, admin, a, max_concurrent=2)
    await cp.add_contacts(app_aconn, a, cid, people(5))
    assert await cp.claim_due(app_aconn, a, cid) == []  # draft: nothing is dialed
    await cp.set_status(app_aconn, a, cid, "running")
    first = await cp.claim_due(app_aconn, a, cid)
    assert len(first) == 2 and first[0].lk_outbound_trunk_id == "OT1"
    assert await cp.claim_due(app_aconn, a, cid) == []  # both lines busy
    await cp.set_status(app_aconn, a, cid, "paused")
    assert await cp.claim_due(app_aconn, a, cid) == []
    assert (await cp.counts(app_aconn, a, cid)) == {"calling": 2, "pending": 3}


async def test_calling_window_uses_each_contacts_own_timezone(
    app_aconn: AsyncConnection, admin: psycopg.Connection, two_workspaces: WS
) -> None:
    a, _ = two_workspaces
    # A window of the current UTC hour: UTC contacts qualify, a contact 12 hours away does not.
    now = dt.datetime.now(dt.UTC)
    start = (now - dt.timedelta(minutes=1)).time().replace(microsecond=0)
    end = (now + dt.timedelta(minutes=30)).time().replace(microsecond=0)
    if not start < end:
        pytest.skip("test would straddle midnight UTC")
    cid = await seed(app_aconn, admin, a, window_start=start, window_end=end, max_concurrent=10)
    far = "Pacific/Auckland" if now.hour < 12 else "America/Los_Angeles"
    await cp.add_contacts(
        app_aconn,
        a,
        cid,
        [cp.ContactInput("+14155550001", "here"), cp.ContactInput("+14155550002", "far", far)],
    )
    await cp.set_status(app_aconn, a, cid, "running")
    claimed = {c.e164 for c in await cp.claim_due(app_aconn, a, cid)}
    assert claimed == {"+14155550001"}


async def test_calling_days_are_honoured(
    app_aconn: AsyncConnection, admin: psycopg.Connection, two_workspaces: WS
) -> None:
    a, _ = two_workspaces
    today = dt.datetime.now(dt.UTC).isoweekday() - 1  # 0 = Monday
    other = 1 << ((today + 3) % 7)
    cid = await seed(app_aconn, admin, a, days_mask=other)
    await cp.add_contacts(app_aconn, a, cid, people(2))
    await cp.set_status(app_aconn, a, cid, "running")
    assert await cp.claim_due(app_aconn, a, cid) == []
    admin.execute("UPDATE campaigns SET days_mask = %s", (1 << today,))
    assert len(await cp.claim_due(app_aconn, a, cid)) == 2


async def test_do_not_call_blocks_at_import_at_dial_time_and_on_opt_out(
    app_aconn: AsyncConnection, admin: psycopg.Connection, two_workspaces: WS
) -> None:
    a, b = two_workspaces
    await cp.dnc_add(app_aconn, a, "+14155550000", source="manual")
    cid = await seed(app_aconn, admin, a, max_concurrent=10)
    await cp.add_contacts(app_aconn, a, cid, people(3))
    contacts, _ = await cp.list_contacts(app_aconn, a, cid)
    assert {c.e164: c.status for c in contacts}["+14155550000"] == "dnc"  # blocked on import
    await cp.set_status(app_aconn, a, cid, "running")
    await cp.dnc_add(app_aconn, a, "+14155550001", source="manual")  # added after import
    claimed = {c.e164 for c in await cp.claim_due(app_aconn, a, cid)}
    assert claimed == {"+14155550002"}
    await cp.opt_out(
        app_aconn, a, "+14155550002", (await cp.list_contacts(app_aconn, a, cid))[0][2].id
    )
    assert any(
        r[0] == "+14155550002" and r[1] == "opt_out" for r in await cp.dnc_list(app_aconn, a)
    )
    assert await cp.dnc_list(app_aconn, b) == []  # other workspaces never see it
    assert await cp.dnc_remove(app_aconn, a, "+14155550000") and not await cp.dnc_remove(
        app_aconn, a, "+14155550000"
    )
    with pytest.raises(cp.CampaignError):
        await cp.dnc_add(app_aconn, a, "415", source="manual")


async def finish_call(
    conn: AsyncConnection,
    admin: psycopg.Connection,
    wid: uuid.UUID,
    cid: uuid.UUID,
    contact: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    status: str,
    reason: str,
) -> None:
    call_id = await calls.start_call(
        conn,
        wid,
        agent_id=agent_id,
        version=1,
        source="outbound",
        room="r",
        policy=PolicyConfig(),
        campaign_id=cid,
        contact_id=contact,
    )
    await calls.finish_call(conn, wid, call_id, status=status, end_reason=reason)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("status", "reason", "after_first_attempt"),
    [
        ("completed", "agent ended the call", "completed"),
        ("completed", "ended", "completed"),
        ("failed", "not answered", "pending"),  # no_answer: try again
        ("completed", "voicemail", "pending"),
        ("failed", "worker stopped", "pending"),
    ],
)
async def test_outcomes_and_retries(
    app_aconn: AsyncConnection,
    admin: psycopg.Connection,
    two_workspaces: WS,
    status: str,
    reason: str,
    after_first_attempt: str,
) -> None:
    a, _ = two_workspaces
    cid = await seed(app_aconn, admin, a, max_attempts=2, retry_delay_min=30)
    agent_id = admin.execute("SELECT agent_id FROM campaigns WHERE id = %s", (cid,)).fetchone()[0]  # type: ignore[index]
    await cp.add_contacts(app_aconn, a, cid, people(1))
    await cp.set_status(app_aconn, a, cid, "running")
    (claim,) = await cp.claim_due(app_aconn, a, cid)
    assert await cp.resolve_finished(app_aconn, a, cid) == 0  # still calling: no call record yet
    await finish_call(
        app_aconn, admin, a, cid, claim.contact_id, agent_id, status=status, reason=reason
    )
    assert await cp.resolve_finished(app_aconn, a, cid) == 1
    (c,), _ = await cp.list_contacts(app_aconn, a, cid)
    assert c.status == after_first_attempt and c.attempts == 1
    if after_first_attempt == "pending":
        assert c.next_attempt_at is not None and c.next_attempt_at > dt.datetime.now(
            dt.UTC
        ) + dt.timedelta(minutes=25)
        assert await cp.claim_due(app_aconn, a, cid) == []  # not due yet
        admin.execute("UPDATE campaign_contacts SET next_attempt_at = now() - interval '1 minute'")
        (again,) = await cp.claim_due(app_aconn, a, cid)
        await finish_call(
            app_aconn, admin, a, cid, again.contact_id, agent_id, status=status, reason=reason
        )
        await cp.resolve_finished(app_aconn, a, cid)
        (c,), _ = await cp.list_contacts(app_aconn, a, cid)
        assert c.attempts == 2 and c.status == {"voicemail": "voicemail"}.get(
            reason,
            "failed"
            if status == "failed" and reason != "not answered"
            else ("no_answer" if reason == "not answered" else "voicemail"),
        )
    assert await cp.maybe_complete(app_aconn, a, cid) is True
    assert (await cp.get_campaign(app_aconn, a, cid)).status == "completed"  # type: ignore[union-attr]


async def test_calls_that_never_started_or_hung_are_given_up_on(
    app_aconn: AsyncConnection, admin: psycopg.Connection, two_workspaces: WS
) -> None:
    a, _ = two_workspaces
    cid = await seed(app_aconn, admin, a, max_attempts=1)
    await cp.add_contacts(app_aconn, a, cid, people(1))
    await cp.set_status(app_aconn, a, cid, "running")
    await cp.claim_due(app_aconn, a, cid)
    assert await cp.resolve_finished(app_aconn, a, cid) == 0  # within the grace period
    admin.execute("UPDATE campaign_contacts SET claimed_at = now() - interval '5 minutes'")
    assert await cp.resolve_finished(app_aconn, a, cid) == 1
    (c,), _ = await cp.list_contacts(app_aconn, a, cid)
    assert c.status == "failed" and c.last_error == "call did not start"


async def test_failed_dial_is_retried_until_attempts_run_out(
    app_aconn: AsyncConnection, admin: psycopg.Connection, two_workspaces: WS
) -> None:
    a, _ = two_workspaces
    cid = await seed(app_aconn, admin, a, max_attempts=2)
    await cp.add_contacts(app_aconn, a, cid, people(1))
    await cp.set_status(app_aconn, a, cid, "running")
    (claim,) = await cp.claim_due(app_aconn, a, cid)
    await cp.release_failed(app_aconn, a, claim.contact_id, "Twilio refused the request")
    (c,), _ = await cp.list_contacts(app_aconn, a, cid)
    assert c.status == "pending" and c.last_error.startswith("Twilio")
    admin.execute("UPDATE campaign_contacts SET next_attempt_at = now()")
    (claim,) = await cp.claim_due(app_aconn, a, cid)
    await cp.release_failed(app_aconn, a, claim.contact_id, "again")
    (c,), _ = await cp.list_contacts(app_aconn, a, cid)
    assert c.status == "failed" and c.attempts == 2
    assert await cp.maybe_complete(app_aconn, a, cid)


async def test_import_dedupes_and_tenants_are_isolated(
    app_aconn: AsyncConnection, admin: psycopg.Connection, two_workspaces: WS
) -> None:
    a, b = two_workspaces
    cid = await seed(app_aconn, admin, a)
    assert await cp.add_contacts(app_aconn, a, cid, people(3)) == (3, 0)
    assert await cp.add_contacts(app_aconn, a, cid, people(4)) == (1, 3)
    assert await cp.get_campaign(app_aconn, b, cid) is None
    assert await cp.list_campaigns(app_aconn, b) == []
    with pytest.raises(cp.CampaignError, match="not found"):
        await cp.add_contacts(app_aconn, b, cid, people(1))
    await cp.set_status(app_aconn, a, cid, "cancelled")
    with pytest.raises(cp.CampaignError, match="finished"):
        await cp.add_contacts(app_aconn, a, cid, people(9))
    ctx = await cp.contact_context(
        app_aconn, a, (await cp.list_contacts(app_aconn, a, cid))[0][0].id
    )
    assert ctx is not None and ctx[1] == "P0"
