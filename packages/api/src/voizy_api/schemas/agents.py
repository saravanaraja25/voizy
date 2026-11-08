from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field
from voizy_core.domain.agent_config import AgentConfig

from voizy_api.schemas.base import StrictModel


class AgentCreate(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    config: AgentConfig


class VersionCreate(StrictModel):
    config: AgentConfig


class VersionOut(BaseModel):
    version: int
    is_published: bool
    published_at: datetime | None
    created_at: datetime
    config: AgentConfig


class AgentOut(BaseModel):
    id: uuid.UUID
    name: str
    published_version: int | None
    archived: bool
    created_at: datetime
