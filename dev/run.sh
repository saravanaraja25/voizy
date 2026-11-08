#!/usr/bin/env bash
# Run the dev agent against the mock clinic API.
#   dev/run.sh            talk to it in the terminal (use headphones)
#   dev/run.sh dev        register a worker so you can join from a LiveKit room/playground
# Env knobs: MOCK_DELAY_MS (default 1500), VOIZY_LOG_TRANSCRIPTS=1 to print what is said.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
export VOIZY_DEV_AGENT_CONFIG="$PWD/dev/agent.example.json"
export VOIZY_DEV_ALLOW_LOCAL_TOOLS=1   # lets tools call loopback only; private ranges stay blocked

uv run python -m voizy_agent.devtools.mock_clinic --port 8099 --delay-ms "${MOCK_DELAY_MS:-1500}" &
MOCK_PID=$!
trap 'kill "$MOCK_PID" 2>/dev/null || true' EXIT
sleep 1.5
uv run python -m voizy_agent "${1:-console}" "${@:2}"
