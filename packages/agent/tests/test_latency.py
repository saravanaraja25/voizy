from __future__ import annotations

from livekit.agents import metrics
from voizy_agent.latency import LatencyRecorder


def eou(sid: str, delay: float) -> metrics.EOUMetrics:
    return metrics.EOUMetrics(
        timestamp=0.0,
        end_of_utterance_delay=delay,
        transcription_delay=0.1,
        on_user_turn_completed_delay=0.0,
        speech_id=sid,
    )


def llm(sid: str, ttft: float, cancelled: bool = False) -> metrics.LLMMetrics:
    return metrics.LLMMetrics(
        label="l",
        request_id="r",
        timestamp=0.0,
        duration=1.0,
        ttft=ttft,
        cancelled=cancelled,
        completion_tokens=1,
        prompt_tokens=1,
        prompt_cached_tokens=0,
        total_tokens=2,
        tokens_per_second=1.0,
        speech_id=sid,
    )


def tts(sid: str, ttfb: float, cancelled: bool = False) -> metrics.TTSMetrics:
    return metrics.TTSMetrics(
        label="t",
        request_id="r",
        timestamp=0.0,
        ttfb=ttfb,
        duration=1.0,
        audio_duration=1.0,
        cancelled=cancelled,
        characters_count=10,
        streamed=True,
        speech_id=sid,
    )


def test_plain_turn_total_is_sum_of_stages() -> None:
    rec = LatencyRecorder()
    for m in (eou("s1", 0.30), llm("s1", 0.50), tts("s1", 0.13)):
        rec.ingest(m)
    (turn,) = rec.turns()
    assert turn.complete and turn.llm_calls == 1
    assert abs((turn.total_s or 0) - 0.93) < 1e-9


def test_tool_turn_counts_both_llm_calls_and_tool_time() -> None:
    rec = LatencyRecorder()
    for m in (eou("s1", 0.3), llm("s1", 0.5), llm("s1", 0.4), tts("s1", 0.1)):
        rec.ingest(m)
    rec.add_tool_time("s1", 0.8)
    (turn,) = rec.turns()
    assert turn.llm_calls == 2
    assert abs((turn.total_s or 0) - 2.1) < 1e-9


def test_incomplete_turn_has_no_total_and_is_excluded_from_summary() -> None:
    rec = LatencyRecorder()
    rec.ingest(eou("s1", 0.3))
    assert rec.turns()[0].total_s is None and rec.summary() == {}


def test_cancelled_llm_and_tts_are_ignored() -> None:
    rec = LatencyRecorder()
    for m in (
        eou("s1", 0.3),
        llm("s1", 9.0, cancelled=True),
        llm("s1", 0.5),
        tts("s1", 7.0, cancelled=True),
        tts("s1", 0.1),
    ):
        rec.ingest(m)
    (turn,) = rec.turns()
    assert turn.llm_ttfts_s == [0.5] and turn.tts_ttfb_s == 0.1


def test_first_tts_audio_is_what_counts() -> None:
    rec = LatencyRecorder()
    for m in (eou("s1", 0.3), llm("s1", 0.5), tts("s1", 0.1), tts("s1", 0.4)):
        rec.ingest(m)
    assert rec.turns()[0].tts_ttfb_s == 0.1


def test_metrics_without_speech_id_are_ignored() -> None:
    rec = LatencyRecorder()
    rec.ingest(llm("", 0.5))
    assert rec.turns() == []


def test_summary_percentiles_in_milliseconds() -> None:
    rec = LatencyRecorder()
    for i, ttft in enumerate([0.4, 0.5, 0.6, 0.7, 2.0]):
        sid = f"s{i}"
        for m in (eou(sid, 0.3), llm(sid, ttft), tts(sid, 0.1)):
            rec.ingest(m)
    s = rec.summary()
    assert s["llm_ttft"]["p50"] == 600 and s["llm_ttft"]["p95"] == 2000
    assert s["total"]["n"] == 5 and s["tool_time"]["p50"] == 0
