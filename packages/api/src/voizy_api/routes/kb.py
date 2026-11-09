"""Knowledge base documents and a search endpoint for trying retrieval."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from voizy_core.db.pool import workspace_tx
from voizy_core.domain.permissions import Permission
from voizy_core.services import kb
from voizy_core.services.auth import Principal

from voizy_api.schemas.kb import (
    ChunkOut,
    CollectionsOut,
    DocumentCreate,
    DocumentDetailOut,
    DocumentOut,
    HitOut,
)
from voizy_api.web.auth import require
from voizy_api.web.common import audit, not_found

router = APIRouter(prefix="/v1/kb", tags=["knowledge"])
Reader = Annotated[Principal, Depends(require(Permission.KB_READ))]
Manager = Annotated[Principal, Depends(require(Permission.KB_MANAGE))]


def _out(d: kb.Document, created_at: object) -> DocumentOut:
    return DocumentOut(
        id=d.id,
        collection=d.collection,
        title=d.title,
        source_name=d.source_name,
        bytes=d.bytes,
        chunk_count=d.chunk_count,
        created_at=created_at,  # type: ignore[arg-type]
    )


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(
    request: Request, p: Reader, collection: Annotated[str | None, Query(max_length=40)] = None
) -> list[DocumentOut]:
    async with request.app.state.pool.connection() as conn:
        return [_out(d, at) for d, at in await kb.list_documents(conn, p.workspace_id, collection)]


@router.get("/collections", response_model=CollectionsOut)
async def list_collections(request: Request, p: Reader) -> CollectionsOut:
    async with request.app.state.pool.connection() as conn:
        return CollectionsOut(collections=await kb.collections(conn, p.workspace_id))


@router.post("/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def add_document(body: DocumentCreate, request: Request, p: Manager) -> DocumentOut:
    pool = request.app.state.pool
    try:
        async with pool.connection() as conn:
            doc = await kb.add_document(
                conn,
                p.workspace_id,
                collection=body.collection,
                title=body.title,
                source_name=body.source_name,
                content=body.content,
            )
    except kb.KbError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    async with workspace_tx(pool, p.workspace_id) as conn:
        await audit(
            conn,
            p,
            "kb.add",
            "kb_document",
            doc.id,
            title=doc.title,
            collection=doc.collection,
            chunks=doc.chunk_count,
        )
    async with pool.connection() as conn:
        listed = await kb.list_documents(conn, p.workspace_id, doc.collection)
    created = next((at for d, at in listed if d.id == doc.id), None)
    return _out(doc, created)


@router.get("/documents/{document_id}", response_model=DocumentDetailOut)
async def get_document(document_id: uuid.UUID, request: Request, p: Reader) -> DocumentDetailOut:
    async with request.app.state.pool.connection() as conn:
        chunks = await kb.get_chunks(conn, p.workspace_id, document_id)
        listed = await kb.list_documents(conn, p.workspace_id)
    found = next(((d, at) for d, at in listed if d.id == document_id), None)
    if chunks is None or found is None:
        raise not_found()
    return DocumentDetailOut(
        document=_out(*found), chunks=[ChunkOut(heading=c.heading, text=c.text) for c in chunks]
    )


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: uuid.UUID, request: Request, p: Manager) -> Response:
    pool = request.app.state.pool
    async with pool.connection() as conn:
        deleted = await kb.delete_document(conn, p.workspace_id, document_id)
    if not deleted:
        raise not_found()
    async with workspace_tx(pool, p.workspace_id) as conn:
        await audit(conn, p, "kb.delete", "kb_document", document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/search", response_model=list[HitOut])
async def search(
    request: Request,
    p: Reader,
    q: Annotated[str, Query(min_length=1, max_length=500)],
    collection: Annotated[
        str, Query(max_length=40, pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    ] = "default",
    k: Annotated[int, Query(ge=1, le=10)] = 3,
) -> list[HitOut]:
    async with request.app.state.pool.connection() as conn:
        hits = await kb.search(conn, p.workspace_id, collection, q, k)
    return [
        HitOut(document_title=h.document_title, heading=h.heading, text=h.text, rank=h.rank)
        for h in hits
    ]
