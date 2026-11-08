from typing import Any

import pytest
from pydantic import ValidationError
from voizy_core.domain.agent_config import AgentConfig, HttpTool


def cfg(auth: dict[str, Any] | None) -> AgentConfig:
    tool: dict[str, Any] = {
        "kind": "http",
        "name": "lookup",
        "description": "d",
        "url": "https://x.example/a",
    }
    if auth is not None:
        tool["auth"] = auth
    return AgentConfig.model_validate(
        {
            "name": "A",
            "system_prompt": "Hi",
            "stt": {"provider": "deepgram", "model": "nova-3"},
            "llm": {"provider": "google", "model": "gemini-2.5-flash"},
            "tts": {"provider": "cartesia", "model": "sonic-turbo", "voice_id": "v"},
            "tools": [tool],
        }
    )


def tool_of(config: AgentConfig) -> HttpTool:
    tool = config.tools[0]
    assert isinstance(tool, HttpTool)
    return tool


def test_tools_default_to_no_auth_and_refer_to_secrets_by_name_only() -> None:
    assert tool_of(cfg(None)).auth is None
    auth = tool_of(cfg({"kind": "bearer", "secret": "clinic_api_key"})).auth
    assert auth is not None
    assert auth.secret == "clinic_api_key"  # noqa: S105 - a secret *name*, not a value


@pytest.mark.parametrize(
    "auth",
    [
        {"kind": "bearer", "secret": "Not Snake"},
        {"kind": "bearer", "secret": ""},
        {"kind": "bearer", "secret": "../etc"},
        {"kind": "header", "secret": "k"},  # header auth needs a header name
        {"kind": "header", "secret": "k", "header_name": "Bad Header"},
        {"kind": "header", "secret": "k", "header_name": "Host"},
        {"kind": "header", "secret": "k", "header_name": "content-length"},
        {"kind": "header", "secret": "k", "header_name": "Cookie"},
        {"kind": "bearer", "secret": "k", "header_name": "X-Key"},  # only for header auth
        {"kind": "oauth", "secret": "k"},
        {"kind": "bearer", "secret": "k", "value": "inline-secret"},  # never inline
    ],
)
def test_bad_auth_is_rejected(auth: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        cfg(auth)


def test_header_and_basic_auth_are_accepted() -> None:
    cfg({"kind": "header", "secret": "k", "header_name": "X-Api-Key"})
    cfg({"kind": "basic", "secret": "k"})


def test_the_old_inline_reference_field_is_gone() -> None:
    tool = {
        "kind": "http",
        "name": "t",
        "description": "d",
        "url": "https://x.example/a",
        "auth_secret_ref": "k",
    }
    with pytest.raises(ValidationError):
        AgentConfig.model_validate(
            {
                "name": "A",
                "system_prompt": "Hi",
                "tools": [tool],
                "stt": {"provider": "deepgram", "model": "nova-3"},
                "llm": {"provider": "google", "model": "gemini-2.5-flash"},
                "tts": {"provider": "cartesia", "model": "sonic-turbo", "voice_id": "v"},
            }
        )
