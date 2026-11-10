from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from voizy_api.schemas.base import StrictModel

CampaignStatus = Literal["draft", "running", "paused", "completed", "cancelled"]
ContactStatus = Literal[
    "pending", "calling", "completed", "no_answer", "voicemail", "failed", "opted_out", "dnc"
]
CSV_LIMIT = 700_000


class CampaignOut(BaseModel):
    id: uuid.UUID
    name: str
    agent_id: uuid.UUID
    agent_name: str
    from_number_id: uuid.UUID | None  # None once the number has been disconnected
    from_number: str  # masked unless the reader holds calls:view_pii
    status: CampaignStatus
    timezone: str
    days: list[int]  # 0 = Monday
    window_start: str  # HH:MM
    window_end: str
    max_concurrent: int
    max_attempts: int
    retry_delay_min: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    counts: dict[str, int]


class ImportReport(BaseModel):
    added: int
    already_in_campaign: int
    rejected: list[tuple[int, str]]
    ignored_columns: list[str]


class CampaignCreated(BaseModel):
    campaign: CampaignOut
    import_report: ImportReport | None


class CampaignCreate(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    agent_id: uuid.UUID
    from_number_id: uuid.UUID
    timezone: str = Field(default="UTC", max_length=64)
    days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4], min_length=1, max_length=7)
    window_start: str = Field(default="09:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    window_end: str = Field(default="17:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    max_concurrent: int = Field(default=1, ge=1, le=10)
    max_attempts: int = Field(default=2, ge=1, le=5)
    retry_delay_min: int = Field(default=60, ge=5, le=10080)
    # The operator attests the people on the list agreed to be called.
    consent_confirmed: bool
    csv: str | None = Field(default=None, max_length=CSV_LIMIT)
    default_country_code: str | None = Field(default=None, pattern=r"^\+?[1-9][0-9]{0,3}$")


class CsvPayload(StrictModel):
    csv: str = Field(min_length=1, max_length=CSV_LIMIT)
    default_country_code: str | None = Field(default=None, pattern=r"^\+?[1-9][0-9]{0,3}$")
    agent_id: uuid.UUID | None = None  # lets the preview say which columns the agent will use


class CsvPreview(BaseModel):
    accepted: int
    rejected: list[tuple[int, str]]
    ignored_columns: list[str]
    sample: list[dict[str, str]]  # first rows, numbers masked


class ContactOut(BaseModel):
    id: uuid.UUID
    number: str  # masked unless the reader holds calls:view_pii
    name: str
    timezone: str | None
    status: ContactStatus
    attempts: int
    next_attempt_at: datetime | None
    last_outcome: str | None
    last_error: str
    last_call_id: uuid.UUID | None


class ContactListOut(BaseModel):
    items: list[ContactOut]
    total: int


class DncOut(BaseModel):
    number: str
    source: str
    note: str
    created_at: datetime


class DncCreate(StrictModel):
    e164: str = Field(pattern=r"^\+[1-9][0-9]{6,14}$")
    note: str = Field(default="", max_length=200)
