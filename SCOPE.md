# Voizy: scope and status

Open-source (Apache-2.0), multi-tenant platform where voice agents are created and configured
from a dashboard, not coded. Phone calls over Twilio, **English only for now**. Target: under
800ms from end of user speech to first agent audio (median near 600-700ms, no long tail).
**Not met yet**: about 820 ms median and 1.7 s at the 95th percentile on a small sample
([docs/LATENCY.md](docs/LATENCY.md)).

This file is the plan *and* the honest status of each part. **Built** means it exists, is tested,
and was exercised. "Not verified" notes what has not been tried against the real provider.

## Scope and status

### 1. Agent runtime
One generic LiveKit Agents worker that builds its pipeline from a versioned `AgentConfig`.
- **Built:** streaming STT/LLM/TTS through LiveKit Inference or your own provider keys (Deepgram,
  OpenAI, Google, Cartesia), Silero VAD plus LiveKit's end-of-turn detector, barge-in, spoken fillers
  while tools run, a pre-warmed VAD, hang-up, call time and silence limits.
- **Not built:** backchannel (the config field exists but does nothing), speech-to-speech ("realtime")
  models, config caching (a config is loaded per call), pre-warmed provider connections.
- **Verified:** direct Google AI key (language model) in a live conversation. **Not verified:** direct
  Deepgram, OpenAI and Cartesia keys against the real providers.

### 2. Agent builder (dashboard)
- **Built:** create agents; prompt with variables and a greeting; voice and models; turn-taking;
  tools; knowledge; privacy; immutable versions, draft and publish (publishing an earlier version is a
  rollback); a browser voice test console with live transcript and a per-turn latency chart.
- **Not built:** clone and archive, templates, a version diff view, text-chat testing, post-call
  configuration.

### 3. Tools and knowledge
- **Built:** HTTP tools with named credentials pinned to allowed hosts and an SSRF guard; built-in
  `end_call`, and on outbound calls `voicemail_detected` and `opt_out_of_calls`; a knowledge base
  (collections; looked up per turn, on request, or in the prompt) using **Postgres full-text
  search**, not pgvector (no extra service, key or extension).
- **Not built:** built-in transfer, send-SMS and collect-fields tools; signed outbound webhooks (only
  the signing primitive exists); embeddings/vector search; PDF import.

### 4. Telephony
- **Built:** Twilio Elastic SIP trunks into LiveKit set up automatically from the dashboard,
  bring-your-own Twilio credentials, number assignment, inbound and outbound calls, the other party's
  number on each call.
- **Not built:** business hours, fallback routing, call transfer to a human.
- **Verified:** trunk setup, number connection and a real outbound call on a free Twilio trial and the
  free LiveKit plan. **Not verified:** an inbound call through real Twilio.

### 5. Campaigns
- **Built:** CSV contacts with per-person variables, calling days and hours in each person's
  timezone, concurrency, retries, consent confirmation, a do-not-call list (checked at import and at
  dial time), voicemail handling and spoken opt-out. The scheduler is a Postgres-backed loop in the
  API (one instance, primary workspace), **not Temporal**.
- **Not built:** per-country compliance rules, campaign analytics.
- **Not verified:** a campaign dialing through real Twilio (the scheduler was run against real LiveKit
  with the phone leg simulated).

### 6. Calls and post-call
- **Built:** call history, transcripts with best-effort masking, tool use, per-turn latency, the other
  party's number (masked unless permitted), per-agent privacy (keep transcripts, masking, retention),
  automatic expiry, failure reasons when a provider refuses.
- **Not built:** audio recording, summaries, extracted data, cost per call, export.

### 7. Analytics
- **Partial:** summary cards on the Calls page (volume, completed, average length, median response)
  and `scripts/latency_report.py` for per-stage percentiles.
- **Not built:** dashboards for answer rate, outcomes, cost and latency trends.

### 8. Access control
- **Built:** workspace accounts and invites, a locked Superadmin role (custom roles and the full
  permission set exist in code and are switched on with `VOIZY_ENABLE_ROLES=1`), API keys and
  an audit log (through the API), Postgres row-level security isolating tenants, encrypted write-only
  keys, CSRF and Origin checks, login throttling.
- **Not built:** an API-keys page and an audit-log viewer in the dashboard, a command for the
  platform-superadmin flag, SSO.

### 9. Project quality
- **Built:** Docker Compose self-hosting (tested from a fresh clone), CI (lint, types, tests, API-type
  sync, image builds), migrations, documentation and a generated schema diagram, measured latency.
- **Not done:** a demo video, a larger published latency benchmark.

## Language

English only. Language stays data (`AgentConfig.languages`, per-language overrides, provider
interfaces), so adding a language later is configuration, not a rewrite. Tamil, language detection
and code-switching are phase 2.

## Out of scope (phase 2+)

Tamil and other languages, a flow/stage-graph builder, MCP tools, simulated-caller evals, live
listen-in and takeover, a publish approval workflow, resource-scoped roles, SSO, a platform admin UI,
billing, a marketplace, non-Twilio carriers.

## Build order

Done: 1 skeleton, schema and permissions · 2 runtime and test console · 3 dashboard builder and
versions · 4 Twilio inbound and outbound · 5 tools and knowledge · 7 campaigns and policy ·
9 hardening and docs.
In progress: 6 voice quality and latency tuning.
Next: 8 post-call summaries and analytics, call recording (opt-in), then phase 2.

## Known risks

- Real Twilio coverage is partial (see Telephony and Campaigns above); unverified parts are reported
  as such.
- Under 800ms depends on provider choice, region and, on phone calls, the carrier path; the README
  shows measured numbers only.
- Free provider tiers (LiveKit Inference, Twilio trial) have hard limits; the first-time-setup guide
  explains them, and a refused request now fails visibly instead of silently.
