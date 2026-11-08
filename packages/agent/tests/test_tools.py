from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from livekit.agents import llm
from voizy_agent.http_tool import HttpToolExecutor, ToolResult
from voizy_agent.tools import (
    DEFAULT_FILLERS,
    STILL_WORKING,
    build_http_tools,
    filler_source,
    tool_names,
)
from voizy_core.domain.agent_config import AgentConfig, FillerPolicy


class FakeContext:
    """Records how the tool asked for filler speech."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    @contextlib.asynccontextmanager
    async def with_filler(self, source: Callable[[int], str], **kw: Any) -> AsyncIterator[None]:
        self.calls.append({"source": source, **kw})
        yield


class FakeExecutor(HttpToolExecutor):
    def __init__(self, result: ToolResult) -> None:
        super().__init__()
        self.result = result
        self.seen: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, tool: Any, args: Any, secrets: Any = None) -> ToolResult:
        self.seen.append((tool.name, dict(args)))
        self.secrets = secrets
        return self.result


def config(**tool_over: Any) -> AgentConfig:
    tool = {
        "kind": "http",
        "name": "check_availability",
        "description": "Look up open appointment times for a date.",
        "url": "https://clinic.example/availability",
        "method": "GET",
        "parameters_schema": {
            "type": "object",
            "properties": {"date": {"type": "string"}},
            "required": ["date"],
        },
        **tool_over,
    }
    return AgentConfig.model_validate(
        {
            "name": "A",
            "system_prompt": "Hi",
            "stt": {"provider": "deepgram", "model": "nova-3"},
            "llm": {"provider": "google", "model": "gemini-2.5-flash"},
            "tts": {"provider": "cartesia", "model": "sonic-turbo", "voice_id": "v"},
            "tools": [tool],
        }
    )


def ok(text: str = '{"slots":["09:00"]}') -> ToolResult:
    return ToolResult(True, text, 200, 0.05)


async def call(tool: llm.RawFunctionTool[..., Any], ctx: FakeContext, **args: Any) -> str:
    return str(await tool._func(args, ctx))


@pytest.mark.asyncio
async def test_tool_is_registered_with_the_configured_schema() -> None:
    (t,) = build_http_tools(config(), FakeExecutor(ok()))
    assert tool_names([t]) == ["check_availability"]
    schema = t.info.raw_schema
    assert (
        schema["description"].startswith("Look up open")
        and "date" in schema["parameters"]["properties"]
    )


@pytest.mark.asyncio
async def test_success_returns_the_text_and_passes_model_arguments_through() -> None:
    ex = FakeExecutor(ok("OPEN"))
    (t,) = build_http_tools(config(), ex)
    assert await call(t, FakeContext(), date="2026-11-10") == "OPEN"
    assert ex.seen == [("check_availability", {"date": "2026-11-10"})]


@pytest.mark.asyncio
async def test_failure_becomes_a_tool_error_with_the_configured_apology() -> None:
    bad = ToolResult(False, "the request timed out", None, 5.0)
    cfg = config(filler={"failure_phrase": "Sorry, the system is down."})
    (t,) = build_http_tools(cfg, FakeExecutor(bad))
    with pytest.raises(llm.ToolError) as err:
        await call(t, FakeContext(), date="x")
    msg = str(err.value)
    assert "timed out" in msg and "Sorry, the system is down." in msg and "Do not guess" in msg


@pytest.mark.asyncio
async def test_filler_timing_comes_from_the_policy() -> None:
    cfg = config(filler={"delay_ms": 400, "still_working_after_ms": 3000})
    (t,) = build_http_tools(cfg, FakeExecutor(ok()))
    ctx = FakeContext()
    await call(t, ctx, date="x")
    (c,) = ctx.calls
    assert c["delay"] == 0.4 and c["interval"] == 2.6 and c["max_steps"] == 3


@pytest.mark.asyncio
async def test_filler_none_never_asks_for_filler() -> None:
    (t,) = build_http_tools(config(filler={"mode": "none"}), FakeExecutor(ok()))
    ctx = FakeContext()
    await call(t, ctx, date="x")
    assert ctx.calls == []


def test_filler_source_rotates_and_switches_to_still_working() -> None:
    pick = filler_source(FillerPolicy())
    assert pick is not None
    firsts = [pick(0) for _ in range(len(DEFAULT_FILLERS) + 1)]
    assert firsts[:-1] == list(DEFAULT_FILLERS) and firsts[-1] == DEFAULT_FILLERS[0]
    assert all(a != b for a, b in zip(firsts, firsts[1:], strict=False))
    assert (
        pick(1) == STILL_WORKING[0] and pick(2) == STILL_WORKING[1] and pick(3) == STILL_WORKING[0]
    )


def test_custom_filler_uses_only_configured_phrases() -> None:
    pick = filler_source(FillerPolicy(mode="custom", phrases=["Checking now."]))
    assert pick is not None and pick(0) == "Checking now." and pick(0) == "Checking now."
    assert filler_source(FillerPolicy(mode="none")) is None
