from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from voizy_api.schemas.base import StrictModel

E164_PATTERN = r"^\+[1-9][0-9]{6,14}$"


class PhoneNumberOut(BaseModel):
    id: uuid.UUID
    e164: str
    label: str
    agent_id: uuid.UUID | None
    agent_name: str | None
    created_at: datetime


class PhoneNumberCreate(StrictModel):
    e164: str = Field(pattern=E164_PATTERN)
    label: str = Field(default="", max_length=80)
    agent_id: uuid.UUID | None = None


class PhoneNumberUpdate(StrictModel):
    # Sent (even as null) = change who answers inbound calls; omitted = leave as is.
    agent_id: uuid.UUID | None = None
    label: str | None = Field(default=None, max_length=80)


class OutboundCall(StrictModel):
    from_number_id: uuid.UUID
    agent_id: uuid.UUID
    to: str = Field(pattern=E164_PATTERN)
    # The caller attests they may call this person. Campaign-level consent/DND policy comes later.
    consent_confirmed: bool


class OutboundCallOut(BaseModel):
    room: str
