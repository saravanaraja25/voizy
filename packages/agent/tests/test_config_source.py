from __future__ import annotations

import json
import uuid
from pathlib import Path

import psycopg
import pytest
from voizy_agent.config_source import (
    ConfigNotFoundError,
    load_config,
    load_dev_config,
    load_published_config,
)
from voizy_core.db.pool import open_pool
from voizy_core.domain.dispatch import DispatchTarget

WS, AG = uuid.uuid4(), uuid.uuid4()
CONFIG = {
    "name": "A",
    "system_prompt": "Hi",
    "stt": {"provider": "deepgram", "model": "nova-3"},
    "llm": {"provider": "google", "model": "gemini-2.5-flash"},
    "tts": {"provider": "cartesia", "model": "sonic-3", "voice_id": "v"},
}


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


@pytest.mark.asyncio
async def test_named_version_loads_drafts_for_tests_but_stays_workspace_scoped(
    admin_dsn: str, admin: psycopg.Connection, two_workspaces: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, b = two_workspaces
    agent = uuid.uuid4()
    admin.execute("INSERT INTO agents (workspace_id, id, name) VALUES (%s, %s, 'x')", (a, agent))
    for ver, name in ((1, "published-one"), (2, "draft-two")):
        admin.execute(
            "INSERT INTO agent_versions (workspace_id, agent_id, version, config) "
            "VALUES (%s, %s, %s, %s::jsonb)",
            (a, agent, ver, json.dumps({**CONFIG, "name": name})),
        )
    pool = await open_pool(admin_dsn)
    try:
        draft = await load_config(pool, DispatchTarget(a, agent, 2))
        assert draft.name == "draft-two"
        with pytest.raises(ConfigNotFoundError):  # no published version, none requested
            await load_config(pool, DispatchTarget(a, agent))
        with pytest.raises(ConfigNotFoundError):  # version that does not exist
            await load_config(pool, DispatchTarget(a, agent, 9))
        with pytest.raises(ConfigNotFoundError):  # wrong workspace sees nothing
            await load_config(pool, DispatchTarget(b, agent, 2))
    finally:
        await pool.close()
