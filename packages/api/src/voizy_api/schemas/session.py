from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel
from voizy_core.domain.permissions import Permission


class MeOut(BaseModel):
    workspace_id: uuid.UUID
    workspace_name: str
    api_key_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    email: str | None = None
    display_name: str | None = None
    csrf_token: str | None = None
    permissions: list[Permission]


class VersionSummary(BaseModel):
    version: int
    is_published: bool
    published_at: datetime | None
    created_at: datetime


class TestSessionOut(BaseModel):
    url: str
    token: str
    room: str
    identity: str
    expires_in_s: int
