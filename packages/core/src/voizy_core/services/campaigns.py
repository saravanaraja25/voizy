# ruff: noqa: S608 - every f-string SQL here interpolates module constants, never user input.
"""Outbound campaigns: contacts, the do-not-call list, and the scheduler's claim/outcome rules.

The scheduler is a loop in the API process that calls `resolve_finished`, `claim_due` and
`maybe_complete` for each running campaign. Every decision (calling window in the contact's own
timezone, do-not-call, concurrency, retries) lives in SQL here so it can be tested without phones.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
import uuid
import zoneinfo
from dataclasses import dataclass, field
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from voizy_core.db.tx import owned_tx, set_local

E164 = re.compile(r"^\+[1-9][0-9]{6,14}$")
VAR_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
MAX_CONTACTS = 5000
MAX_COLUMNS = 30
MAX_VALUE = 200
CALL_START_GRACE_S = 120  # a claimed contact with no call record after this never started
CALL_MAX_S = 3600  # a claimed contact still 'calling' after this is given up on
PHONE_COLUMNS = ("phone", "mobile", "number", "phone_number", "cell", "e164")
NAME_COLUMNS = ("name", "full_name")
TZ_COLUMNS = ("timezone", "tz")

TERMINAL = ("completed", "cancelled")


class CampaignError(ValueError):
    """A rule was broken (bad input, illegal state change). The message is safe to show."""


# ------------------------------------------------------------------------------------- CSV import


@dataclass(frozen=True)
class ContactInput:
    e164: str
    name: str = ""
    timezone: str | None = None
    variables: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedCsv:
    accepted: list[ContactInput]
    rejected: list[tuple[int, str]]  # (line number, reason)
    ignored_columns: list[str]


def valid_timezone(name: str) -> bool:
    try:
        zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError, OSError):
        return False
    return True


def normalize_number(raw: str, default_country_code: str | None = None) -> str | None:
    """'+1 (415) 555-0134' -> '+14155550134'. None when it cannot be made a valid E.164 number."""
    cleaned = re.sub(r"[\s().\-]", "", raw.strip())
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    if not cleaned.startswith("+") and default_country_code and cleaned.isdigit():
        cc = default_country_code.lstrip("+")
        cleaned = f"+{cc}{cleaned.lstrip('0')}"
    return cleaned if E164.match(cleaned) else None


def _cell(row: list[str], i: int | None) -> str:
    return row[i].strip() if i is not None and i < len(row) else ""


def _header_key(raw: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", raw.strip().lower()).strip("_")


def parse_contacts_csv(
    text: str, *, default_country_code: str | None = None, known_variables: set[str] | None = None
) -> ParsedCsv:
    """Rows with a valid phone become contacts; every other row is reported with its reason.

    Columns other than phone/name/timezone become prompt variables for that person. When
    `known_variables` is given, columns the agent does not declare are listed as ignored.
    """
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    try:
        header = next(reader)
    except StopIteration:
        raise CampaignError("The file is empty.") from None
    keys = [_header_key(h) for h in header]
    if len(keys) > MAX_COLUMNS:
        raise CampaignError(f"Too many columns (limit {MAX_COLUMNS}).")
    phone_i = next((i for i, k in enumerate(keys) if k in PHONE_COLUMNS), None)
    if phone_i is None:
        raise CampaignError("The first row must be a header with a 'phone' column.")
    name_i = next((i for i, k in enumerate(keys) if k in NAME_COLUMNS), None)
    tz_i = next((i for i, k in enumerate(keys) if k in TZ_COLUMNS), None)
    var_cols = {
        i: k for i, k in enumerate(keys) if i not in (phone_i, name_i, tz_i) and VAR_NAME.match(k)
    }
    ignored = [
        header[i].strip()
        for i in range(len(keys))
        if i not in (phone_i, name_i, tz_i) and i not in var_cols
    ]
    if known_variables is not None:
        ignored += [k for k in var_cols.values() if k not in known_variables]

    accepted: list[ContactInput] = []
    rejected: list[tuple[int, str]] = []
    seen: set[str] = set()
    for line, row in enumerate(reader, start=2):
        if not any(c.strip() for c in row):
            continue
        if len(accepted) + len(rejected) >= MAX_CONTACTS:
            raise CampaignError(f"Too many rows (limit {MAX_CONTACTS}).")
        number = normalize_number(_cell(row, phone_i), default_country_code)
        if number is None:
            reason = (
                "no phone number"
                if not _cell(row, phone_i)
                else "not a valid number (use +country code)"
            )
            rejected.append((line, reason))
            continue
        if number in seen:
            rejected.append((line, "duplicate number"))
            continue
        tz = _cell(row, tz_i) or None
        if tz is not None and not valid_timezone(tz):
            rejected.append((line, f"unknown timezone '{tz[:40]}'"))
            continue
        seen.add(number)
        variables = {k: _cell(row, i)[:MAX_VALUE] for i, k in var_cols.items() if _cell(row, i)}
        accepted.append(ContactInput(number, _cell(row, name_i)[:100], tz, variables))
    return ParsedCsv(accepted, rejected, sorted(set(ignored)))


# ---------------------------------------------------------------------------------------- records


@dataclass(frozen=True)
class Campaign:
    id: uuid.UUID
    name: str
    agent_id: uuid.UUID
    agent_name: str
    from_number_id: uuid.UUID
    from_e164: str
    status: str
    timezone: str
    days_mask: int
    window_start: dt.time
    window_end: dt.time
    max_concurrent: int
    max_attempts: int
    retry_delay_min: int
    consent_confirmed_at: dt.datetime | None
    created_at: dt.datetime
    started_at: dt.datetime | None
    completed_at: dt.datetime | None


@dataclass(frozen=True)
class Contact:
    id: uuid.UUID
    e164: str
    name: str
    timezone: str | None
    status: str
    attempts: int
    next_attempt_at: dt.datetime | None
    last_outcome: str | None
    last_error: str
    last_call_id: uuid.UUID | None


@dataclass(frozen=True)
class Claim:
    contact_id: uuid.UUID
    e164: str
    agent_id: uuid.UUID
    from_number_id: uuid.UUID
    lk_outbound_trunk_id: str


_CAMPAIGN_COLS = (
    "c.id, c.name, c.agent_id, a.name, c.from_number_id, n.e164, c.status, c.timezone, "
    "c.days_mask, c.window_start, c.window_end, c.max_concurrent, c.max_attempts, "
    "c.retry_delay_min, c.consent_confirmed_at, c.created_at, c.started_at, c.completed_at "
    "FROM campaigns c JOIN agents a ON a.workspace_id = c.workspace_id AND a.id = c.agent_id "
    "JOIN phone_numbers n ON n.workspace_id = c.workspace_id AND n.id = c.from_number_id"
)
_CONTACT_COLS = (
    "ct.id, ct.e164, ct.name, ct.timezone, ct.status, ct.attempts, ct.next_attempt_at, "
    "ct.last_outcome, ct.last_error, "
    "(SELECT k.id FROM calls k WHERE k.workspace_id = ct.workspace_id AND k.contact_id = ct.id "
    "ORDER BY k.started_at DESC LIMIT 1) FROM campaign_contacts ct"
)


async def _ws(conn: AsyncConnection, workspace_id: uuid.UUID) -> None:
    await set_local(conn, "app.workspace_id", str(workspace_id))


# ------------------------------------------------------------------------------------------ DNC


async def dnc_add(
    conn: AsyncConnection, workspace_id: uuid.UUID, e164: str, *, source: str, note: str = ""
) -> None:
    """Add to the do-not-call list and stop any pending calls to that number, in every campaign."""
    if not E164.match(e164):
        raise CampaignError("Enter the number with its country code, like +14155550134.")
    async with owned_tx(conn):
        await _ws(conn, workspace_id)
        await conn.execute(
            "INSERT INTO dnc_numbers (workspace_id, e164, source, note) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT DO NOTHING",
            (workspace_id, e164, source, note[:200]),
        )
        await conn.execute(
            "UPDATE campaign_contacts SET status = 'dnc' WHERE e164 = %s AND status = 'pending'",
            (e164,),
        )


async def dnc_list(
    conn: AsyncConnection, workspace_id: uuid.UUID
) -> list[tuple[str, str, str, dt.datetime]]:
    async with owned_tx(conn):
        await _ws(conn, workspace_id)
        cur = await conn.execute(
            "SELECT e164, source, note, created_at FROM dnc_numbers ORDER BY created_at DESC"
        )
        return [(r[0], r[1], r[2], r[3]) for r in await cur.fetchall()]


async def dnc_remove(conn: AsyncConnection, workspace_id: uuid.UUID, e164: str) -> bool:
    async with owned_tx(conn):
        await _ws(conn, workspace_id)
        cur = await conn.execute("DELETE FROM dnc_numbers WHERE e164 = %s", (e164,))
        return cur.rowcount == 1


async def opt_out(
    conn: AsyncConnection, workspace_id: uuid.UUID, e164: str, contact_id: uuid.UUID | None
) -> None:
    """The person asked not to be called again: DNC for the workspace, and stop this contact."""
    await dnc_add(conn, workspace_id, e164, source="opt_out", note="asked on a call")
    if contact_id is not None:
        async with owned_tx(conn):
            await _ws(conn, workspace_id)
            await conn.execute(
                "UPDATE campaign_contacts SET status = 'opted_out', next_attempt_at = NULL "
                "WHERE id = %s",
                (contact_id,),
            )


# ------------------------------------------------------------------------------------- campaigns


async def create_campaign(
    conn: AsyncConnection,
    workspace_id: uuid.UUID,
    *,
    name: str,
    agent_id: uuid.UUID,
    from_number_id: uuid.UUID,
    timezone: str,
    days_mask: int,
    window_start: dt.time,
    window_end: dt.time,
    max_concurrent: int,
    max_attempts: int,
    retry_delay_min: int,
    consent_confirmed: bool,
    user_id: uuid.UUID | None,
) -> uuid.UUID:
    if not consent_confirmed:
        raise CampaignError("Confirm that the people on this list have agreed to be called.")
    if not valid_timezone(timezone):
        raise CampaignError("Unknown timezone.")
    if not window_start < window_end:
        raise CampaignError("The calling window must end after it starts.")
    async with owned_tx(conn):
        await _ws(conn, workspace_id)
        cur = await conn.execute(
            "INSERT INTO campaigns (workspace_id, name, agent_id, from_number_id, timezone, "
            "days_mask, window_start, window_end, max_concurrent, max_attempts, retry_delay_min, "
            "consent_confirmed_at, consent_confirmed_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), %s) RETURNING id",
            (
                workspace_id,
                name.strip(),
                agent_id,
                from_number_id,
                timezone,
                days_mask,
                window_start,
                window_end,
                max_concurrent,
                max_attempts,
                retry_delay_min,
                user_id,
            ),
        )
        row = await cur.fetchone()
    if row is None:
        raise RuntimeError("campaign insert returned no row")
    return row[0]  # type: ignore[no-any-return]


async def get_campaign(
    conn: AsyncConnection, workspace_id: uuid.UUID, campaign_id: uuid.UUID
) -> Campaign | None:
    async with owned_tx(conn):
        await _ws(conn, workspace_id)
        sql = f"SELECT {_CAMPAIGN_COLS} WHERE c.id = %s"
        cur = await conn.execute(sql, (campaign_id,))
        row = await cur.fetchone()
    return Campaign(*row) if row else None


async def list_campaigns(
    conn: AsyncConnection, workspace_id: uuid.UUID
) -> list[tuple[Campaign, dict[str, int]]]:
    async with owned_tx(conn):
        await _ws(conn, workspace_id)
        sql = f"SELECT {_CAMPAIGN_COLS} ORDER BY c.created_at DESC"
        cur = await conn.execute(sql)
        campaigns = [Campaign(*r) for r in await cur.fetchall()]
        cur = await conn.execute(
            "SELECT campaign_id, status, count(*) FROM campaign_contacts GROUP BY 1, 2"
        )
        counts: dict[uuid.UUID, dict[str, int]] = {}
        for cid, status, n in await cur.fetchall():
            counts.setdefault(cid, {})[status] = n
    return [(c, counts.get(c.id, {})) for c in campaigns]


async def counts(
    conn: AsyncConnection, workspace_id: uuid.UUID, campaign_id: uuid.UUID
) -> dict[str, int]:
    async with owned_tx(conn):
        await _ws(conn, workspace_id)
        cur = await conn.execute(
            "SELECT status, count(*) FROM campaign_contacts WHERE campaign_id = %s GROUP BY 1",
            (campaign_id,),
        )
        return {s: n for s, n in await cur.fetchall()}


_TRANSITIONS = {
    "draft": {"running", "cancelled"},
    "running": {"paused", "cancelled"},
    "paused": {"running", "cancelled"},
}


async def set_status(
    conn: AsyncConnection, workspace_id: uuid.UUID, campaign_id: uuid.UUID, new: str
) -> str:
    """Move a campaign between states; returns the state it is now in."""
    async with owned_tx(conn):
        await _ws(conn, workspace_id)
        cur = await conn.execute(
            "SELECT status, consent_confirmed_at IS NOT NULL, "
            "(SELECT count(*) FROM campaign_contacts WHERE campaign_id = campaigns.id) "
            "FROM campaigns WHERE id = %s FOR UPDATE",
            (campaign_id,),
        )
        row = await cur.fetchone()
        if row is None:
            raise CampaignError("Campaign not found.")
        status, consent, contact_count = row
        if new not in _TRANSITIONS.get(status, set()):
            raise CampaignError(f"A {status} campaign cannot become {new}.")
        if new == "running" and not consent:
            raise CampaignError("Confirm consent before starting.")
        if new == "running" and contact_count == 0:
            raise CampaignError("Add contacts before starting.")
        await conn.execute(
            "UPDATE campaigns SET status = %s, "
            "started_at = CASE WHEN %s = 'running' "
            "THEN coalesce(started_at, now()) ELSE started_at END, "
            "completed_at = CASE WHEN %s = 'cancelled' THEN now() ELSE completed_at END "
            "WHERE id = %s",
            (new, new, new, campaign_id),
        )
        if new == "cancelled":
            await conn.execute(
                "UPDATE campaign_contacts SET next_attempt_at = NULL "
                "WHERE campaign_id = %s AND status = 'pending'",
                (campaign_id,),
            )
    return new


async def add_contacts(
    conn: AsyncConnection,
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    contacts: list[ContactInput],
) -> tuple[int, int]:
    """Returns (added, already_in_campaign). Numbers on the DNC list are added as 'dnc'."""
    if len(contacts) > MAX_CONTACTS:
        raise CampaignError(f"Too many contacts (limit {MAX_CONTACTS}).")
    async with owned_tx(conn):
        await _ws(conn, workspace_id)
        cur = await conn.execute("SELECT status FROM campaigns WHERE id = %s", (campaign_id,))
        row = await cur.fetchone()
        if row is None:
            raise CampaignError("Campaign not found.")
        if row[0] in TERMINAL:
            raise CampaignError("This campaign is finished.")
        cur = await conn.execute(
            "SELECT count(*) FROM campaign_contacts WHERE campaign_id = %s", (campaign_id,)
        )
        existing = (await cur.fetchone() or (0,))[0]
        if existing + len(contacts) > MAX_CONTACTS:
            raise CampaignError(f"A campaign can hold {MAX_CONTACTS} contacts.")
        added = 0
        for c in contacts:
            cur = await conn.execute(
                "INSERT INTO campaign_contacts (workspace_id, campaign_id, e164, name, timezone, "
                "variables, status) VALUES (%s, %s, %s, %s, %s, %s, "
                "CASE WHEN EXISTS (SELECT 1 FROM dnc_numbers d WHERE d.e164 = %s) "
                "THEN 'dnc' ELSE 'pending' END) ON CONFLICT DO NOTHING",
                (workspace_id, campaign_id, c.e164, c.name, c.timezone, Jsonb(c.variables), c.e164),
            )
            added += cur.rowcount
    return added, len(contacts) - added


async def list_contacts(
    conn: AsyncConnection,
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    *,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Contact], int]:
    async with owned_tx(conn):
        await _ws(conn, workspace_id)
        where, params = "ct.campaign_id = %s", [campaign_id]
        if status:
            where += " AND ct.status = %s"
            params.append(status)  # type: ignore[arg-type]
        cur = await conn.execute(f"SELECT count(*) FROM campaign_contacts ct WHERE {where}", params)
        total = (await cur.fetchone() or (0,))[0]
        sql = (
            f"SELECT {_CONTACT_COLS} WHERE {where} ORDER BY ct.created_at, ct.id LIMIT %s OFFSET %s"
        )
        cur = await conn.execute(sql, [*params, max(1, min(limit, 500)), max(0, offset)])
        return [Contact(*r) for r in await cur.fetchall()], total


async def contact_context(
    conn: AsyncConnection, workspace_id: uuid.UUID, contact_id: uuid.UUID
) -> tuple[uuid.UUID, str, dict[str, Any]] | None:
    """(campaign id, name, variables) for the worker to personalise a call."""
    async with owned_tx(conn):
        await _ws(conn, workspace_id)
        cur = await conn.execute(
            "SELECT campaign_id, name, variables FROM campaign_contacts WHERE id = %s",
            (contact_id,),
        )
        row = await cur.fetchone()
    return (row[0], row[1], row[2]) if row else None


# ------------------------------------------------------------------------------------ scheduler

_OUTCOME_SQL = (
    "CASE WHEN {src}.end_reason = 'voicemail' THEN 'voicemail' "
    "WHEN {src}.end_reason = 'not answered' THEN 'no_answer' "
    "WHEN {src}.call_status = 'failed' THEN 'failed' ELSE 'completed' END"
)
# After an outcome: finished, or back in the queue for another try if attempts remain.
_NEXT_STATUS = (
    "CASE WHEN {o} = 'completed' THEN 'completed' "
    "WHEN ct.attempts < c.max_attempts THEN 'pending' ELSE {o} END"
)
_NEXT_TIME = (
    "CASE WHEN {o} <> 'completed' AND ct.attempts < c.max_attempts "
    "THEN now() + make_interval(mins => c.retry_delay_min) END"
)


async def resolve_finished(
    conn: AsyncConnection, workspace_id: uuid.UUID, campaign_id: uuid.UUID
) -> int:
    """Turn finished calls (and calls that never started) into outcomes. Returns how many."""
    o_call = _OUTCOME_SQL.format(src="l")
    stuck = "'failed'"
    async with owned_tx(conn):
        await _ws(conn, workspace_id)
        sql = (
            "WITH l AS (SELECT DISTINCT ON (ct.id) ct.id AS contact_id, k.status AS call_status, "
            "k.end_reason FROM campaign_contacts ct JOIN calls k "
            "ON k.workspace_id = ct.workspace_id AND k.contact_id = ct.id "
            "AND k.started_at >= ct.claimed_at - interval '10 seconds' "
            "WHERE ct.campaign_id = %s AND ct.status = 'calling' AND k.status <> 'in_progress' "
            "ORDER BY ct.id, k.started_at DESC) "
            "UPDATE campaign_contacts ct SET "
            f"last_outcome = {o_call}, "
            f"status = {_NEXT_STATUS.format(o=o_call)}, "
            f"next_attempt_at = {_NEXT_TIME.format(o=o_call)} "
            "FROM l, campaigns c WHERE ct.id = l.contact_id AND c.id = ct.campaign_id"
        )
        cur = await conn.execute(sql, (campaign_id,))
        done = cur.rowcount
        for reason, cond in (
            (
                "call did not start",
                f"ct.claimed_at < now() - interval '{CALL_START_GRACE_S} seconds' AND NOT EXISTS "
                "(SELECT 1 FROM calls k WHERE k.workspace_id = ct.workspace_id "
                "AND k.contact_id = ct.id "
                "AND k.started_at >= ct.claimed_at - interval '10 seconds')",
            ),
            ("call timed out", f"ct.claimed_at < now() - interval '{CALL_MAX_S} seconds'"),
        ):
            sql = (
                "UPDATE campaign_contacts ct SET last_outcome = 'failed', "
                f"last_error = '{reason}', status = {_NEXT_STATUS.format(o=stuck)}, "
                f"next_attempt_at = {_NEXT_TIME.format(o=stuck)} "
                "FROM campaigns c WHERE c.id = ct.campaign_id AND ct.campaign_id = %s "
                f"AND ct.status = 'calling' AND {cond}"
            )
            cur = await conn.execute(sql, (campaign_id,))
            done += cur.rowcount
    return done


async def claim_due(
    conn: AsyncConnection, workspace_id: uuid.UUID, campaign_id: uuid.UUID
) -> list[Claim]:
    """Mark up to (max_concurrent - already calling) eligible contacts as calling and return them.

    Eligible: pending, retry time reached, today is a calling day and the time is inside the
    window in the contact's own timezone (or the campaign's), and not on the DNC list.
    """
    async with owned_tx(conn):
        await _ws(conn, workspace_id)
        cur = await conn.execute(
            "SELECT status, max_concurrent, "
            "(SELECT count(*) FROM campaign_contacts WHERE campaign_id = campaigns.id "
            "AND status = 'calling') FROM campaigns WHERE id = %s FOR UPDATE",
            (campaign_id,),
        )
        row = await cur.fetchone()
        if row is None or row[0] != "running":
            return []
        room = row[1] - row[2]
        await conn.execute(
            "UPDATE campaign_contacts SET status = 'dnc', next_attempt_at = NULL "
            "WHERE campaign_id = %s AND status = 'pending' "
            "AND EXISTS (SELECT 1 FROM dnc_numbers d WHERE d.e164 = campaign_contacts.e164)",
            (campaign_id,),
        )
        if room <= 0:
            return []
        local = "(now() AT TIME ZONE coalesce(ct.timezone, c.timezone))"
        cur = await conn.execute(
            "WITH due AS (SELECT ct.id FROM campaign_contacts ct "
            "JOIN campaigns c ON c.workspace_id = ct.workspace_id AND c.id = ct.campaign_id "
            "WHERE ct.campaign_id = %s AND ct.status = 'pending' "
            "AND coalesce(ct.next_attempt_at, now()) <= now() "
            f"AND (c.days_mask >> (extract(isodow FROM {local})::int - 1)) & 1 = 1 "
            f"AND {local}::time >= c.window_start AND {local}::time < c.window_end "
            "ORDER BY coalesce(ct.next_attempt_at, ct.created_at), ct.id "
            "LIMIT %s FOR UPDATE OF ct SKIP LOCKED) "
            "UPDATE campaign_contacts ct SET status = 'calling', attempts = ct.attempts + 1, "
            "claimed_at = now(), last_error = '' FROM due, campaigns c, phone_numbers n "
            "WHERE ct.id = due.id AND c.id = ct.campaign_id "
            "AND n.workspace_id = c.workspace_id AND n.id = c.from_number_id "
            "RETURNING ct.id, ct.e164, c.agent_id, c.from_number_id, n.lk_outbound_trunk_id",
            (campaign_id, room),
        )
        return [Claim(*r) for r in await cur.fetchall()]


async def release_failed(
    conn: AsyncConnection, workspace_id: uuid.UUID, contact_id: uuid.UUID, error: str
) -> None:
    """The dial itself failed (provider error): count the attempt, retry later if any remain."""
    o = "'failed'"
    async with owned_tx(conn):
        await _ws(conn, workspace_id)
        sql = (
            "UPDATE campaign_contacts ct SET last_outcome = 'failed', last_error = %s, "
            f"status = {_NEXT_STATUS.format(o=o)}, next_attempt_at = {_NEXT_TIME.format(o=o)} "
            "FROM campaigns c WHERE c.id = ct.campaign_id AND ct.id = %s"
        )
        await conn.execute(sql, (error[:200], contact_id))


async def maybe_complete(
    conn: AsyncConnection, workspace_id: uuid.UUID, campaign_id: uuid.UUID
) -> bool:
    async with owned_tx(conn):
        await _ws(conn, workspace_id)
        cur = await conn.execute(
            "UPDATE campaigns SET status = 'completed', completed_at = now() "
            "WHERE id = %s AND status = 'running' AND NOT EXISTS "
            "(SELECT 1 FROM campaign_contacts WHERE campaign_id = campaigns.id "
            "AND status IN ('pending', 'calling'))",
            (campaign_id,),
        )
        return cur.rowcount == 1


async def running_campaign_ids(conn: AsyncConnection, workspace_id: uuid.UUID) -> list[uuid.UUID]:
    async with owned_tx(conn):
        await _ws(conn, workspace_id)
        cur = await conn.execute("SELECT id FROM campaigns WHERE status = 'running'")
        return [r[0] for r in await cur.fetchall()]
