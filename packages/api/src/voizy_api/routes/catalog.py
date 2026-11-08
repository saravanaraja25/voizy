from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from voizy_core.domain import catalog
from voizy_core.services.auth import Principal

from voizy_api.web.auth import current_principal

router = APIRouter(prefix="/v1", tags=["catalog"])


class ModelOut(BaseModel):
    provider: str
    model: str
    label: str
    note: str


class CatalogOut(BaseModel):
    stt: list[ModelOut]
    llm: list[ModelOut]
    tts: list[ModelOut]
    default_voice_id: str


def _out(options: tuple[catalog.ModelOption, ...]) -> list[ModelOut]:
    return [
        ModelOut(provider=o.provider, model=o.model, label=o.label, note=o.note) for o in options
    ]


@router.get("/catalog", response_model=CatalogOut)
async def get_catalog(_: Annotated[Principal, Depends(current_principal)]) -> CatalogOut:
    return CatalogOut(
        stt=_out(catalog.STT),
        llm=_out(catalog.LLM),
        tts=_out(catalog.TTS),
        default_voice_id=catalog.DEFAULT_VOICE_ID,
    )
