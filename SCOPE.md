# Voizy: MVP scope

Open-source (Apache-2.0), multi-tenant platform where voice agents are created and configured
from a dashboard, not coded. Phone calls over Twilio, **English only for now**. Target: under
800ms from end of user speech to first agent audio (median near 600-700ms, no long tail).

## In scope

1. **Agent runtime**: one generic LiveKit Agents worker that builds its pipeline from a versioned
   `AgentConfig`. Streaming STT/LLM/TTS, VAD plus semantic end-of-turn, barge-in, fillers,
   backchannel, pre-warmed connections, cached configs.
2. **Agent builder (dashboard)**: create/clone/archive, templates, persona and prompt variables,
   voices, models, turn-taking, tools, knowledge, policies, post-call. Draft/publish/diff/rollback.
   Test console: browser voice call, text chat, live transcript, per-turn latency waterfall.
3. **Tools and knowledge**: built-ins (transfer, end call, send SMS, collect fields), HTTP/webhook
   tool builder (SSRF-protected), pgvector knowledge base, signed outbound webhooks.
4. **Telephony**: Twilio SIP trunks into LiveKit, bring-your-own Twilio credentials, number
   assignment, business hours, fallback, inbound and outbound.
5. **Campaigns**: CSV contacts with variables, calling windows, timezones, concurrency, retries,
   consent/DND/quiet-hour policy, Temporal scheduling.
6. **Calls and post-call**: history, transcript, recording, summary, extracted JSON, tool calls,
   per-turn latency and cost, export, retention and PII redaction.
7. **Analytics**: volume, answer rate, dispositions, cost, P50/P95 latency per stage.
8. **Access control**: workspace superadmin, custom roles built from code-defined permissions,
   escalation prevention, last-owner protection, scoped API keys, audit log, Postgres RLS tenant
   isolation, encrypted write-only provider keys. Platform superadmin is a flag set by a CLI.
9. **Project quality**: Docker Compose self-host, CI, migrations, docs, measured latency numbers.

## Language

English only. Language stays data (`AgentConfig.languages`, per-language overrides, a `language`
column on calls, a string table for built-in phrases, provider interfaces), so adding a language
later is configuration, not a rewrite. Tamil, language detection and code-switching are phase 2.

## Out of scope (phase 2+)

Tamil and other languages, flow/stage-graph builder, MCP tools, simulated-caller evals, live
listen-in and takeover, publish approval workflow, resource-scoped roles, SSO, platform admin UI,
billing, marketplace, non-Twilio carriers.

## Build order

1. Skeleton, schema, permission model
2. Runtime and test console
3. Dashboard builder and versions
4. Twilio inbound and outbound
5. Tools and knowledge
6. English voice quality and latency tuning
7. Campaigns and policy
8. Post-call and analytics
9. Hardening, docs, latency benchmark

## Known risks

- The real Twilio + LiveKit path needs live-call verification; unverified parts are reported as such.
- Under 800ms depends on provider choice and region; the README will show measured numbers only.
