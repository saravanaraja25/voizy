import pytest
from pydantic import ValidationError
from voizy_core.domain.agent_config import AgentConfig, render_prompt


def base(**over: object) -> dict[str, object]:
    cfg: dict[str, object] = {
        "name": "Receptionist",
        "system_prompt": "You are {{agent_name}} for {{company}}.",
        "variables": [{"name": "company", "required": True}],
        "stt": {"provider": "deepgram", "model": "nova-3"},
        "llm": {"provider": "openai", "model": "gpt-4o-mini"},
        "tts": {"provider": "cartesia", "model": "sonic", "voice_id": "v1"},
    }
    cfg.update(over)
    return cfg


def test_minimal_config_is_valid_and_defaults_to_english() -> None:
    cfg = AgentConfig.model_validate(base())
    assert cfg.default_language == "en"
    assert [lang.code for lang in cfg.languages] == ["en"]


def test_unknown_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentConfig.model_validate(base(surprise=1))


def test_undeclared_prompt_variable_rejected() -> None:
    with pytest.raises(ValidationError, match="undeclared variables: region"):
        AgentConfig.model_validate(base(system_prompt="Hi {{company}} {{region}}"))


def test_variable_cannot_shadow_system_variable() -> None:
    with pytest.raises(ValidationError, match="shadow"):
        AgentConfig.model_validate(base(variables=[{"name": "agent_name"}]))


def test_default_language_must_be_listed() -> None:
    with pytest.raises(ValidationError, match="default_language"):
        AgentConfig.model_validate(base(default_language="ta"))


def test_http_tool_requires_https_and_valid_name() -> None:
    tool = {"kind": "http", "name": "lookup", "description": "d", "url": "http://x.example/a"}
    with pytest.raises(ValidationError, match="https"):
        AgentConfig.model_validate(base(tools=[tool]))
    bad = {**tool, "url": "https://x.example/a", "name": "Bad Name"}
    with pytest.raises(ValidationError, match="snake_case"):
        AgentConfig.model_validate(base(tools=[bad]))


def test_duplicate_tool_names_rejected() -> None:
    t = {"kind": "http", "name": "lookup", "description": "d", "url": "https://x.example/a"}
    with pytest.raises(ValidationError, match="duplicate tool"):
        AgentConfig.model_validate(base(tools=[t, t]))


def test_recording_requires_disclosure() -> None:
    with pytest.raises(ValidationError, match="recording_disclosure"):
        AgentConfig.model_validate(base(policy={"record_calls": True}))


def test_endpointing_delays_ordered() -> None:
    turn = {"min_endpointing_delay_ms": 900, "max_endpointing_delay_ms": 500}
    with pytest.raises(ValidationError, match="max_endpointing"):
        AgentConfig.model_validate(base(turn=turn))


def test_render_prompt_does_not_rescan_substituted_values() -> None:
    out = render_prompt("Hi {{name}}", {"name": "{{secret}}", "secret": "LEAK"})
    assert out == "Hi {{secret}}"


def test_render_prompt_missing_value_is_empty() -> None:
    assert render_prompt("A{{x}}B", {}) == "AB"
