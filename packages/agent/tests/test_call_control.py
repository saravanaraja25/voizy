from __future__ import annotations

import asyncio

from voizy_agent.call_control import CallEnder, SilenceGuard, enforce_time_limit
from voizy_agent.instructions import build_instructions
from voizy_core.domain.agent_config import AgentConfig


class Room:
    def __init__(self, fail: bool = False) -> None:
        self.deleted, self.fail = 0, fail

    async def delete(self) -> None:
        self.deleted += 1
        if self.fail:
            raise RuntimeError("room already gone")


async def test_hang_up_deletes_the_room_once_and_keeps_the_first_reason() -> None:
    room = Room()
    ender = CallEnder(room.delete)
    await ender.hang_up("agent ended the call")
    await ender.hang_up("time limit")
    assert room.deleted == 1 and ender.reason == "agent ended the call"


async def test_hang_up_survives_a_room_that_is_already_gone() -> None:
    ender = CallEnder(Room(fail=True).delete)
    await ender.hang_up("caller silent")
    assert ender.reason == "caller silent"


async def test_time_limit_hangs_up() -> None:
    room = Room()
    ender = CallEnder(room.delete)
    await asyncio.wait_for(enforce_time_limit(ender, 0), 1)
    assert ender.reason == "time limit" and room.deleted == 1


async def test_silence_asks_once_then_hangs_up() -> None:
    room, asked = Room(), []
    ender = CallEnder(room.delete)
    guard = SilenceGuard(ender, lambda: asked.append(1), 0.05)
    guard.on_state("away")
    guard.on_state("away")  # a repeat must not ask twice
    await asyncio.sleep(0.15)
    assert asked == [1] and ender.reason == "caller silent" and room.deleted == 1


async def test_caller_speech_cancels_the_pending_hang_up() -> None:
    room, asked = Room(), []
    ender = CallEnder(room.delete)
    guard = SilenceGuard(ender, lambda: asked.append(1), 0.05)
    guard.on_state("away")
    guard.on_state("speaking")
    await asyncio.sleep(0.15)
    assert ender.reason is None and room.deleted == 0
    guard.on_state("away")  # silent again later: asks again
    guard.close()
    assert asked == [1, 1]


def test_instructions_tell_the_model_when_to_hang_up() -> None:
    cfg = AgentConfig.model_validate(
        {
            "name": "A",
            "system_prompt": "Hi",
            "stt": {"provider": "deepgram", "model": "nova-3"},
            "llm": {"provider": "google", "model": "gemini-2.5-flash"},
            "tts": {"provider": "cartesia", "model": "sonic-3", "voice_id": "v"},
        }
    )
    text = build_instructions(cfg, ["end_call"])
    assert "end_call" in text and "Never hang up while the caller" in text
