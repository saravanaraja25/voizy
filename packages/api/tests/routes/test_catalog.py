from __future__ import annotations

import httpx
from voizy_api.testing import bearer
from voizy_core.services.bootstrap import BootstrapResult


async def test_catalog_requires_auth_and_lists_measured_options(
    client: httpx.AsyncClient, workspace_a: BootstrapResult
) -> None:
    assert (await client.get("/v1/catalog")).status_code == 401
    body = (await client.get("/v1/catalog", headers=bearer(workspace_a.token))).json()
    assert {"stt", "llm", "tts", "default_voice_id"} <= body.keys()
    llm_ids = [f"{m['provider']}/{m['model']}" for m in body["llm"]]
    assert "google/gemini-2.5-flash" in llm_ids
    assert all(m["label"] for kind in ("stt", "llm", "tts") for m in body[kind])
