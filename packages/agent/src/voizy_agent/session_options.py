"""Map AgentConfig settings to LiveKit AgentSession options."""

from __future__ import annotations

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
