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

## Run (Docker)

```sh
cp .env.example .env   # set the two passwords
docker compose up --build
docker compose run --rm migrate voizy-admin bootstrap --name "My workspace"  # one-time API key
curl -H "Authorization: Bearer <key>" localhost:8000/v1/agents
```

License: Apache-2.0.
