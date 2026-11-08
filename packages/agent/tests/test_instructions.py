from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from voizy_agent.instructions import build_instructions
from voizy_core.domain.agent_config import AgentConfig

NOW = datetime(2026, 11, 8, 12, 30, tzinfo=UTC)


def make(**over: Any) -> AgentConfig:
    cfg: dict[str, Any] = {
        "name": "Ava",
        "system_prompt": "You are {{agent_name}} for {{company}}. Now: {{current_time}}.",
        "variables": [{"name": "company", "default": "Acme Dental"}],
        "stt": {"provider": "deepgram", "model": "nova-3"},
        "llm": {"provider": "google", "model": "gemini-2.5-flash"},
        "tts": {"provider": "cartesia", "model": "sonic-turbo", "voice_id": "v"},
    }
    cfg.update(over)
    return AgentConfig.model_validate(cfg)


def test_prompt_is_rendered_then_rules_follow_it() -> None:
    text = build_instructions(make(), now=NOW)
    assert text.startswith("You are Ava for Acme Dental. Now: 2026-11-08T12:30+00:00.")
    assert text.index("Rules for this phone call") > text.index("Acme Dental")


def test_no_registered_tools_is_stated_explicitly() -> None:
    assert "Your tools: none." in build_instructions(make(), now=NOW)


def test_registered_tools_are_listed_sorted() -> None:
    text = build_instructions(make(), ["send_sms", "check_schedule"], now=NOW)
    assert "Your tools: check_schedule, send_sms." in text


def test_config_declared_tools_are_not_assumed_available() -> None:
    cfg = make(
        tools=[{"kind": "http", "name": "lookup", "description": "d", "url": "https://x.example/a"}]
    )
    # Declared in the config but not registered by the runtime: must not be advertised.
    assert "lookup" not in build_instructions(cfg, now=NOW)


def test_variable_values_are_not_expanded_again() -> None:
    cfg = make(variables=[{"name": "company", "default": "{{current_time}}"}])
    assert "Acme" not in build_instructions(cfg, now=NOW)
    assert "You are Ava for {{current_time}}." in build_instructions(cfg, now=NOW)


def test_forbids_unbacked_promises() -> None:
    text = build_instructions(make(), now=NOW)
    assert "Never say you will check" in text and "Never leave the caller waiting" in text


def test_rules_ask_for_a_short_spoken_lead_in_before_tool_calls() -> None:
    text = build_instructions(make(), ["lookup"], now=NOW)
    assert "very short lead-in of at most four words" in text
    assert "do not repeat the lead-in afterwards" in text


def test_rules_forbid_inventing_facts() -> None:
    text = build_instructions(make(), now=NOW)
    assert "Only state facts that appear in your instructions or in a tool result" in text
    assert "Never guess or invent details" in text
