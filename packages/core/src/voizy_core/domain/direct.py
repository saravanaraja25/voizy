"""Which components can talk to their provider directly with the workspace's own key."""

from __future__ import annotations

from voizy_core.domain.agent_config import AgentConfig, ProviderChoice
from voizy_core.domain.integrations import BY_ID

# (component, provider) -> the integration field holding the key
DIRECT_KEYS: dict[tuple[str, str], str] = {
    ("stt", "deepgram"): "deepgram_api_key",
    ("llm", "openai"): "openai_api_key",
    ("llm", "google"): "google_api_key",
    ("tts", "cartesia"): "cartesia_api_key",
}
ALL_DIRECT_KEY_NAMES: tuple[str, ...] = tuple(dict.fromkeys(DIRECT_KEYS.values()))


def components(cfg: AgentConfig) -> list[tuple[str, ProviderChoice]]:
    out: list[tuple[str, ProviderChoice]] = []
    for kind, choice in (("stt", cfg.stt), ("llm", cfg.llm), ("tts", cfg.tts)):
        if choice is not None:
            out.append((kind, choice))
    for lang in cfg.languages:
        if lang.stt is not None:
            out.append(("stt", lang.stt))
        if lang.tts is not None:
            out.append(("tts", lang.tts))
    return out


def _integration_label(key_name: str) -> str:
    for integration in BY_ID.values():
        if any(f.name == key_name for f in integration.fields):
            return integration.label
    return key_name


def direct_problems(cfg: AgentConfig, configured: set[str]) -> list[str]:
    """Human-readable reasons the config's 'own key' choices cannot work; empty if fine."""
    problems: list[str] = []
    for kind, choice in components(cfg):
        if choice.connection != "own":
            continue
        key = DIRECT_KEYS.get((kind, choice.provider))
        if key is None:
            problems.append(
                f"{kind.upper()}: {choice.provider} can't be used with your own key yet. "
                "Choose LiveKit instead."
            )
        elif key not in configured:
            problems.append(
                f"{kind.upper()}: add your {_integration_label(key)} key in Settings first."
            )
    return list(dict.fromkeys(problems))
