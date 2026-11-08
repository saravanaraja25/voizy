"""Build the agent's system instructions: the builder's prompt plus non-negotiable call rules.

The rules come last so they outweigh anything earlier, and they list only the tools the runtime
has actually registered, so the model cannot promise an action it has no means to perform.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from voizy_core.domain.agent_config import SYSTEM_VARIABLES, AgentConfig, render_prompt

_RULES = """\
## Rules for this phone call (always apply)
- You are speaking aloud on a phone call. Use short, natural spoken sentences. Never use lists, \
markdown, emoji or read out symbols.
- You can only do what your tools allow. Your tools: {tools}.
- Only state facts that appear in your instructions or in a tool result: hours, prices, \
locations, policies, names. If you do not have a fact, say you do not have that information and \
offer what you can do. Never guess or invent details.
- Never say you will check, look up, book, send, transfer or confirm something unless you have a \
tool that does exactly that. If you cannot, say so plainly in one sentence and offer what you \
can do instead, such as answering from the information above or taking a message for a callback.
- Never leave the caller waiting. If you say you are doing something, do it in the same turn.
- When you need a tool, first say a very short lead-in of at most four words, such as "One sec." \
or "Let me check." Say it in the same reply and then call the tool straight away. Never explain \
what you are about to look up, and do not repeat the lead-in afterwards."""


def prompt_values(cfg: AgentConfig, *, now: datetime | None = None) -> dict[str, str]:
    values = {v.name: v.default or "" for v in cfg.variables}
    values.update({k: "" for k in SYSTEM_VARIABLES})
    values["agent_name"] = cfg.name
    values["current_time"] = (now or datetime.now(UTC)).isoformat(timespec="minutes")
    return values


def build_instructions(
    cfg: AgentConfig, tool_names: Sequence[str] = (), *, now: datetime | None = None
) -> str:
    body = render_prompt(cfg.system_prompt, prompt_values(cfg, now=now)).rstrip()
    tools = ", ".join(sorted(tool_names)) if tool_names else "none"
    return f"{body}\n\n{_RULES.format(tools=tools)}"
