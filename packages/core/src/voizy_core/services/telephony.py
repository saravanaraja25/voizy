"""Phone number records. Talking to Twilio and LiveKit happens in the API; this is storage only."""

from __future__ import annotations

import datetime as dt
import re
import uuid
from dataclasses import dataclass

import psycopg.errors
from psycopg import AsyncConnection

from voizy_core.db.tx import owned_tx, set_local

E164 = re.compile(r"^\+[1-9][0-9]{6,14}$")


class NumberTakenError(Exception):
    """The number is already connected (in this or another workspace)."""


@dataclass(frozen=True)
class Trunk:
    twilio_trunk_sid: str
    termination_domain: str
    twilio_credential_list_sid: str


@dataclass(frozen=True)
class PhoneNumber:
    id: uuid.UUID
    e164: str
    label: str
    agent_id: uuid.UUID | None
    agent_name: str | None
    twilio_number_sid: str
    twilio_credential_sid: str
    lk_inbound_trunk_id: str
    lk_dispatch_rule_id: str
    lk_outbound_trunk_id: str
    created_at: dt.datetime


_COLS = (
    "n.id, n.e164, n.label, n.agent_id, a.name, n.twilio_number_sid, n.twilio_credential_sid, "
    "n.lk_inbound_trunk_id, n.lk_dispatch_rule_id, n.lk_outbound_trunk_id, n.created_at "
    "FROM phone_numbers n LEFT JOIN agents a "
    "ON a.workspace_id = n.workspace_id AND a.id = n.agent_id"
)


async def get_trunk(conn: AsyncConnection, workspace_id: uuid.UUID) -> Trunk | None:
    async with owned_tx(conn):
        await set_local(conn, "app.workspace_id", str(workspace_id))
        cur = await conn.execute(
            "SELECT twilio_trunk_sid, termination_domain, twilio_credential_list_sid "
            "FROM telephony_trunks"
        )
        row = await cur.fetchone()
    return Trunk(*row) if row else None


async def save_trunk(conn: AsyncConnection, workspace_id: uuid.UUID, trunk: Trunk) -> None:
    async with owned_tx(conn):
        await set_local(conn, "app.workspace_id", str(workspace_id))
        await conn.execute(
            "INSERT INTO telephony_trunks (workspace_id, twilio_trunk_sid, termination_domain, "
            "twilio_credential_list_sid) VALUES (%s, %s, %s, %s)",
            (
                workspace_id,
                trunk.twilio_trunk_sid,
                trunk.termination_domain,
                trunk.twilio_credential_list_sid,
            ),
        )


async def add_number(
    conn: AsyncConnection,
    workspace_id: uuid.UUID,
    *,
    e164: str,
    label: str,
    agent_id: uuid.UUID | None,
    twilio_number_sid: str,
    twilio_credential_sid: str,
    lk_inbound_trunk_id: str,
    lk_dispatch_rule_id: str,
    lk_outbound_trunk_id: str,
) -> uuid.UUID:
    try:
        async with owned_tx(conn):
            await set_local(conn, "app.workspace_id", str(workspace_id))
            cur = await conn.execute(
                "INSERT INTO phone_numbers (workspace_id, e164, label, agent_id, "
                "twilio_number_sid, twilio_credential_sid, lk_inbound_trunk_id, "
                "lk_dispatch_rule_id, lk_outbound_trunk_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    workspace_id,
                    e164,
                    label,
                    agent_id,
                    twilio_number_sid,
                    twilio_credential_sid,
                    lk_inbound_trunk_id,
                    lk_dispatch_rule_id,
                    lk_outbound_trunk_id,
                ),
            )
            row = await cur.fetchone()
    except psycopg.errors.UniqueViolation as exc:
        raise NumberTakenError(e164) from exc
    if row is None:
        raise RuntimeError("phone number insert returned no row")
    return row[0]  # type: ignore[no-any-return]


async def list_numbers(conn: AsyncConnection, workspace_id: uuid.UUID) -> list[PhoneNumber]:
    async with owned_tx(conn):
        await set_local(conn, "app.workspace_id", str(workspace_id))
        sql = f"SELECT {_COLS} ORDER BY n.created_at, n.id"  # noqa: S608
        cur = await conn.execute(sql)
        return [PhoneNumber(*r) for r in await cur.fetchall()]


async def get_number(
    conn: AsyncConnection, workspace_id: uuid.UUID, number_id: uuid.UUID
) -> PhoneNumber | None:
    async with owned_tx(conn):
        await set_local(conn, "app.workspace_id", str(workspace_id))
        sql = f"SELECT {_COLS} WHERE n.id = %s"  # noqa: S608 - fixed column list
        cur = await conn.execute(sql, (number_id,))
        row = await cur.fetchone()
    return PhoneNumber(*row) if row else None


async def update_assignment(
    conn: AsyncConnection,
    workspace_id: uuid.UUID,
    number_id: uuid.UUID,
    *,
    agent_id: uuid.UUID | None,
    label: str | None,
    lk_dispatch_rule_id: str,
) -> bool:
    async with owned_tx(conn):
        await set_local(conn, "app.workspace_id", str(workspace_id))
        cur = await conn.execute(
            "UPDATE phone_numbers SET agent_id = %s, label = coalesce(%s, label), "
            "lk_dispatch_rule_id = %s WHERE id = %s",
            (agent_id, label, lk_dispatch_rule_id, number_id),
        )
        return cur.rowcount == 1


async def campaign_blockers(
    conn: AsyncConnection, workspace_id: uuid.UUID, number_id: uuid.UUID
) -> list[str]:
    """Names of campaigns that still need this number (draft, running or paused)."""
    async with owned_tx(conn):
        await set_local(conn, "app.workspace_id", str(workspace_id))
        cur = await conn.execute(
            "SELECT name FROM campaigns WHERE from_number_id = %s "
            "AND status IN ('draft', 'running', 'paused') ORDER BY name",
            (number_id,),
        )
        return [r[0] for r in await cur.fetchall()]


async def delete_number(
    conn: AsyncConnection, workspace_id: uuid.UUID, number_id: uuid.UUID
) -> bool:
    async with owned_tx(conn):
        await set_local(conn, "app.workspace_id", str(workspace_id))
        cur = await conn.execute("DELETE FROM phone_numbers WHERE id = %s", (number_id,))
        return cur.rowcount == 1
