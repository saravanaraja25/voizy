"""Turn an AgentConfig into concrete STT / LLM / TTS components.

Model ids are checked against LiveKit Inference's catalogs up front, so a typo fails at publish
or call setup with a clear message instead of mid-call.
"""

from __future__ import annotations

import typing
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from livekit.agents import NOT_GIVEN, inference
from livekit.agents.types import NotGivenOr
from voizy_core.domain.agent_config import AgentConfig, ProviderChoice, VoiceChoice
from voizy_core.domain.direct import DIRECT_KEYS, components


class ConfigError(Exception):
    """The AgentConfig cannot be turned into a working pipeline."""


def model_id(choice: ProviderChoice) -> str:
    return f"{choice.provider}/{choice.model}"


def _catalog(alias: object) -> frozenset[str]:
    names: set[str] = set()
    for arg in typing.get_args(alias):
        if typing.get_origin(arg) is typing.Literal:
            names.update(typing.get_args(arg))
        elif isinstance(arg, str):
            names.add(arg)
    return frozenset(names)


STT_MODELS = _catalog(inference.STTModels)
LLM_MODELS = _catalog(inference.LLMModels)
TTS_MODELS = _catalog(inference.TTSModels)


def _check(kind: str, ident: str, catalog: frozenset[str]) -> None:
    if ident not in catalog:
        raise ConfigError(f"unsupported {kind} model {ident!r}")


class Providers(Protocol):
    def validate(self, cfg: AgentConfig) -> None:
        """Raise ConfigError for anything unusable, before any component is constructed."""
        ...

    def stt(self, choice: ProviderChoice, language: str) -> typing.Any: ...
    def llm(self, choice: ProviderChoice) -> typing.Any: ...
    def tts(self, choice: VoiceChoice, language: str) -> typing.Any: ...


class InferenceProviders:
    """Builds components backed by LiveKit Inference (one LiveKit key for all three).

    Credentials come from the workspace's stored LiveKit connection when given, otherwise from
    the environment (the SDK's default).
    """

    def __init__(self, api_key: str | None = None, api_secret: str | None = None) -> None:
        both = bool(api_key and api_secret)
        self._plain_key = api_key if both else None  # the LLM class wants str | None
        self._plain_secret = api_secret if both else None
        self._key: NotGivenOr[str] = api_key if both and api_key else NOT_GIVEN
        self._secret: NotGivenOr[str] = api_secret if both and api_secret else NOT_GIVEN

    def validate(self, cfg: AgentConfig) -> None:
        if cfg.stt is not None:
            _check("STT", model_id(cfg.stt), STT_MODELS)
        if cfg.llm is not None:
            _check("LLM", model_id(cfg.llm), LLM_MODELS)
        if cfg.tts is not None:
            _check("TTS", model_id(cfg.tts), TTS_MODELS)

    def stt(self, choice: ProviderChoice, language: str) -> inference.STT:
        _check("STT", model_id(choice), STT_MODELS)
        return inference.STT(
            model_id(choice), language=language, api_key=self._key, api_secret=self._secret
        )

    def llm(self, choice: ProviderChoice) -> inference.LLM:
        _check("LLM", model_id(choice), LLM_MODELS)
        return inference.LLM(
            model_id(choice), api_key=self._plain_key, api_secret=self._plain_secret
        )

    def tts(self, choice: VoiceChoice, language: str) -> inference.TTS:
        _check("TTS", model_id(choice), TTS_MODELS)
        return inference.TTS(
            model_id(choice),
            voice=choice.voice_id,
            language=language,
            api_key=self._key,
            api_secret=self._secret,
        )


class WorkspaceProviders:
    """Chooses, per component, LiveKit Inference or the provider's own plugin with the stored key.

    Keys are the workspace's integration secrets (see direct.DIRECT_KEYS). A component set to use
    its own key never silently falls back to LiveKit: a missing key fails the call setup loudly.
    """

    def __init__(
        self, inference: InferenceProviders, keys: Mapping[str, str] | None = None
    ) -> None:
        self._inference = inference
        self._keys = dict(keys or {})

    def _key(self, kind: str, choice: ProviderChoice) -> str:
        name = DIRECT_KEYS.get((kind, choice.provider))
        if name is None:
            raise ConfigError(f"{kind} provider {choice.provider!r} has no direct connection")
        key = self._keys.get(name)
        if not key:
            raise ConfigError(f"{name} is not configured for this workspace")
        return key

    def validate(self, cfg: AgentConfig) -> None:
        for kind, choice in components(cfg):
            if choice.connection == "own":
                self._key(kind, choice)
        for kind, choice in components(cfg):
            if choice.connection != "own":
                catalog = {"stt": STT_MODELS, "llm": LLM_MODELS, "tts": TTS_MODELS}[kind]
                _check(kind.upper(), model_id(choice), catalog)

    def stt(self, choice: ProviderChoice, language: str) -> typing.Any:
        if choice.connection != "own":
            return self._inference.stt(choice, language)
        from livekit.plugins import deepgram  # noqa: PLC0415 - heavy import, only when used

        return deepgram.STT(model=choice.model, language=language, api_key=self._key("stt", choice))

    def llm(self, choice: ProviderChoice) -> typing.Any:
        if choice.connection != "own":
            return self._inference.llm(choice)
        key = self._key("llm", choice)
        if choice.provider == "openai":
            from livekit.plugins import openai  # noqa: PLC0415

            return openai.LLM(model=choice.model, api_key=key)
        from livekit.plugins import google  # noqa: PLC0415

        return google.LLM(model=choice.model, api_key=key)

    def tts(self, choice: VoiceChoice, language: str) -> typing.Any:
        if choice.connection != "own":
            return self._inference.tts(choice, language)
        from livekit.plugins import cartesia  # noqa: PLC0415

        extra: dict[str, typing.Any] = {"speed": choice.speed} if choice.speed != 1.0 else {}
        return cartesia.TTS(
            model=choice.model,
            voice=choice.voice_id,
            language=language,
            api_key=self._key("tts", choice),
            **extra,
        )


@dataclass(frozen=True)
class PipelineParts:
    stt: typing.Any
    llm: typing.Any
    tts: typing.Any


def build_pipeline(cfg: AgentConfig, providers: Providers) -> PipelineParts:
    if cfg.mode != "pipeline":
        raise ConfigError(f"mode {cfg.mode!r} is not supported by the runtime yet")
    if cfg.stt is None or cfg.llm is None or cfg.tts is None:  # AgentConfig already guarantees it
        raise ConfigError("pipeline mode requires stt, llm and tts")
    providers.validate(cfg)
    language = cfg.default_language
    return PipelineParts(
        stt=providers.stt(cfg.stt, language),
        llm=providers.llm(cfg.llm),
        tts=providers.tts(cfg.tts, language),
    )
