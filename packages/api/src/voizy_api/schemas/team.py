from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr

from voizy_api.schemas.base import StrictModel


class InviteCreate(StrictModel):
    email: EmailStr
    # Omitted = Superadmin. Anything else needs custom roles to be enabled.
    role_id: uuid.UUID | None = None


class InviteOut(BaseModel):
    id: uuid.UUID
    email: str
    role_name: str
    expires_at: datetime
    created_at: datetime


class InviteCreated(InviteOut):
    token: str  # returned exactly once
    invite_path: str


class InvitePreview(BaseModel):
    workspace_name: str
    email: str
    role_name: str
    expires_at: datetime


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    role_id: uuid.UUID
    role_name: str
    joined_at: datetime
    last_login_at: datetime | None


class MemberRoleChange(StrictModel):
    role_id: uuid.UUID


class AssignableRole(BaseModel):
    id: uuid.UUID
    name: str
