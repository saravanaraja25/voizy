from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from voizy_api.schemas.base import StrictModel


class SetupStatus(BaseModel):
    needs_setup: bool


class SetupRequest(StrictModel):
    setup_token: str = Field(min_length=8, max_length=200)
    workspace_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=100)
    password: str = Field(max_length=256)  # policy is enforced in the handler


class LoginRequest(StrictModel):
    email: EmailStr
    password: str = Field(max_length=256)
    workspace_id: uuid.UUID | None = None


class PasswordChange(StrictModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


class AcceptInvite(StrictModel):
    display_name: str = Field(min_length=1, max_length=100)
    password: str = Field(max_length=256)


class Notice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    detail: str
