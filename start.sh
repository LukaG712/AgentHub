#!/usr/bin/env bash
# start.sh — Start the Agent Hub server
# Run this as your normal (non-root) user after running setup.sh.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── Load environment variables from .env ─────────────────────────────
if [ -f ".env" ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
else
  echo "Error: .env file not found.  Run ./setup.sh first."
  exit 1
fi

if [ -z "${HUB_API_KEY:-}" ]; then
  echo "Error: HUB_API_KEY is not set in .env."
  exit 1
fi

# ── Activate virtual environment ─────────────────────────────────────
if [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
else
  echo "Error: .venv not found.  Run ./setup.sh first."
  exit 1
fi

# ── Start the server ─────────────────────────────────────────────────
echo ""
echo "Starting Agent Hub …"
echo "Dashboard: http://localhost:8080"
echo "API key:   ${HUB_API_KEY}"
echo ""
echo "Press Ctrl+C to stop."
echo ""

exec uvicorn hub.api:app --host 0.0.0.0 --port 8080
