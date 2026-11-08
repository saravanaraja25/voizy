"""Turn the HTTP tools in an AgentConfig into LiveKit tools the model can call.

While a tool runs, the SDK's with_filler speaks a short holding phrase once the session has been
idle for the configured delay, so a quick lookup stays silent and a slow one never leaves dead air.
Failures reach the model as a ToolError carrying the configured apology, never as raw exceptions.
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Callable, Sequence
from typing import Any

from livekit.agents import RunContext, llm
from voizy_core.domain.agent_config import AgentConfig, FillerPolicy, HttpTool

from voizy_agent.http_tool import HttpToolExecutor, SecretResolver

RawTool = llm.RawFunctionTool[..., Any]

log = logging.getLogger("livekit.agents.voizy")

DEFAULT_FILLERS: tuple[str, ...] = (
    "One moment.",
    "Let me check that for you.",
    "Just a second.",
    "Sure, one moment.",
)
STILL_WORKING: tuple[str, ...] = (
    "Still looking, thanks for waiting.",
    "Sorry, this is taking a moment.",
)


def filler_source(policy: FillerPolicy) -> Callable[[int], str] | None:
    """Return a step -> phrase callable, or None when this tool should stay silent."""
    if policy.mode == "none":
        return None
    first = tuple(policy.phrases) if policy.mode == "custom" else DEFAULT_FILLERS
    state = {"last": -1}

    def pick(step: int) -> str:
        if step >= 1:
            return STILL_WORKING[(step - 1) % len(STILL_WORKING)]
        # Rotate through the phrases so consecutive calls don't repeat the same words.
        state["last"] = (state["last"] + 1) % len(first)
        return first[state["last"]]

    return pick


def _filler_timing(policy: FillerPolicy) -> tuple[float, float]:
    delay = policy.delay_ms / 1000
    interval = max(1.0, (policy.still_working_after_ms - policy.delay_ms) / 1000)
    return delay, interval


def build_http_tools(
    cfg: AgentConfig, executor: HttpToolExecutor, secrets: SecretResolver | None = None
) -> list[RawTool]:
    return [_build_one(tool, executor, secrets) for tool in cfg.tools if isinstance(tool, HttpTool)]


def _build_one(
    tool: HttpTool, executor: HttpToolExecutor, secrets: SecretResolver | None
) -> RawTool:
    source = filler_source(tool.filler)
    delay, interval = _filler_timing(tool.filler)

    async def handler(raw_arguments: dict[str, Any], context: RunContext[Any]) -> str:
        filler = (
            context.with_filler(source, delay=delay, interval=interval, max_steps=3)
            if source
            else contextlib.nullcontext()
        )
        log.info("trace tool start %s @%d", tool.name, time.monotonic() * 1000)
        async with filler:
            result = await executor.execute(tool, raw_arguments, secrets)
        log.info(
            "tool call",
            extra={
                "tool": tool.name,
                "ok": result.ok,
                "status": result.status,
                "ms": round(result.duration_s * 1000),
            },
        )
        if not result.ok:
            raise llm.ToolError(
                f"The {tool.name} request failed: {result.text}. "
                f"Do not guess. Tell the caller: {tool.filler.failure_phrase}"
            )
        return result.text

    return llm.function_tool(
        handler,
        raw_schema={
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters_schema,
        },
    )


def tool_names(tools: Sequence[RawTool]) -> list[str]:
    return [t.info.name for t in tools]
