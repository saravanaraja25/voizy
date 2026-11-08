"""Drift guard: every model offered in the dashboard must exist in the live SDK catalog."""

from voizy_agent.providers import LLM_MODELS, STT_MODELS, TTS_MODELS
from voizy_core.domain import catalog


def test_every_offered_model_is_supported_by_the_runtime() -> None:
    for options, supported in (
        (catalog.STT, STT_MODELS),
        (catalog.LLM, LLM_MODELS),
        (catalog.TTS, TTS_MODELS),
    ):
        missing = [o.id for o in options if o.id not in supported]
        assert not missing, f"not supported by the runtime: {missing}"
