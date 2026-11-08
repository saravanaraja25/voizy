# Voizy

Open-source, multi-tenant platform for configurable AI voice agents. Agents are versioned
configurations created from a dashboard, not code; one generic runtime interprets them. English
first, Twilio telephony, designed for low latency. See [SCOPE.md](SCOPE.md) for the full scope and
[docs/SECURITY.md](docs/SECURITY.md) for the security rules the code is held to.

## Status

Early. The control plane (workspaces, custom roles, API keys, agents and versions, audit log) is
implemented and tested. **Not built yet:** the voice runtime, dashboard, telephony, campaigns,
human login. Nothing has been measured against real Twilio, LiveKit or STT/TTS/LLM providers, so
no latency figures are claimed.

## Layout

```
packages/core   voizy_core: domain/ security/ db/ services/ (models, authz, crypto, RLS schema)
packages/api    voizy_api:  routes/ schemas/ web/ (FastAPI control plane)
docker/         Postgres init; docker-compose.yml and Dockerfile at the root
```

## Develop

```sh
uv sync
# tests need a disposable Postgres superuser URL; each run creates and drops its own database
VOIZY_TEST_ADMIN_URL=postgresql://postgres@127.0.0.1:55432/postgres uv run pytest
uv run ruff check . && uv run mypy packages/core/src packages/api/src
```

## Dashboard

React 19 + TypeScript + Vite + Tailwind v4 + shadcn/ui, in `apps/dashboard`. Create your account on first run (see below),
then create and edit agents (prompt, voice and models, turn-taking, tools), save immutable versions,
publish, and **test-call any version from the browser** with a live transcript and a per-turn
latency chart. API types are generated from the backend's OpenAPI schema, so they cannot drift.

```sh
# API + worker (see below). Local http needs VOIZY_COOKIE_SECURE=0; origins are the dashboard's:
VOIZY_COOKIE_SECURE=0 VOIZY_CORS_ORIGINS=http://127.0.0.1:5173,http://localhost:5173 \
VOIZY_DATABASE_URL=... uv run uvicorn voizy_api.app:create_app --factory --port 8010
uv run python -m voizy_agent start          # the worker that answers test calls

cd apps/dashboard
pnpm install
pnpm dev                                    # http://127.0.0.1:5173
pnpm check                                  # lint + typecheck + tests
pnpm gen:api                                # regenerate types after backend schema changes
uv run python scripts/export_openapi.py apps/dashboard/openapi.json   # refresh the schema first
```

Production builds ship a strict Content-Security-Policy (`<meta>`); also send `frame-ancestors 'none'`
as an HTTP header, which a meta tag cannot carry. The API key lives in `sessionStorage` (this tab only).

### Keys: LiveKit, Twilio, model providers, tool credentials

Set `VOIZY_SECRET_KEYS` on the server (generate with `voizy-admin generate-secret-key`), then open
**Settings** in the dashboard: connect LiveKit, Twilio and model providers (each has a *Test
connection* button), and save named **tool credentials** that HTTP tools reference by name (each is
locked to the hosts you list). Values are encrypted, write-only, and never shown again. The voice
worker uses the saved LiveKit connection when no `LIVEKIT_*` environment variables are set; start it
after connecting LiveKit. Direct model-provider keys are stored and verified now; agents still reach
models through LiveKit Inference.

### First run, accounts and teammates

On a fresh database the API logs a line like `FIRST-RUN SETUP: ... setup token: <token>`. Open the
dashboard, paste that token, and create the workspace and your administrator account; setup then
closes for good. Invite teammates from **Team** (you get a one-time link to send them; no email
server is needed). Everyone you invite is a Superadmin for now; set `VOIZY_ENABLE_ROLES=1` to
bring back role templates, role management and per-invite roles (you can only hand out roles that
carry no more access than you have). Set `VOIZY_SETUP_TOKEN` to choose the token yourself.

## Try the voice agent locally

Needs `.env` with `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` (LiveKit Cloud; Inference
supplies STT, LLM and TTS). Use headphones.

```sh
dev/run.sh          # talk in the terminal; starts a mock clinic API with tools (1.5 s delay)
dev/run.sh dev      # or register a worker and join from a LiveKit room
```

The dev agent (`dev/agent.example.json`) books appointments through the mock API. Tools may only
call loopback in this mode (`VOIZY_DEV_ALLOW_LOCAL_TOOLS=1`); private and metadata ranges stay
blocked. Set `VOIZY_LOG_TRANSCRIPTS=1` to print what is said (off by default: personal data).

## Run everything with Docker

```sh
cp .env.example .env     # set the two DB passwords and VOIZY_SECRET_KEYS (see the comments inside)
docker compose up --build
docker compose logs api | grep "setup token"      # the one-time first-run token
```

Open <http://localhost:8080>, finish first-run setup, then connect LiveKit under **Settings**. The
voice worker container waits for that connection and picks it up within seconds: no restart, and no
`LIVEKIT_*` variables needed (set them in `.env` instead if you prefer; they win).

- Only the dashboard's port is published. Its nginx serves the app and proxies `/v1` to the API, so
  the browser sees a single origin (first-party cookies, no CORS).
- `VOIZY_COOKIE_SECURE` defaults to `0` so plain `http://localhost` works. **Put TLS in front for
  anything real, set it to `1`, and list your public origin(s) in `VOIZY_PUBLIC_ORIGINS`.**
- Database upgrades are applied by the `migrate` service on every start.
- Images: API ~350 MB, voice worker ~1.1 GB (the LiveKit agent stack), dashboard ~80 MB.

License: Apache-2.0.
