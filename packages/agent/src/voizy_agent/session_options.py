"""Map AgentConfig settings to LiveKit AgentSession options."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
from typing import Any

from voizy_core.domain.agent_config import TurnConfig


def turn_handling(turn: TurnConfig) -> dict[str, Any]:
    return {
        "endpointing": {
            "min_delay": turn.min_endpointing_delay_ms / 1000,
            "max_delay": turn.max_endpointing_delay_ms / 1000,
        },
        "interruption": {
            "enabled": turn.allow_interruptions,
            "min_words": turn.interruption_min_words,
        },
        "preemptive_generation": {"enabled": turn.preemptive_generation},
    }


VadKey = tuple[float, float]


def vad_params(turn: TurnConfig) -> dict[str, float]:
    return {
        "min_silence_duration": turn.vad_min_silence_ms / 1000,
        "activation_threshold": turn.vad_threshold,
    }


def get_vad(cache: MutableMapping[VadKey, Any], turn: TurnConfig, load: Callable[..., Any]) -> Any:
    """Load a VAD once per distinct (silence, threshold) pair in this worker process."""
    params = vad_params(turn)
    key = (params["min_silence_duration"], params["activation_threshold"])
    if key not in cache:
        cache[key] = load(**params)
    return cache[key]
