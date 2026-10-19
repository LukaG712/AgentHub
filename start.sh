#!/usr/bin/env bash
# start.sh — Start the Agent Hub server
# Auto-runs setup.sh if this is the first time.
# Run this as your normal (non-root) user.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── Auto-setup if needed ─────────────────────────────────────────────
needs_setup=0

if [ ! -d ".venv" ]; then
  needs_setup=1
fi
if [ ! -f ".env" ]; then
  needs_setup=1
fi

if [ "$needs_setup" -eq 1 ]; then
  echo ""
  echo "First time running Agent Hub? Running setup..."
  echo ""
  if [ -f "setup.sh" ]; then
    bash setup.sh
  else
    echo "Error: setup.sh not found. Run setup manually."
    exit 1
  fi
  echo ""
  echo "Setup complete. Starting server..."
  echo ""
fi

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

# ── Get port from environment or default to 8080 ─────────────────────
port="${HUB_PORT:-8080}"

# ── Start the server ─────────────────────────────────────────────────
echo ""
echo "Starting Agent Hub …"
echo "Dashboard: http://localhost:$port"
echo "Press Ctrl+C to stop."
echo ""

# ── Auto-open browser ────────────────────────────────────────────────
if command -v xdg-open &>/dev/null; then
  xdg-open "http://localhost:$port" &>/dev/null &
elif command -v open &>/dev/null; then
  open "http://localhost:$port" &>/dev/null &
fi

exec uvicorn hub.api:app --host 0.0.0.0 --port "$port" --reload
