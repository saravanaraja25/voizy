from __future__ import annotations

import json
import uuid
from pathlib import Path

import psycopg
import pytest
from voizy_agent.config_source import (
    ConfigNotFoundError,
    load_dev_config,
    load_published_config,
    parse_job_metadata,
)
from voizy_core.db.pool import open_pool

WS, AG = uuid.uuid4(), uuid.uuid4()
CONFIG = {
    "name": "A",
    "system_prompt": "Hi",
    "stt": {"provider": "deepgram", "model": "nova-3"},
    "llm": {"provider": "google", "model": "gemini-2.5-flash"},
    "tts": {"provider": "cartesia", "model": "sonic-3", "voice_id": "v"},
}


def test_parse_job_metadata_accepts_only_two_uuids() -> None:
    ok = json.dumps({"workspace_id": str(WS), "agent_id": str(AG)})
    assert parse_job_metadata(ok) == (WS, AG)


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "not json",
        "[]",
        "null",
        "{}",
        json.dumps({"workspace_id": str(WS)}),
        json.dumps({"workspace_id": str(WS), "agent_id": "nope"}),
        json.dumps({"workspace_id": str(WS), "agent_id": str(AG), "extra": 1}),
        json.dumps({"workspace_id": 5, "agent_id": [1]}),
    ],
)
def test_parse_job_metadata_rejects_everything_else(raw: str | None) -> None:
    assert parse_job_metadata(raw) is None


def test_dev_config_loading(tmp_path: Path) -> None:
    good = tmp_path / "a.json"
    good.write_text(json.dumps(CONFIG))
    assert load_dev_config(good).name == "A"
    bad = tmp_path / "b.json"
    bad.write_text(json.dumps({**CONFIG, "surprise": 1}))
    with pytest.raises(ConfigNotFoundError):
        load_dev_config(bad)
    with pytest.raises(ConfigNotFoundError):
        load_dev_config(tmp_path / "missing.json")


@pytest.mark.asyncio
async def test_published_config_only_for_published_unarchived_same_workspace(
    admin_dsn: str, admin: psycopg.Connection, two_workspaces: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, b = two_workspaces
    agent, other = uuid.uuid4(), uuid.uuid4()
    for wid, aid in ((a, agent), (b, other)):
        admin.execute(
            "INSERT INTO agents (workspace_id, id, name) VALUES (%s, %s, 'x')", (wid, aid)
        )
        vid = uuid.uuid4()
        admin.execute(
            "INSERT INTO agent_versions "
            "(workspace_id, id, agent_id, version, config, is_published) "
            "VALUES (%s, %s, %s, 1, %s::jsonb, true)",
            (wid, vid, aid, json.dumps(CONFIG)),
        )
        admin.execute("UPDATE agents SET published_version_id = %s WHERE id = %s", (vid, aid))
    pool = await open_pool(admin_dsn)
    try:
        assert (await load_published_config(pool, a, agent)).name == "A"
        with pytest.raises(ConfigNotFoundError):  # another tenant's agent
            await load_published_config(pool, a, other)
        admin.execute("UPDATE agents SET archived_at = now() WHERE id = %s", (agent,))
        with pytest.raises(ConfigNotFoundError):  # archived
            await load_published_config(pool, a, agent)
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_draft_only_agent_has_no_config(
    admin_dsn: str, admin: psycopg.Connection, two_workspaces: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, _ = two_workspaces
    agent = uuid.uuid4()
    admin.execute("INSERT INTO agents (workspace_id, id, name) VALUES (%s, %s, 'x')", (a, agent))
    admin.execute(
        "INSERT INTO agent_versions (workspace_id, agent_id, version, config) "
        "VALUES (%s, %s, 1, %s::jsonb)",
        (a, agent, json.dumps(CONFIG)),
    )
    pool = await open_pool(admin_dsn)
    try:
        with pytest.raises(ConfigNotFoundError):
            await load_published_config(pool, a, agent)
    finally:
        await pool.close()
