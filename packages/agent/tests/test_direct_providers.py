"""Components set to 'own key' use the provider's plugin, never silently LiveKit."""

from __future__ import annotations

from typing import Any

import pytest
from livekit.plugins import cartesia, deepgram, google, openai
from voizy_agent.providers import (
    ConfigError,
    InferenceProviders,
    WorkspaceProviders,
    build_pipeline,
)
from voizy_core.domain.agent_config import AgentConfig

KEYS = {
    "deepgram_api_key": "dg-key-" + "a" * 20,
    "openai_api_key": "sk-" + "b" * 24,
    "google_api_key": "AIza" + "c" * 24,
    "cartesia_api_key": "ct-key-" + "d" * 20,
}


def cfg(llm_provider: str = "openai", llm_model: str = "gpt-4o-mini", **conn: str) -> AgentConfig:
    own = {"connection": "own"}
    return AgentConfig.model_validate(
        {
            "name": "A",
            "system_prompt": "Hi",
            "stt": {
                "provider": "deepgram",
                "model": "nova-3",
                **({"connection": conn["stt"]} if "stt" in conn else own),
            },
            "llm": {
                "provider": llm_provider,
                "model": llm_model,
                **({"connection": conn["llm"]} if "llm" in conn else own),
            },
            "tts": {
                "provider": "cartesia",
                "model": "sonic-3",
                "voice_id": "v-1",
                **({"connection": conn["tts"]} if "tts" in conn else own),
            },
        }
    )


def providers(keys: dict[str, str] | None = None) -> WorkspaceProviders:
    return WorkspaceProviders(InferenceProviders(), KEYS if keys is None else keys)


def test_own_keys_build_the_providers_own_plugins() -> None:
    parts = build_pipeline(cfg(), providers())
    assert isinstance(parts.stt, deepgram.STT)
    assert isinstance(parts.llm, openai.LLM)
    assert isinstance(parts.tts, cartesia.TTS)
    assert parts.llm.model == "gpt-4o-mini"
    assert parts.tts._opts.voice == "v-1"  # the voice id reached the plugin


def test_google_llm_uses_the_google_plugin() -> None:
    parts = build_pipeline(cfg("google", "gemini-2.5-flash"), providers())
    assert isinstance(parts.llm, google.LLM)
    # Tools need function calling, which only the v1beta API allows (a real Google key was rejected
    # with "Function calling is not enabled for api version v1" before this was set).
    http_options: Any = parts.llm._opts.http_options
    assert http_options.api_version == "v1beta"


def test_missing_key_fails_loudly_instead_of_falling_back() -> None:
    without_openai = {k: v for k, v in KEYS.items() if k != "openai_api_key"}
    with pytest.raises(ConfigError, match="openai_api_key"):
        build_pipeline(cfg(), providers(without_openai))


def test_unsupported_direct_provider_is_refused() -> None:
    bad = AgentConfig.model_validate(
        {
            "name": "A",
            "system_prompt": "Hi",
            "stt": {"provider": "assemblyai", "model": "universal-streaming", "connection": "own"},
            "llm": {"provider": "openai", "model": "gpt-4o-mini"},
            "tts": {"provider": "cartesia", "model": "sonic-3", "voice_id": "v"},
        }
    )
    with pytest.raises(ConfigError, match="no direct connection"):
        build_pipeline(bad, providers())


def test_default_connection_still_goes_through_livekit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVEKIT_URL", "wss://x.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", "APIkey1234")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "s" * 32)
    mixed = cfg(stt="livekit", llm="livekit", tts="livekit")
    parts: Any = build_pipeline(mixed, providers({}))
    assert type(parts.stt).__module__.startswith("livekit.agents.inference")
    assert type(parts.llm).__module__.startswith("livekit.agents.inference")


def test_mixed_connections_choose_per_component(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVEKIT_URL", "wss://x.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", "APIkey1234")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "s" * 32)
    parts: Any = build_pipeline(cfg(llm="livekit"), providers())
    assert isinstance(parts.stt, deepgram.STT)
    assert type(parts.llm).__module__.startswith("livekit.agents.inference")
