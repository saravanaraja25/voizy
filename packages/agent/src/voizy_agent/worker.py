"""The generic voice worker: one entrypoint that becomes any agent described by an AgentConfig."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time

from livekit import agents, rtc
from livekit.agents import (
    Agent,
    AgentSession,
    AgentStateChangedEvent,
    ConversationItemAddedEvent,
    FunctionToolsExecutedEvent,
    JobContext,
    UserStateChangedEvent,
    inference,
    llm,
)
from livekit.plugins import silero
from psycopg_pool import AsyncConnectionPool
from voizy_core.db.pool import open_pool
from voizy_core.domain.agent_config import AgentConfig, TurnConfig
from voizy_core.domain.dispatch import AGENT_WORKER_NAME, DispatchTarget, parse_dispatch
from voizy_core.security.ssrf import STRICT, SsrfPolicy

from voizy_agent.call_recorder import CallRecorder
from voizy_agent.config_source import (
    ConfigNotFoundError,
    load_config_with_version,
    load_dev_config,
)
from voizy_agent.credentials import (
    DbSecretResolver,
    LiveKitCredentials,
    load_livekit,
    secret_box_from_env,
)
from voizy_agent.http_tool import HttpToolExecutor
from voizy_agent.instructions import build_instructions
from voizy_agent.latency import LatencyRecorder
from voizy_agent.providers import InferenceProviders, build_pipeline
from voizy_agent.session_options import get_vad, turn_handling
from voizy_agent.tools import build_http_tools, tool_names

LOG_TRANSCRIPTS = os.environ.get("VOIZY_LOG_TRANSCRIPTS") == "1"
TRACE = os.environ.get("VOIZY_TRACE") == "1"  # state-change timeline for latency debugging
log = logging.getLogger("livekit.agents.voizy")  # inherits LiveKit's log config


def _tool_policy() -> SsrfPolicy:
    """Strict unless development mode is explicitly enabled; even then only loopback opens up."""
    if os.environ.get("VOIZY_DEV_ALLOW_LOCAL_TOOLS") == "1":
        log.warning("DEV MODE: tools may call loopback addresses (VOIZY_DEV_ALLOW_LOCAL_TOOLS=1)")
        return SsrfPolicy(allow_loopback=True)
    return STRICT


server = agents.AgentServer()
_pool: AsyncConnectionPool | None = None


_background: set[asyncio.Task[None]] = set()  # keep references so tasks are not collected early


async def _publish_latency(room: rtc.Room, ms: dict[str, int]) -> None:
    """Send a turn's timings (numbers only, no personal data) to the connected client."""
    try:
        await room.local_participant.publish_data(
            json.dumps({"type": "turn_latency", "ms": ms}), reliable=True, topic="voizy.latency"
        )
    except Exception:  # noqa: BLE001 - telemetry must never break a call
        log.warning("could not publish latency data")


def prewarm(proc: agents.JobProcess) -> None:
    """Load heavy models once per worker process, before any call arrives."""
    proc.userdata["vad_cache"] = {}
    get_vad(proc.userdata["vad_cache"], TurnConfig(), silero.VAD.load)  # default, ready at call 1


server.setup_fnc = prewarm


async def _pool_for() -> AsyncConnectionPool:
    global _pool  # noqa: PLW0603 - one pool per worker process
    if _pool is None:
        _pool = await open_pool(os.environ["VOIZY_DATABASE_URL"])
    return _pool


async def _config_for(ctx: JobContext) -> tuple[AgentConfig, DispatchTarget | None, int]:
    """The agent's config, which agent it is, and the version used (no target for a dev file)."""
    target = parse_dispatch(ctx.job.metadata)
    if target is not None:
        cfg, version = await load_config_with_version(await _pool_for(), target)
        return cfg, target, version
    dev = os.environ.get("VOIZY_DEV_AGENT_CONFIG")  # local development / playground only
    if dev:
        return load_dev_config(dev), None, 0
    raise ConfigNotFoundError("no dispatch metadata and VOIZY_DEV_AGENT_CONFIG is not set")


@server.rtc_session(agent_name=os.environ.get("VOIZY_AGENT_NAME", AGENT_WORKER_NAME))
async def entrypoint(ctx: JobContext) -> None:
    cfg, target, version = await _config_for(ctx)
    workspace_id = target.workspace_id if target else None
    resolver: DbSecretResolver | None = None
    livekit: LiveKitCredentials | None = None
    box = secret_box_from_env()
    if workspace_id is not None and box is not None:
        pool = await _pool_for()
        resolver = DbSecretResolver(pool, box, workspace_id)
        livekit = await load_livekit(pool, box, workspace_id)
    tools = build_http_tools(cfg, HttpToolExecutor(_tool_policy()), resolver)
    agent_tools: list[llm.Tool | llm.Toolset] = [*tools]
    providers = (
        InferenceProviders(livekit.api_key, livekit.api_secret) if livekit else InferenceProviders()
    )
    parts = build_pipeline(cfg, providers)
    recorder = LatencyRecorder()
    history: CallRecorder | None = None
    if target is not None:
        history = CallRecorder(
            await _pool_for(),
            target.workspace_id,
            agent_id=target.agent_id,
            version=version,
            room=ctx.room.name,
            policy=cfg.policy,
        )
        history.start()

    # Loading a model is blocking work; keep it off the event loop that carries call audio.
    vad = await asyncio.to_thread(
        get_vad, ctx.proc.userdata["vad_cache"], cfg.turn, silero.VAD.load
    )
    handling = turn_handling(cfg.turn)
    handling["turn_detection"] = inference.TurnDetector()
    session: AgentSession[None] = AgentSession(
        stt=parts.stt,
        llm=parts.llm,
        tts=parts.tts,
        vad=vad,
        turn_handling=handling,  # type: ignore[arg-type]
    )

    @session.on("conversation_item_added")
    def _on_item(ev: ConversationItemAddedEvent) -> None:
        item = ev.item
        if item.type == "message" and item.role in ("user", "assistant"):
            if LOG_TRANSCRIPTS:  # off by default: transcripts are personal data
                log.info("transcript %s: %s", item.role, item.text_content)
            before = len(recorder.turns())
            recorder.ingest_message(item.role, item.metrics)
            ms: dict[str, int] | None = None
            if len(recorder.turns()) > before:
                t = recorder.turns()[-1]
                ms = {k.removesuffix("_s"): round(v * 1000) for k, v in vars(t).items() if v}
                log.info("turn latency: %s", ms)
            if history is not None:
                history.turn(
                    "user" if item.role == "user" else "agent",
                    item.text_content or "",
                    latency=ms,
                )
            if ms is not None:
                task = asyncio.create_task(_publish_latency(ctx.room, ms))
                _background.add(task)
                task.add_done_callback(_background.discard)

    if TRACE:

        @session.on("agent_state_changed")
        def _on_state(ev: AgentStateChangedEvent) -> None:
            log.info(
                "trace agent %s -> %s @%d", ev.old_state, ev.new_state, time.monotonic() * 1000
            )

        @session.on("user_state_changed")
        def _on_user_state(ev: UserStateChangedEvent) -> None:
            log.info("trace user %s -> %s @%d", ev.old_state, ev.new_state, time.monotonic() * 1000)

        @session.on("function_tools_executed")
        def _on_tools(ev: FunctionToolsExecutedEvent) -> None:
            log.info("trace tools executed @%d", time.monotonic() * 1000)

    if history is not None:
        recording = history

        @session.on("function_tools_executed")
        def _record_tools(ev: FunctionToolsExecutedEvent) -> None:
            for (
                call,
                out,
            ) in ev.zipped():  # names and outcome only: arguments and results are not kept
                recording.turn(
                    "tool",
                    tool_name=call.name,
                    tool_ok=not out.is_error,
                    tool_ms=max(0, round((out.created_at - call.created_at) * 1000)),
                )

    async def _log_summary() -> None:
        log.info("latency summary (ms): %s", recorder.summary())

    async def _close_history() -> None:
        if history is not None:
            await history.close(reason="ended")  # idempotent: safe from both paths below

    if history is not None:

        @session.on("close")
        def _on_close(_: object) -> None:
            # Close the record when the conversation ends, not when the job process finally exits
            # (that can lag by many seconds, leaving the call "in progress" in the dashboard).
            task = asyncio.create_task(_close_history())
            _background.add(task)
            task.add_done_callback(_background.discard)

    ctx.add_shutdown_callback(_log_summary)
    ctx.add_shutdown_callback(_close_history)

    await session.start(
        agent=Agent(instructions=build_instructions(cfg, tool_names(tools)), tools=agent_tools),
        room=ctx.room,
    )
    greeting = next((lang.greeting for lang in cfg.languages if lang.greeting), None)
    if greeting:
        await session.say(greeting)
    else:
        await session.generate_reply(instructions="Greet the caller briefly and ask how to help.")
