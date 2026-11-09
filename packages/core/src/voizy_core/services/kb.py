"""Knowledge base: split documents into chunks and search them with Postgres full-text search.

Search is keyword-based (stemmed, ranked), so it finds the right passage when the caller's words
overlap the document's; it will miss a pure paraphrase. The caller's question is OR-ed term by term
so a long spoken question still matches, and results are ranked by how many terms hit.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from psycopg import AsyncConnection

from voizy_core.db.tx import owned_tx, set_local

MAX_CONTENT_CHARS = 400_000
MAX_CHUNKS = 600
CHUNK_CHARS = 900
OVERLAP_CHARS = 120
COLLECTION = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*\S)\s*$")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


class KbError(ValueError):
    """The document cannot be stored (too big, empty, ...). The message is safe to show."""


@dataclass(frozen=True)
class Chunk:
    heading: str
    text: str


@dataclass(frozen=True)
class Document:
    id: uuid.UUID
    collection: str
    title: str
    source_name: str
    bytes: int
    chunk_count: int


@dataclass(frozen=True)
class Hit:
    document_title: str
    heading: str
    text: str
    rank: float


def _split_long(block: str) -> list[str]:
    """Break an over-long paragraph on sentence boundaries, with a little overlap."""
    parts, current = [], ""
    for sentence in _SENTENCE_END.split(block):
        while len(sentence) > CHUNK_CHARS:  # no punctuation at all: hard split
            parts.append(
                (current + " " + sentence[:CHUNK_CHARS]).strip()
                if current
                else sentence[:CHUNK_CHARS]
            )
            current, sentence = "", sentence[CHUNK_CHARS - OVERLAP_CHARS :]
        if current and len(current) + len(sentence) + 1 > CHUNK_CHARS:
            parts.append(current)
            current = current[-OVERLAP_CHARS:].split(" ", 1)[-1]
        current = f"{current} {sentence}".strip()
    if current:
        parts.append(current)
    return parts


def chunk_text(content: str) -> list[Chunk]:
    """Paragraph-aware chunks of about CHUNK_CHARS, tagged with the Markdown heading above."""
    text = content.replace("\r\n", "\n").replace("\r", "\n")
    heading, chunks, buffer = "", [], ""

    def flush() -> None:
        nonlocal buffer
        if buffer.strip():
            chunks.append(Chunk(heading, buffer.strip()))
        buffer = ""

    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        match = _HEADING.match(block.split("\n", 1)[0])
        if match:
            flush()
            heading = match.group(1)[:200]
            block = block.split("\n", 1)[1].strip() if "\n" in block else ""
            if not block:
                continue
        pieces = _split_long(block) if len(block) > CHUNK_CHARS else [block]
        for piece in pieces:
            if buffer and len(buffer) + len(piece) + 2 > CHUNK_CHARS:
                flush()
            buffer = f"{buffer}\n\n{piece}".strip()
    flush()
    return chunks


async def add_document(
    conn: AsyncConnection,
    workspace_id: uuid.UUID,
    *,
    collection: str,
    title: str,
    source_name: str,
    content: str,
) -> Document:
    if not COLLECTION.match(collection):
        raise KbError("Collection names use lowercase letters, digits, - and _ (up to 40).")
    if not title.strip():
        raise KbError("Give the document a title.")
    if len(content) > MAX_CONTENT_CHARS:
        raise KbError("That document is too large (limit about 400,000 characters).")
    if "\x00" in content:
        raise KbError("That file is not plain text.")
    chunks = chunk_text(content)
    if not chunks:
        raise KbError("The document has no text.")
    if len(chunks) > MAX_CHUNKS:
        raise KbError("That document is too large (too many sections).")
    async with owned_tx(conn):
        await set_local(conn, "app.workspace_id", str(workspace_id))
        cur = await conn.execute(
            "INSERT INTO kb_documents (workspace_id, collection, title, source_name, bytes, "
            "chunk_count) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (
                workspace_id,
                collection,
                title.strip()[:200],
                source_name[:200],
                len(content.encode()),
                len(chunks),
            ),
        )
        row = await cur.fetchone()
        if row is None:
            raise RuntimeError("document insert returned no row")
        doc_id: uuid.UUID = row[0]
        async with conn.cursor() as c:
            await c.executemany(
                "INSERT INTO kb_chunks "
                "(workspace_id, document_id, collection, seq, heading, content) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                [
                    (workspace_id, doc_id, collection, i, ch.heading, ch.text)
                    for i, ch in enumerate(chunks)
                ],
            )
    return Document(
        doc_id,
        collection,
        title.strip()[:200],
        source_name[:200],
        len(content.encode()),
        len(chunks),
    )


async def list_documents(
    conn: AsyncConnection, workspace_id: uuid.UUID, collection: str | None = None
) -> list[tuple[Document, object]]:
    async with owned_tx(conn):
        await set_local(conn, "app.workspace_id", str(workspace_id))
        cur = await conn.execute(
            "SELECT id, collection, title, source_name, bytes, chunk_count, created_at "
            "FROM kb_documents WHERE (%s::text IS NULL OR collection = %s) "
            "ORDER BY created_at DESC, id",
            (collection, collection),
        )
        return [(Document(*r[:6]), r[6]) for r in await cur.fetchall()]


async def get_chunks(
    conn: AsyncConnection, workspace_id: uuid.UUID, document_id: uuid.UUID
) -> list[Chunk] | None:
    async with owned_tx(conn):
        await set_local(conn, "app.workspace_id", str(workspace_id))
        cur = await conn.execute("SELECT 1 FROM kb_documents WHERE id = %s", (document_id,))
        if await cur.fetchone() is None:
            return None
        cur = await conn.execute(
            "SELECT heading, content FROM kb_chunks WHERE document_id = %s ORDER BY seq",
            (document_id,),
        )
        return [Chunk(*r) for r in await cur.fetchall()]


async def delete_document(
    conn: AsyncConnection, workspace_id: uuid.UUID, document_id: uuid.UUID
) -> bool:
    async with owned_tx(conn):
        await set_local(conn, "app.workspace_id", str(workspace_id))
        cur = await conn.execute("DELETE FROM kb_documents WHERE id = %s", (document_id,))
        return cur.rowcount == 1


async def collections(conn: AsyncConnection, workspace_id: uuid.UUID) -> list[str]:
    async with owned_tx(conn):
        await set_local(conn, "app.workspace_id", str(workspace_id))
        cur = await conn.execute("SELECT DISTINCT collection FROM kb_documents ORDER BY 1")
        return [r[0] for r in await cur.fetchall()]


async def search(
    conn: AsyncConnection,
    workspace_id: uuid.UUID,
    collection: str,
    query: str,
    k: int = 3,
) -> list[Hit]:
    """Best passages for a spoken question; empty if nothing matches. Safe with odd input."""
    if not query.strip():
        return []
    async with owned_tx(conn):
        await set_local(conn, "app.workspace_id", str(workspace_id))
        cur = await conn.execute(
            "WITH q AS (SELECT replace(plainto_tsquery('english', %s)::text, '&', '|')::tsquery "
            "AS tq) "
            "SELECT d.title, c.heading, c.content, ts_rank_cd(c.tsv, q.tq) AS rank "
            "FROM kb_chunks c JOIN kb_documents d "
            "ON d.workspace_id = c.workspace_id AND d.id = c.document_id, q "
            "WHERE c.collection = %s AND c.tsv @@ q.tq AND q.tq::text <> '' "
            "ORDER BY rank DESC, c.seq LIMIT %s",
            (query[:500], collection, max(1, min(k, 10))),
        )
        return [Hit(*r) for r in await cur.fetchall()]


async def collection_text(
    conn: AsyncConnection, workspace_id: uuid.UUID, collection: str, max_chars: int
) -> str | None:
    """The whole collection as text for 'prompt' mode, or None if it would exceed max_chars."""
    async with owned_tx(conn):
        await set_local(conn, "app.workspace_id", str(workspace_id))
        cur = await conn.execute(
            "SELECT d.title, c.heading, c.content FROM kb_chunks c JOIN kb_documents d "
            "ON d.workspace_id = c.workspace_id AND d.id = c.document_id "
            "WHERE c.collection = %s ORDER BY d.created_at, d.id, c.seq",
            (collection,),
        )
        rows = await cur.fetchall()
    parts = [f"[{t}{' / ' + h if h else ''}]\n{c}" for t, h, c in rows]
    text = "\n\n".join(parts)
    return text if len(text) <= max_chars else None
