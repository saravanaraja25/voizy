"""Ending a call: the agent hanging up, the time limit, and the caller going silent.

Deleting the LiveKit room disconnects every participant, which also hangs up a phone leg. That is
the only reliable way to drop the line from the agent's side.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from livekit.agents import RunContext, function_tool, llm

log = logging.getLogger("livekit.agents.voizy")

END_CALL_DESCRIPTION = (
    "Hang up the phone call. Use it only after you have said goodbye and the caller has nothing "
    "more to ask. Never use it while the caller is still talking or asking something."
)


class CallEnder:
    """Hangs up once, whoever asks first, and remembers why (for the call record)."""

    def __init__(self, delete_room: Callable[[], Awaitable[object]]) -> None:
        self._delete_room = delete_room
        self.reason: str | None = None

    async def hang_up(self, reason: str) -> None:
        if self.reason is not None:
            return
        self.reason = reason
        try:
            await self._delete_room()
        except Exception:  # noqa: BLE001 - the caller may already be gone
            log.warning("could not delete the room while hanging up (%s)", reason)


def end_call_tool(ender: CallEnder) -> llm.Tool:
    @function_tool(name="end_call", description=END_CALL_DESCRIPTION)
    async def end_call(context: RunContext[None]) -> None:
        await context.wait_for_playout()  # let the goodbye finish before the line drops
        await ender.hang_up("agent ended the call")

    return end_call


VOICEMAIL_DESCRIPTION = (
    "Use this the moment you realise you reached a voicemail box or answering machine (a recorded "
    "greeting, 'leave a message after the tone', a beep). Say nothing before using it."
)
OPT_OUT_DESCRIPTION = (
    "Use this when the person asks not to be called again (for example 'stop calling me', 'take me "
    "off your list'). It removes their number from all future calls. Afterwards apologise "
    "briefly, say goodbye and use end_call."
)


def voicemail_tool(ender: CallEnder) -> llm.Tool:
    @function_tool(name="voicemail_detected", description=VOICEMAIL_DESCRIPTION)
    async def voicemail_detected() -> None:
        await ender.hang_up("voicemail")

    return voicemail_detected


def opt_out_tool(do_opt_out: Callable[[], Awaitable[None]]) -> llm.Tool:
    @function_tool(name="opt_out_of_calls", description=OPT_OUT_DESCRIPTION)
    async def opt_out_of_calls() -> str:
        try:
            await do_opt_out()
        except Exception:  # noqa: BLE001 - say so honestly rather than promise what failed
            log.warning("could not record an opt-out")
            return "The request could not be saved. Tell them you will pass it on to the team."
        return "Done. Their number has been removed from future calls."

    return opt_out_of_calls


async def enforce_time_limit(ender: CallEnder, seconds: int) -> None:
    await asyncio.sleep(seconds)
    await ender.hang_up("time limit")


class SilenceGuard:
    """Caller silent: ask once whether they are there, then hang up if they stay silent.

    The SDK reports "away" only when the state changes, so a second silence produces no second
    event. The follow-up hang-up is therefore a timer that any caller speech cancels.
    """

    def __init__(self, ender: CallEnder, ask: Callable[[], object], wait_s: float) -> None:
        self._ender, self._ask, self._wait_s = ender, ask, wait_s
        self._pending: asyncio.Task[None] | None = None

    def on_state(self, new_state: str) -> None:
        if new_state == "speaking":
            self._cancel()
        elif new_state == "away" and self._pending is None:
            self._ask()
            self._pending = asyncio.create_task(self._hang_up_later())

    def _cancel(self) -> None:
        if self._pending is not None:
            self._pending.cancel()
            self._pending = None

    async def _hang_up_later(self) -> None:
        await asyncio.sleep(self._wait_s)
        await self._ender.hang_up("caller silent")

    def close(self) -> None:
        self._cancel()
