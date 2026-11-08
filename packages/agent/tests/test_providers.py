from __future__ import annotations

from typing import Any

import pytest
from voizy_agent.providers import (
    LLM_MODELS,
    STT_MODELS,
    TTS_MODELS,
    ConfigError,
    InferenceProviders,
    build_pipeline,
)
from voizy_core.domain.agent_config import AgentConfig, ProviderChoice, VoiceChoice


def make_config(**over: Any) -> AgentConfig:
    cfg: dict[str, Any] = {
        "name": "A",
        "system_prompt": "Hi",
        "stt": {"provider": "deepgram", "model": "nova-3"},
        "llm": {"provider": "google", "model": "gemini-2.5-flash"},
        "tts": {"provider": "cartesia", "model": "sonic-3", "voice_id": "voice-1"},
    }
    cfg.update(over)
    return AgentConfig.model_validate(cfg)


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def validate(self, cfg: AgentConfig) -> None:
        self.calls.append(("validate", ()))

    def stt(self, choice: ProviderChoice, language: str) -> str:
        self.calls.append(("stt", (choice.model, language)))
        return "STT"

    def llm(self, choice: ProviderChoice) -> str:
        self.calls.append(("llm", (choice.model,)))
        return "LLM"

    def tts(self, choice: VoiceChoice, language: str) -> str:
        self.calls.append(("tts", (choice.voice_id, language)))
        return "TTS"


def test_build_pipeline_wires_each_stage_from_config() -> None:
    rec = Recorder()
    parts = build_pipeline(make_config(), rec)
    assert (parts.stt, parts.llm, parts.tts) == ("STT", "LLM", "TTS")
    assert rec.calls == [
        ("validate", ()),
        ("stt", ("nova-3", "en")),
        ("llm", ("gemini-2.5-flash",)),
        ("tts", ("voice-1", "en")),
    ]


def test_realtime_mode_is_rejected_clearly_until_implemented() -> None:
    cfg = make_config(
        mode="realtime",
        stt=None,
        llm=None,
        tts=None,
        realtime={"provider": "google", "model": "gemini-live"},
    )
    with pytest.raises(ConfigError, match="not supported by the runtime yet"):
        build_pipeline(cfg, Recorder())


def test_catalogs_contain_the_models_we_default_to() -> None:
    assert "deepgram/nova-3" in STT_MODELS
    assert "google/gemini-2.5-flash" in LLM_MODELS
    assert "cartesia/sonic-3" in TTS_MODELS


@pytest.mark.parametrize(
    ("kind", "choice"),
    [
        ("stt", {"provider": "deepgram", "model": "nova-99"}),
        ("llm", {"provider": "google", "model": "gemini-9000"}),
    ],
)
def test_unknown_models_fail_before_any_component_is_built(
    kind: str, choice: dict[str, str]
) -> None:
    # No LiveKit credentials are set: if construction ran first, it would fail differently.
    cfg = make_config(**{kind: choice})
    with pytest.raises(ConfigError, match="unsupported"):
        build_pipeline(cfg, InferenceProviders())


def test_unknown_tts_model_rejected() -> None:
    cfg = make_config(
        tts={"provider": "cartesia", "model": "sonic-0", "voice_id": "v"},
    )
    with pytest.raises(ConfigError, match="unsupported TTS"):
        build_pipeline(cfg, InferenceProviders())


def test_inference_providers_construct_real_components_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LIVEKIT_URL", "wss://example.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", "key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "s" * 32)
    parts = build_pipeline(make_config(), InferenceProviders())
    assert type(parts.stt).__name__ == "STT"
    assert type(parts.llm).__name__ == "LLM"
    assert type(parts.tts).__name__ == "TTS"


def test_explicit_workspace_credentials_are_used_without_any_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        monkeypatch.delenv(var, raising=False)
    # With no environment, the SDK refuses to build a component unless it is handed credentials.
    with pytest.raises(ValueError, match="api_key"):
        build_pipeline(make_config(), InferenceProviders())
    parts = build_pipeline(make_config(), InferenceProviders("APIkey123", "s" * 40))
    assert type(parts.stt).__name__ == "STT" and type(parts.tts).__name__ == "TTS"
    assert type(parts.llm).__name__ == "LLM"
