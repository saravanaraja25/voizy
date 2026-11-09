from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class CallOut(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: str
    agent_version: int
    source: Literal["test", "inbound", "outbound"]
    status: Literal["in_progress", "completed", "failed"]
    started_at: datetime
    ended_at: datetime | None
    duration_s: int | None
    end_reason: str
    turn_count: int
    latency_p50_ms: int | None
    transcript_stored: bool
    # The other party's number: full with calls:view_pii, otherwise masked ('•••• 0134').
    remote_number: str | None = None
    remote_number_masked: bool = False


class CallListOut(BaseModel):
    items: list[CallOut]
    next_cursor: str | None = None


class TurnOut(BaseModel):
    seq: int
    role: Literal["user", "agent", "tool"]
    text: str
    tool_name: str | None
    tool_ok: bool | None
    tool_ms: int | None
    latency: dict[str, int] | None
    at: datetime


class CallDetailOut(BaseModel):
    call: CallOut
    turns: list[TurnOut]
    transcript_visible: bool  # False when the caller lacks calls:view_transcript


class CallSummaryOut(BaseModel):
    days: int
    total: int
    completed: int
    failed: int
    avg_duration_s: int | None
    median_latency_ms: int | None
