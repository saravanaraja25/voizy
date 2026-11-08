"""Per-turn latency accounting from LiveKit's per-message metrics.

LiveKit attaches a metrics report to each conversation message: the user message carries
transcription and end-of-turn delays, the assistant message carries LLM time-to-first-token, TTS
time-to-first-byte and an end-to-end figure (user stopped speaking -> agent began responding). We
pair each assistant message with the user message before it. Tool time is added separately.
Excludes network delivery to the client, so it is a floor on what the caller perceives.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

STAGES = ("transcription_delay", "end_of_turn_delay", "llm_ttft", "tool_time", "tts_ttfb", "e2e")


@dataclass
class TurnLatency:
    transcription_delay_s: float | None = None
    end_of_turn_delay_s: float | None = None
    llm_ttft_s: float | None = None
    tts_ttfb_s: float | None = None
    e2e_s: float | None = None
    tool_time_s: float = 0.0


def _percentile(sorted_ms: list[float], q: float) -> float:
    """Nearest-rank percentile; deterministic and fine for small samples."""
    rank = max(1, math.ceil(q * len(sorted_ms)))
    return sorted_ms[rank - 1]


def _num(report: Mapping[str, Any], key: str) -> float | None:
    value = report.get(key)
    return float(value) if isinstance(value, int | float) else None


class LatencyRecorder:
    def __init__(self) -> None:
        self._pending: dict[str, float | None] = {}
        self._turns: list[TurnLatency] = []

    def ingest_message(self, role: str, report: Mapping[str, Any] | None) -> None:
        """Feed each conversation message's metrics report (role is 'user' or 'assistant')."""
        report = report or {}
        if role == "user":
            self._pending = {
                "transcription_delay": _num(report, "transcription_delay"),
                "end_of_turn_delay": _num(report, "end_of_turn_delay"),
            }
        elif role == "assistant":
            e2e = _num(report, "e2e_latency")
            if e2e is None:  # greetings and interrupted replies have no user turn to measure
                self._pending = {}
                return
            self._turns.append(
                TurnLatency(
                    transcription_delay_s=self._pending.get("transcription_delay"),
                    end_of_turn_delay_s=self._pending.get("end_of_turn_delay"),
                    llm_ttft_s=_num(report, "llm_node_ttft"),
                    tts_ttfb_s=_num(report, "tts_node_ttfb"),
                    e2e_s=e2e,
                )
            )
            self._pending = {}

    def add_tool_time(self, seconds: float) -> None:
        """Attribute tool execution time to the most recent turn."""
        if self._turns:
            self._turns[-1].tool_time_s += max(0.0, seconds)

    def turns(self) -> list[TurnLatency]:
        return list(self._turns)

    def summary(self) -> dict[str, dict[str, float]]:
        """P50/P95 in milliseconds per stage; stages with no samples are omitted."""
        series: dict[str, list[float]] = {s: [] for s in STAGES}
        for t in self._turns:
            for stage, value in (
                ("transcription_delay", t.transcription_delay_s),
                ("end_of_turn_delay", t.end_of_turn_delay_s),
                ("llm_ttft", t.llm_ttft_s),
                ("tts_ttfb", t.tts_ttfb_s),
                ("e2e", t.e2e_s),
                ("tool_time", t.tool_time_s),
            ):
                if value is not None:
                    series[stage].append(value * 1000)
        out: dict[str, dict[str, float]] = {}
        for stage in STAGES:
            xs = sorted(series[stage])
            if xs:
                out[stage] = {
                    "p50": _percentile(xs, 0.5),
                    "p95": _percentile(xs, 0.95),
                    "n": len(xs),
                }
        return out
