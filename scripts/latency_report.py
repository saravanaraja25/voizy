"""Per-stage latency percentiles from recorded calls.

    VOIZY_ADMIN_DATABASE_URL=postgresql://... uv run python scripts/latency_report.py [days]

Reads the per-turn timings the voice worker stores with each call (numbers only, no transcripts).
These are measured inside the worker: from the end of the caller's turn to the first agent audio,
so they exclude network delivery to the caller and are a floor on what a caller hears.
"""

from __future__ import annotations

import os
import sys

import psycopg

STAGES = ("transcription_delay", "end_of_turn_delay", "llm_ttft", "tool_time", "tts_ttfb", "e2e")


def main() -> int:
    dsn = os.environ.get("VOIZY_ADMIN_DATABASE_URL")
    if not dsn:
        print("Set VOIZY_ADMIN_DATABASE_URL (a role that can read call_turns).", file=sys.stderr)
        return 2
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    with psycopg.connect(dsn) as conn:
        total = conn.execute(
            "SELECT count(*), count(DISTINCT call_id) FROM call_turns "
            "WHERE latency ? 'e2e' AND at > now() - make_interval(days => %s)",
            (days,),
        ).fetchone()
        if total is None:
            return 1
        print(f"{total[0]} agent turns over {total[1]} calls, last {days} days\n")
        print("| stage | n | p50 ms | p95 ms | max ms |")
        print("|---|---:|---:|---:|---:|")
        for stage in STAGES:
            row = conn.execute(
                "SELECT count(*), percentile_cont(0.5) WITHIN GROUP (ORDER BY v), "
                "percentile_cont(0.95) WITHIN GROUP (ORDER BY v), max(v) FROM ("
                "SELECT (latency->>%s)::numeric AS v FROM call_turns "
                "WHERE latency ? %s AND at > now() - make_interval(days => %s)) t",
                (stage, stage, days),
            ).fetchone()
            if row is not None and row[0]:
                print(f"| {stage} | {row[0]} | {row[1]:.0f} | {row[2]:.0f} | {row[3]:.0f} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
