"""The generic voice worker: one entrypoint that becomes any agent described by an AgentConfig."""

from __future__ import annotations

import logging
import os

from livekit import agents
from livekit.agents import (
    Agent,
    AgentSession,
    ConversationItemAddedEvent,
    JobContext,
    inference,
    llm,
)
from livekit.plugins import silero
from psycopg_pool import AsyncConnectionPool
from voizy_core.db.pool import open_pool
from voizy_core.domain.agent_config import AgentConfig
from voizy_core.security.ssrf import STRICT, SsrfPolicy

from voizy_agent.config_source import (
    ConfigNotFoundError,
    load_dev_config,
    load_published_config,
    parse_job_metadata,
)
from voizy_agent.http_tool import HttpToolExecutor
from voizy_agent.instructions import build_instructions
from voizy_agent.latency import LatencyRecorder
from voizy_agent.providers import InferenceProviders, build_pipeline
from voizy_agent.session_options import turn_handling
from voizy_agent.tools import build_http_tools, tool_names

log = logging.getLogger("livekit.agents.voizy")  # inherits LiveKit's log config


def _tool_policy() -> SsrfPolicy:
    """Strict unless development mode is explicitly enabled; even then only loopback opens up."""
    if os.environ.get("VOIZY_DEV_ALLOW_LOCAL_TOOLS") == "1":
        log.warning("DEV MODE: tools may call loopback addresses (VOIZY_DEV_ALLOW_LOCAL_TOOLS=1)")
        return SsrfPolicy(allow_loopback=True)
    return STRICT


server = agents.AgentServer()
_pool: AsyncConnectionPool | None = None


def prewarm(proc: agents.JobProcess) -> None:
    """Load heavy models once per worker process, before any call arrives."""
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


async def _config_for(ctx: JobContext) -> AgentConfig:
    global _pool  # noqa: PLW0603 - one pool per worker process
    ids = parse_job_metadata(ctx.job.metadata)
    if ids is not None:
        if _pool is None:
            _pool = await open_pool(os.environ["VOIZY_DATABASE_URL"])
        return await load_published_config(_pool, *ids)
    dev = os.environ.get("VOIZY_DEV_AGENT_CONFIG")  # local development / playground only
    if dev:
        return load_dev_config(dev)
    raise ConfigNotFoundError("no dispatch metadata and VOIZY_DEV_AGENT_CONFIG is not set")


@server.rtc_session(agent_name=os.environ.get("VOIZY_AGENT_NAME", ""))
async def entrypoint(ctx: JobContext) -> None:
    cfg = await _config_for(ctx)
    tools = build_http_tools(cfg, HttpToolExecutor(_tool_policy()))
    agent_tools: list[llm.Tool | llm.Toolset] = [*tools]
    parts = build_pipeline(cfg, InferenceProviders())
    recorder = LatencyRecorder()

    handling = turn_handling(cfg.turn)
    handling["turn_detection"] = inference.TurnDetector()
    session: AgentSession[None] = AgentSession(
        stt=parts.stt,
        llm=parts.llm,
        tts=parts.tts,
        vad=ctx.proc.userdata["vad"],
        turn_handling=handling,  # type: ignore[arg-type]
    )

    @session.on("conversation_item_added")
    def _on_item(ev: ConversationItemAddedEvent) -> None:
        item = ev.item
        if item.type == "message" and item.role in ("user", "assistant"):
            before = len(recorder.turns())
            recorder.ingest_message(item.role, item.metrics)
            if len(recorder.turns()) > before:
                t = recorder.turns()[-1]
                log.info("turn latency: %s", {k: round(v * 1000) for k, v in vars(t).items() if v})

    async def _log_summary() -> None:
        log.info("latency summary (ms): %s", recorder.summary())

    ctx.add_shutdown_callback(_log_summary)

    await session.start(
        agent=Agent(instructions=build_instructions(cfg, tool_names(tools)), tools=agent_tools),
        room=ctx.room,
    )
    greeting = next((lang.greeting for lang in cfg.languages if lang.greeting), None)
    if greeting:
        await session.say(greeting)
    else:
        await session.generate_reply(instructions="Greet the caller briefly and ask how to help.")
