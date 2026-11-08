from __future__ import annotations

import uuid

import psycopg
import pytest
from psycopg import AsyncConnection
from voizy_core.security.secretbox import SecretBox
from voizy_core.services import secrets_store as store

pytestmark = pytest.mark.asyncio
WS = tuple[uuid.UUID, uuid.UUID]


def box() -> SecretBox:
    return SecretBox.from_env_value(f"k1:{SecretBox.generate_key()}")


async def test_roundtrip_hides_the_value_at_rest_and_in_listings(
    app_aconn: AsyncConnection, admin: psycopg.Connection, two_workspaces: WS
) -> None:
    a, _ = two_workspaces
    b = box()
    await store.put_secret(
        app_aconn,
        b,
        a,
        "clinic_api_key",
        "sk-live-0123456789abcdef",
        kind="tool",
        allowed_hosts=["api.clinic.example"],
        description="Clinic backend",
    )
    got = await store.get_secret(app_aconn, b, a, "clinic_api_key", kind="tool")
    assert got is not None and got.value == "sk-live-0123456789abcdef"
    assert got.allowed_hosts == ("api.clinic.example",)

    stored = admin.execute("SELECT ciphertext, hint FROM secrets").fetchone()
    assert stored is not None and "0123456789abcdef" not in stored[0] and stored[1] == "••••cdef"
    (info,) = await store.list_secrets(app_aconn, a, "tool")
    assert (info.name, info.hint, info.description) == (
        "clinic_api_key",
        "••••cdef",
        "Clinic backend",
    )
    assert "0123456789" not in repr(info)  # nothing recoverable in the listing


async def test_overwriting_replaces_the_value_and_keeps_one_row(
    app_aconn: AsyncConnection, admin: psycopg.Connection, two_workspaces: WS
) -> None:
    a, _ = two_workspaces
    b = box()
    for value in ("first-value-12345", "second-value-67890"):
        await store.put_secret(
            app_aconn, b, a, "k", value, kind="tool", allowed_hosts=["x.example.com"]
        )
    got = await store.get_secret(app_aconn, b, a, "k", kind="tool")
    assert got is not None and got.value == "second-value-67890"
    assert admin.execute("SELECT count(*) FROM secrets").fetchone() == (1,)


async def test_secrets_are_tenant_isolated_and_bound_to_their_workspace(
    app_aconn: AsyncConnection, admin: psycopg.Connection, two_workspaces: WS
) -> None:
    a, b_ws = two_workspaces
    bx = box()
    await store.put_secret(
        app_aconn, bx, a, "k", "value-123456789", kind="tool", allowed_hosts=["x.example.com"]
    )
    assert await store.get_secret(app_aconn, bx, b_ws, "k", kind="tool") is None  # RLS
    # Copying the ciphertext into another workspace does not make it readable there.
    admin.execute("UPDATE secrets SET workspace_id = %s", (b_ws,))
    assert await store.get_secret(app_aconn, bx, b_ws, "k", kind="tool") is None  # AAD mismatch


async def test_tool_secrets_cannot_use_integration_names_or_read_integration_secrets(
    app_aconn: AsyncConnection, two_workspaces: WS
) -> None:
    a, _ = two_workspaces
    b = box()
    with pytest.raises(store.SecretStoreError, match="reserved"):
        await store.put_secret(
            app_aconn,
            b,
            a,
            "openai_api_key",
            "x" * 20,
            kind="tool",
            allowed_hosts=["x.example.com"],
        )
    await store.put_secret(app_aconn, b, a, "openai_api_key", "sk-" + "a" * 30, kind="integration")
    # A tool can only resolve kind="tool", so it can never read an integration key.
    assert await store.get_secret(app_aconn, b, a, "openai_api_key", kind="tool") is None
    with pytest.raises(store.SecretStoreError):
        await store.put_secret(app_aconn, b, a, "not_an_integration", "x" * 20, kind="integration")


async def test_a_name_cannot_change_kind(app_aconn: AsyncConnection, two_workspaces: WS) -> None:
    a, _ = two_workspaces
    b = box()
    await store.put_secret(app_aconn, b, a, "twilio_auth_token", "a" * 32, kind="integration")
    with pytest.raises(store.SecretStoreError):
        await store.put_secret(
            app_aconn,
            b,
            a,
            "twilio_auth_token",
            "b" * 32,
            kind="tool",
            allowed_hosts=["x.example.com"],
        )


@pytest.mark.parametrize(
    ("value", "hosts", "message"),
    [
        ("", ["a.example.com"], "value"),
        ("line\nbreak", ["a.example.com"], "control"),
        ("ok-value-123456", [], "at least one host"),
        ("ok-value-123456", ["http://a.example.com"], "valid host"),
        (
            "ok-value-123456",
            ["a.example.com"] * 1 + [f"h{i}.example.com" for i in range(11)],
            "At most",
        ),
    ],
)
async def test_invalid_tool_secrets_are_rejected(
    app_aconn: AsyncConnection, two_workspaces: WS, value: str, hosts: list[str], message: str
) -> None:
    with pytest.raises(store.SecretStoreError, match=message):
        await store.put_secret(
            app_aconn, box(), two_workspaces[0], "k", value, kind="tool", allowed_hosts=hosts
        )


async def test_wrong_key_or_tampering_reads_as_not_configured(
    app_aconn: AsyncConnection, admin: psycopg.Connection, two_workspaces: WS
) -> None:
    a, _ = two_workspaces
    await store.put_secret(
        app_aconn, box(), a, "k", "value-123456789", kind="tool", allowed_hosts=["x.example.com"]
    )
    assert await store.get_secret(app_aconn, box(), a, "k", kind="tool") is None  # a different key
    admin.execute("UPDATE secrets SET ciphertext = 'garbage'")
    assert await store.get_secret(app_aconn, box(), a, "k", kind="tool") is None


async def test_meta_update_and_delete(app_aconn: AsyncConnection, two_workspaces: WS) -> None:
    a, _ = two_workspaces
    b = box()
    await store.put_secret(
        app_aconn, b, a, "k", "value-123456789", kind="tool", allowed_hosts=["x.example.com"]
    )
    assert await store.update_tool_secret_meta(
        app_aconn, a, "k", allowed_hosts=["*.y.example.com"], description="d"
    )
    got = await store.get_secret(app_aconn, b, a, "k", kind="tool")
    assert (
        got is not None
        and got.value == "value-123456789"
        and got.allowed_hosts == ("*.y.example.com",)
    )
    assert not await store.update_tool_secret_meta(
        app_aconn, a, "missing", allowed_hosts=["x.example.com"], description=""
    )
    assert await store.delete_secret(app_aconn, a, ["k"], kind="tool") == 1
    assert await store.get_secret(app_aconn, b, a, "k", kind="tool") is None


async def test_integration_values_are_read_together(
    app_aconn: AsyncConnection, two_workspaces: WS
) -> None:
    a, _ = two_workspaces
    b = box()
    await store.put_secret(
        app_aconn, b, a, "livekit_url", "wss://p.livekit.cloud", kind="integration"
    )
    await store.put_secret(app_aconn, b, a, "livekit_api_key", "APIabc123def", kind="integration")
    got = await store.get_integration_values(
        app_aconn, b, a, ["livekit_url", "livekit_api_key", "livekit_api_secret"]
    )
    assert got == {"livekit_url": "wss://p.livekit.cloud", "livekit_api_key": "APIabc123def"}


async def test_refuses_to_run_inside_an_open_transaction(
    app_aconn: AsyncConnection, two_workspaces: WS
) -> None:
    await app_aconn.execute("SELECT 1")
    with pytest.raises(RuntimeError, match="idle connection"):
        await store.list_secrets(app_aconn, two_workspaces[0], "tool")
