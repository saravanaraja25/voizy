from voizy_agent.session_options import get_vad, turn_handling, vad_params
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


def test_vad_params_convert_units() -> None:
    assert vad_params(TurnConfig()) == {"min_silence_duration": 0.55, "activation_threshold": 0.5}
    p = vad_params(TurnConfig(vad_min_silence_ms=300, vad_threshold=0.6))
    assert p == {"min_silence_duration": 0.3, "activation_threshold": 0.6}


def test_vad_is_loaded_once_per_distinct_setting() -> None:
    loads: list[dict[str, float]] = []

    def load(**kw: float) -> object:
        loads.append(kw)
        return object()

    cache: dict[tuple[float, float], object] = {}
    a = get_vad(cache, TurnConfig(), load)
    assert get_vad(cache, TurnConfig(), load) is a and len(loads) == 1
    b = get_vad(cache, TurnConfig(vad_min_silence_ms=300), load)
    assert b is not a and len(loads) == 2 and loads[1]["min_silence_duration"] == 0.3
