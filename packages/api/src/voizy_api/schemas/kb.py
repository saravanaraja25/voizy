from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from voizy_api.schemas.base import StrictModel


class DocumentOut(BaseModel):
    id: uuid.UUID
    collection: str
    title: str
    source_name: str
    bytes: int
    chunk_count: int
    created_at: datetime


class DocumentCreate(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=400_000)
    collection: str = Field(default="default", pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    source_name: str = Field(default="", max_length=200)


class ChunkOut(BaseModel):
    heading: str
    text: str


class DocumentDetailOut(BaseModel):
    document: DocumentOut
    chunks: list[ChunkOut]


class HitOut(BaseModel):
    document_title: str
    heading: str
    text: str
    rank: float


class CollectionsOut(BaseModel):
    collections: list[str]
