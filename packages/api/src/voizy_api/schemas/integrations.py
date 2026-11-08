from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from voizy_api.schemas.base import StrictModel


class FieldStatus(BaseModel):
    name: str
    label: str
    secret: bool
    configured: bool
    value: str | None = None  # only for non-sensitive fields (a URL, an account id)
    hint: str = ""  # e.g. '••••abcd' for a stored key
    placeholder: str = ""
    help: str = ""


class IntegrationOut(BaseModel):
    id: str
    label: str
    description: str
    used_for: str
    configured: bool
    fields: list[FieldStatus]


class IntegrationUpdate(StrictModel):
    # Blank values keep what is stored, so a key never has to be re-entered to change a URL.
    values: dict[str, str] = Field(max_length=8)


class TestResultOut(BaseModel):
    ok: bool
    message: str


class ToolSecretOut(BaseModel):
    name: str
    description: str
    allowed_hosts: list[str]
    hint: str
    updated_at: datetime


class ToolSecretPut(StrictModel):
    value: str | None = Field(default=None, max_length=4096)  # omit to change only the hosts
    allowed_hosts: list[str] = Field(max_length=10)
    description: str = Field(default="", max_length=200)
