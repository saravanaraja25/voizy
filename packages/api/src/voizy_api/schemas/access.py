from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator
from voizy_core.domain.permissions import Permission

from voizy_api.schemas.base import StrictModel


class PermissionOut(BaseModel):
    name: Permission
    dangerous: bool


class RoleCreate(StrictModel):
    name: str = Field(min_length=1, max_length=60)
    permissions: list[Permission] = Field(max_length=len(Permission))


class RoleUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    permissions: list[Permission] | None = Field(default=None, max_length=len(Permission))


class RoleOut(BaseModel):
    id: uuid.UUID
    name: str
    is_system: bool
    is_locked: bool
    permissions: list[Permission]


class ApiKeyCreate(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    permissions: list[Permission] = Field(min_length=1, max_length=len(Permission))
    expires_at: datetime | None = None

    @field_validator("expires_at")
    @classmethod
    def _future(cls, v: datetime | None) -> datetime | None:
        if v is not None and (v.tzinfo is None or v <= datetime.now(UTC)):
            raise ValueError("expires_at must be a timezone-aware future time")
        return v


class ApiKeyOut(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str
    permissions: list[Permission]
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class ApiKeyCreated(ApiKeyOut):
    token: str  # returned exactly once
