# Latency

Target: under 800 ms from the end of the caller's turn to the first agent audio.
**Current measurement: median 821 ms, p95 1.7 s. The target is not yet met.**

## What is measured

Per agent turn, inside the voice worker (LiveKit's turn metrics), stored with each call and shown on
the call page. `e2e` runs from the caller's speech ending to the first agent audio being produced.
It **excludes network delivery to the caller**, so it is a floor on what a person hears; on a phone
call add the PSTN and Twilio legs. Reproduce with:

```sh
VOIZY_ADMIN_DATABASE_URL=postgresql://... uv run python scripts/latency_report.py 7
```

## Latest run

Browser test calls from a laptop in India to LiveKit Cloud; default agent (Deepgram Nova 3 speech
recognition, Gemini 2.5 Flash, Cartesia Sonic voice, all through LiveKit Inference), a recorded
caller saying one short question per call, no tools.

| stage | n | p50 ms | p95 ms | max ms |
|---|---:|---:|---:|---:|
| transcription delay | 7 | 221 | 721 | 911 |
| end-of-turn detection | 7 | 577 | 817 | 920 |
| LLM first token | 7 | 383 | 657 | 734 |
| voice first byte | 7 | 92 | 95 | 95 |
| **end to end** | 7 | **821** | **1685** | 1792 |

**Read this as indicative, not a benchmark:** seven turns, one machine, one network, one recorded
voice. The p95 of seven samples is close to the maximum. Run the report on your own calls.

## Where the time goes

- **End-of-turn detection (about 580 ms)** is the largest fixed cost: waiting to be sure the
  caller has finished. `Turn-taking` settings in the agent trade speed against cutting people off.
- **LLM first token (about 380 ms)** depends on the model. Smaller, faster models help most.
- **Voice first byte (about 90 ms)** is small with Cartesia Sonic Turbo; Sonic 3 adds leading silence.
- **Tools** add their own time. The agent says a short filler first so the line is not silent.

## Not measured yet

- Real phone calls (Twilio, PSTN) end to end.
- Whether connecting to a provider directly with your own key is faster than going through LiveKit
  Inference. It removes a hop, but no number is claimed until it is measured.
- Tail latency over hundreds of turns, and behavior under concurrent calls.
