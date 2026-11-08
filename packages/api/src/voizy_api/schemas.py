from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from voizy_core.agent_config import AgentConfig


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentCreate(_Strict):
    name: str = Field(min_length=1, max_length=100)
    config: AgentConfig


class VersionCreate(_Strict):
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
