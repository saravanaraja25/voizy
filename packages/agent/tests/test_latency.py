from __future__ import annotations

from voizy_agent.latency import LatencyRecorder

USER = {"transcription_delay": 0.2, "end_of_turn_delay": 0.4}


def assistant(e2e: float | None = 1.0, ttft: float = 0.5, ttfb: float = 0.13) -> dict[str, float]:
    report = {"llm_node_ttft": ttft, "tts_node_ttfb": ttfb}
    if e2e is not None:
        report["e2e_latency"] = e2e
    return report


def test_assistant_message_pairs_with_the_preceding_user_message() -> None:
    rec = LatencyRecorder()
    rec.ingest_message("user", USER)
    rec.ingest_message("assistant", assistant(e2e=1.2))
    (turn,) = rec.turns()
    assert (turn.transcription_delay_s, turn.end_of_turn_delay_s) == (0.2, 0.4)
    assert (turn.llm_ttft_s, turn.tts_ttfb_s, turn.e2e_s) == (0.5, 0.13, 1.2)


def test_greeting_without_e2e_is_not_a_turn_and_clears_pending() -> None:
    rec = LatencyRecorder()
    rec.ingest_message("assistant", assistant(e2e=None))
    rec.ingest_message("user", USER)
    rec.ingest_message("assistant", assistant(e2e=None))  # interrupted reply
    rec.ingest_message("assistant", assistant(e2e=0.9))
    (turn,) = rec.turns()  # stale user metrics must not leak into a later turn
    assert turn.e2e_s == 0.9 and turn.end_of_turn_delay_s is None


def test_missing_or_garbage_metrics_are_tolerated() -> None:
    rec = LatencyRecorder()
    rec.ingest_message("user", None)
    rec.ingest_message("assistant", {"e2e_latency": "fast", "llm_node_ttft": None})
    assert rec.turns() == []
    rec.ingest_message("assistant", {"e2e_latency": 1})
    assert rec.turns()[0].e2e_s == 1.0 and rec.turns()[0].llm_ttft_s is None


def test_tool_time_attaches_to_latest_turn_and_ignores_negatives() -> None:
    rec = LatencyRecorder()
    rec.add_tool_time(1.0)  # no turn yet: ignored
    rec.ingest_message("user", USER)
    rec.ingest_message("assistant", assistant())
    rec.add_tool_time(0.8)
    rec.add_tool_time(-5)
    assert rec.turns()[0].tool_time_s == 0.8


def test_summary_percentiles_in_milliseconds_and_omits_empty_stages() -> None:
    rec = LatencyRecorder()
    assert rec.summary() == {}
    for e2e in (0.8, 0.9, 1.0, 1.1, 3.0):
        rec.ingest_message("user", USER)
        rec.ingest_message("assistant", assistant(e2e=e2e))
    s = rec.summary()
    assert s["e2e"] == {"p50": 1000.0, "p95": 3000.0, "n": 5}
    assert s["llm_ttft"]["p50"] == 500.0 and s["tool_time"]["p50"] == 0.0
