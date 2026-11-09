# ruff: noqa: E501
"""Knowledge base API: permissions, validation, isolation, audit."""

from __future__ import annotations

import httpx
import psycopg
import pytest
from voizy_api.testing import MakeKey, bearer
from voizy_core.domain.permissions import Permission
from voizy_core.services.bootstrap import BootstrapResult

pytestmark = pytest.mark.asyncio
DOC = "# Hours\n\nWe are open nine to five on weekdays.\n\n# Returns\n\nReturns are accepted within 30 days."


async def test_add_list_search_view_delete_and_audit(
    client: httpx.AsyncClient, workspace_a: BootstrapResult, admin: psycopg.Connection
) -> None:
    h = bearer(workspace_a.token)
    r = await client.post(
        "/v1/kb/documents", headers=h, json={"title": "FAQ", "content": DOC, "collection": "shop"}
    )
    assert r.status_code == 201 and r.json()["chunk_count"] == 2
    doc_id = r.json()["id"]
    assert [d["title"] for d in (await client.get("/v1/kb/documents", headers=h)).json()] == ["FAQ"]
    assert (await client.get("/v1/kb/collections", headers=h)).json() == {"collections": ["shop"]}
    hits = (
        await client.get(
            "/v1/kb/search",
            headers=h,
            params={"q": "how long to return an item", "collection": "shop"},
        )
    ).json()
    assert hits and hits[0]["heading"] == "Returns"
    assert (await client.get("/v1/kb/search", headers=h, params={"q": "zzzz qqqq"})).json() == []
    detail = (await client.get(f"/v1/kb/documents/{doc_id}", headers=h)).json()
    assert [c["heading"] for c in detail["chunks"]] == ["Hours", "Returns"]
    assert (await client.delete(f"/v1/kb/documents/{doc_id}", headers=h)).status_code == 204
    assert (await client.delete(f"/v1/kb/documents/{doc_id}", headers=h)).status_code == 404
    actions = [
        a
        for (a,) in admin.execute(
            "SELECT action FROM audit_log WHERE action LIKE 'kb.%' ORDER BY created_at"
        ).fetchall()
    ]
    assert actions == ["kb.add", "kb.delete"]


async def test_bad_input_is_rejected_cleanly(
    client: httpx.AsyncClient, workspace_a: BootstrapResult
) -> None:
    h = bearer(workspace_a.token)
    for body in (
        {"title": "", "content": "x"},
        {"title": "t", "content": ""},
        {"title": "t", "content": "x", "collection": "Bad Name"},
        {"title": "t", "content": "x", "surprise": 1},
        {"title": "t", "content": "   \n  "},
        {"title": "t", "content": "a\x00b"},
    ):
        assert (await client.post("/v1/kb/documents", headers=h, json=body)).status_code == 422
    assert (await client.get("/v1/kb/search", headers=h, params={"q": ""})).status_code == 422


async def test_permissions_and_isolation(
    client: httpx.AsyncClient,
    workspace_a: BootstrapResult,
    make_key: MakeKey,
    two_workspaces: tuple[object, object],
) -> None:
    h = bearer(workspace_a.token)
    doc = (
        await client.post("/v1/kb/documents", headers=h, json={"title": "FAQ", "content": DOC})
    ).json()
    reader = bearer(make_key(workspace_a.workspace_id, frozenset({Permission.KB_READ})))
    assert (await client.get("/v1/kb/documents", headers=reader)).status_code == 200
    assert (
        await client.post("/v1/kb/documents", headers=reader, json={"title": "x", "content": "y"})
    ).status_code == 403
    assert (await client.delete(f"/v1/kb/documents/{doc['id']}", headers=reader)).status_code == 403
    nothing = bearer(make_key(workspace_a.workspace_id, frozenset({Permission.AGENTS_READ})))
    assert (await client.get("/v1/kb/documents", headers=nothing)).status_code == 403
    assert (await client.get("/v1/kb/documents")).status_code == 401
    other = bearer(make_key(two_workspaces[1]))
    assert (await client.get("/v1/kb/documents", headers=other)).json() == []
    assert (await client.get(f"/v1/kb/documents/{doc['id']}", headers=other)).status_code == 404
    assert (await client.delete(f"/v1/kb/documents/{doc['id']}", headers=other)).status_code == 404
