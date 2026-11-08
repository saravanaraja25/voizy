from voizy_agent.session_options import turn_handling
from voizy_core.domain.agent_config import TurnConfig


def test_defaults_map_to_livekit_units_and_enable_preemptive_generation() -> None:
    th = turn_handling(TurnConfig())
    assert th["endpointing"] == {"min_delay": 0.3, "max_delay": 1.5}
    assert th["interruption"] == {"enabled": True, "min_words": 1}
    assert th["preemptive_generation"] == {"enabled": True}


def test_custom_values_are_respected() -> None:
    th = turn_handling(
        TurnConfig(
            min_endpointing_delay_ms=150,
            max_endpointing_delay_ms=900,
            allow_interruptions=False,
            interruption_min_words=3,
            preemptive_generation=False,
        )
    )
    assert th["endpointing"] == {"min_delay": 0.15, "max_delay": 0.9}
    assert th["interruption"] == {"enabled": False, "min_words": 3}
    assert th["preemptive_generation"] == {"enabled": False}
