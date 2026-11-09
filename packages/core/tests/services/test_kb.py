# ruff: noqa: E501
from __future__ import annotations

import uuid

import psycopg
import pytest
from psycopg import AsyncConnection
from voizy_core.services import kb

WS = tuple[uuid.UUID, uuid.UUID]

DOC = """# Opening hours

We are open Monday to Friday from 9am to 6pm, and Saturdays from 10am to 4pm. We are closed on Sundays.

# Returns

You can return any unworn item within 30 days of delivery for a full refund. Refunds arrive within five business days of the item reaching our warehouse.

# Shipping

Standard shipping takes three to five business days. Express shipping takes one to two business days and costs fifteen dollars.
"""


def test_chunks_follow_headings_and_respect_size() -> None:
    chunks = kb.chunk_text(DOC)
    assert [c.heading for c in chunks] == ["Opening hours", "Returns", "Shipping"]
    assert all(len(c.text) <= kb.CHUNK_CHARS + kb.OVERLAP_CHARS for c in chunks)
    long = kb.chunk_text("Sentence one is here. " * 200)
    assert len(long) > 3 and all(len(c.text) <= kb.CHUNK_CHARS + 20 for c in long)
    assert kb.chunk_text("   \n\n  ") == []
    assert kb.chunk_text("x" * 5000)  # no punctuation at all still splits


async def test_search_finds_by_stemmed_words_and_ranks(
    app_aconn: AsyncConnection, admin: psycopg.Connection, two_workspaces: WS
) -> None:
    a, _ = two_workspaces
    await kb.add_document(
        app_aconn, a, collection="shop", title="FAQ", source_name="faq.md", content=DOC
    )
    hits = await kb.search(app_aconn, a, "shop", "what are your opening hours on Saturday?")
    assert hits and hits[0].heading == "Opening hours" and "10am" in hits[0].text
    hits = await kb.search(
        app_aconn, a, "shop", "can I return shoes after a month, how fast is the refund"
    )
    assert hits[0].heading == "Returns"
    assert await kb.search(app_aconn, a, "shop", "quantum chromodynamics") == []
    assert await kb.search(app_aconn, a, "shop", "the and of") == []  # only stop words
    for odd in ("", "   ", "'; DROP TABLE kb_chunks; --", "a & b | !c (", "\x01\x02"):
        await kb.search(app_aconn, a, "shop", odd)  # never raises
    assert await kb.search(app_aconn, a, "other", "opening hours") == []  # collections isolate


async def test_tenant_isolation_and_delete(
    app_aconn: AsyncConnection, admin: psycopg.Connection, two_workspaces: WS
) -> None:
    a, b = two_workspaces
    doc = await kb.add_document(
        app_aconn, a, collection="default", title="T", source_name="", content=DOC
    )
    assert await kb.search(app_aconn, b, "default", "opening hours") == []
    assert await kb.get_chunks(app_aconn, b, doc.id) is None
    assert not await kb.delete_document(app_aconn, b, doc.id)
    assert await kb.list_documents(app_aconn, b) == []
    assert await kb.collections(app_aconn, a) == ["default"]
    assert await kb.delete_document(app_aconn, a, doc.id)
    assert admin.execute("SELECT count(*) FROM kb_chunks").fetchone() == (0,)


async def test_rejects_bad_input(
    app_aconn: AsyncConnection, admin: psycopg.Connection, two_workspaces: WS
) -> None:
    a, _ = two_workspaces
    for kwargs, message in (
        ({"collection": "Bad Name", "title": "t", "content": "x"}, "Collection"),
        ({"collection": "default", "title": " ", "content": "x"}, "title"),
        ({"collection": "default", "title": "t", "content": "  \n "}, "no text"),
        ({"collection": "default", "title": "t", "content": "a\x00b"}, "plain text"),
        (
            {"collection": "default", "title": "t", "content": "x" * (kb.MAX_CONTENT_CHARS + 1)},
            "too large",
        ),
    ):
        with pytest.raises(kb.KbError, match=message):
            await kb.add_document(app_aconn, a, source_name="", **kwargs)


async def test_prompt_mode_returns_text_only_when_small_enough(
    app_aconn: AsyncConnection, admin: psycopg.Connection, two_workspaces: WS
) -> None:
    a, _ = two_workspaces
    await kb.add_document(
        app_aconn, a, collection="default", title="FAQ", source_name="", content=DOC
    )
    text = await kb.collection_text(app_aconn, a, "default", 10_000)
    assert text is not None and "Opening hours" in text and "[FAQ" in text
    assert await kb.collection_text(app_aconn, a, "default", 50) is None
