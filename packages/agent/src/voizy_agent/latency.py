"""Per-turn latency accounting built from LiveKit metrics events.

A turn is identified by speech_id. The estimated response time is the sum of the stages the
caller waits through: end-of-utterance delay, every LLM time-to-first-token (more than one when a
tool is called), tool execution, and TTS time-to-first-byte. It excludes network transit and
audio playout, so it is a floor on what the caller perceives, not the whole of it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from livekit.agents import metrics

STAGES = ("eou_delay", "llm_ttft", "tool_time", "tts_ttfb", "total")


@dataclass
class TurnLatency:
    speech_id: str
    eou_delay_s: float | None = None
    transcription_delay_s: float | None = None
    llm_ttfts_s: list[float] = field(default_factory=list)
    tool_time_s: float = 0.0
    tts_ttfb_s: float | None = None

    @property
    def llm_calls(self) -> int:
        return len(self.llm_ttfts_s)

    @property
    def total_s(self) -> float | None:
        if self.eou_delay_s is None or self.tts_ttfb_s is None or not self.llm_ttfts_s:
            return None
        return self.eou_delay_s + sum(self.llm_ttfts_s) + self.tool_time_s + self.tts_ttfb_s

    @property
    def complete(self) -> bool:
        return self.total_s is not None


def _percentile(sorted_ms: list[float], q: float) -> float:
    """Nearest-rank percentile; deterministic and fine for small samples."""
    rank = max(1, math.ceil(q * len(sorted_ms)))
    return sorted_ms[rank - 1]


class LatencyRecorder:
    def __init__(self) -> None:
        self._turns: dict[str, TurnLatency] = {}

    def _turn(self, speech_id: str) -> TurnLatency:
        return self._turns.setdefault(speech_id, TurnLatency(speech_id))

    def ingest(self, m: metrics.AgentMetrics) -> None:
        speech_id = getattr(m, "speech_id", None)
        if not speech_id:
            return
        if isinstance(m, metrics.EOUMetrics):
            turn = self._turn(speech_id)
            turn.eou_delay_s = m.end_of_utterance_delay
            turn.transcription_delay_s = m.transcription_delay
        elif isinstance(m, metrics.LLMMetrics):
            if not m.cancelled:
                self._turn(speech_id).llm_ttfts_s.append(m.ttft)
        elif isinstance(m, metrics.TTSMetrics) and not m.cancelled:
            turn = self._turn(speech_id)
            if turn.tts_ttfb_s is None:  # first audio is what the caller waits for
                turn.tts_ttfb_s = m.ttfb

    def add_tool_time(self, speech_id: str, seconds: float) -> None:
        self._turn(speech_id).tool_time_s += max(0.0, seconds)

    def turns(self) -> list[TurnLatency]:
        return list(self._turns.values())

    def summary(self) -> dict[str, dict[str, float]]:
        """P50/P95 in milliseconds per stage over completed turns; empty if none yet."""
        done = [t for t in self._turns.values() if t.complete]
        if not done:
            return {}
        series: dict[str, list[float]] = {
            "eou_delay": [t.eou_delay_s * 1000 for t in done if t.eou_delay_s is not None],
            "llm_ttft": [sum(t.llm_ttfts_s) * 1000 for t in done],
            "tool_time": [t.tool_time_s * 1000 for t in done],
            "tts_ttfb": [t.tts_ttfb_s * 1000 for t in done if t.tts_ttfb_s is not None],
            "total": [t.total_s * 1000 for t in done if t.total_s is not None],
        }
        out: dict[str, dict[str, float]] = {}
        for stage in STAGES:
            xs = sorted(series[stage])
            out[stage] = {"p50": _percentile(xs, 0.5), "p95": _percentile(xs, 0.95), "n": len(xs)}
        return out
