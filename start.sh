#!/usr/bin/env bash
# start.sh — Start the Agent Hub server
# On first run, automatically sets up the environment (venv, dependencies, config, API key).
# Run this as your normal (non-root) user.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── Colours (degrade gracefully when not on a terminal) ─────────────
if [ -t 1 ]; then
  GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
else
  GREEN=''; YELLOW=''; RED=''; NC=''
fi

info()  { printf "${GREEN}✓${NC} %s\n" "$*"; }
warn()  { printf "${YELLOW}⚠${NC} %s\n" "$*"; }
fail()  { printf "${RED}✗${NC} %s\n" "$*" >&2; exit 1; }

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
  echo "========================================="
  echo "  Agent Hub — First-time setup"
  echo "========================================="
  echo ""

  # ── 1. Check Python 3.11+ ──────────────────────────────────────────
  if ! command -v python3 &>/dev/null; then
    fail "Python 3 is not installed.  Install it first, e.g.:"
    echo "      sudo apt install python3 python3-venv"
  fi

  PYVER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
  PYMAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
  PYMINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')

  if [ "$PYMAJOR" -lt 3 ] || { [ "$PYMAJOR" -eq 3 ] && [ "$PYMINOR" -lt 11 ]; }; then
    fail "Python $PYVER is too old.  Agent Hub needs Python 3.11 or newer."
  fi
  info "Python $PYVER — good."

  # ── 2. Check Junie CLI (non-blocking warning) ──────────────────────
  if ! command -v junie &>/dev/null; then
    warn "Junie CLI not found on PATH — agents won't run until it's installed."
    echo "     Install from https://junie.jetbrains.com"
  else
    JUNIE_VER=$(junie --version 2>&1 | head -1 || echo "unknown")
    info "Junie CLI found ($JUNIE_VER)."
  fi

  echo ""

  # ── 3. Create virtual environment ───────────────────────────────────
  if [ ! -d ".venv" ]; then
    echo "Creating virtual environment (.venv) …"
    python3 -m venv .venv
    info "Virtual environment created."
  else
    info "Virtual environment already exists."
  fi

  # Activate it for the rest of this script
  # shellcheck disable=SC1091
  source .venv/bin/activate

  # ── 4. Install Python dependencies ──────────────────────────────────
  echo "Installing Python packages …"
  pip install --upgrade pip -q
  pip install -r requirements.txt -q
  info "Packages installed."

  echo ""

  # ── 5. Copy hub.example.yaml → hub.yaml (never overwrite) ───────────
  if [ ! -f "hub.yaml" ]; then
    cp hub.example.yaml hub.yaml
    info "Created hub.yaml from hub.example.yaml."
  else
    info "hub.yaml already exists."
  fi

  echo ""

  # ── 6. Generate API key & .env file ─────────────────────────────────
  if [ ! -f ".env" ]; then
    API_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    echo "HUB_API_KEY=$API_KEY" > .env
    chmod 600 .env
    info "Generated API key and saved it in .env."
    echo ""
    echo "  ┌──────────────────────────────────────────────────────────┐"
    echo "  │  Your API key (save it somewhere safe!):                 │"
    echo "  │  $API_KEY"
    echo "  └──────────────────────────────────────────────────────────┘"
  else
    info ".env file already exists."
  fi

  echo ""
  echo "========================================="
  echo "  Setup complete!"
  echo "========================================="
  echo ""
fi

# ── Load environment variables from .env ─────────────────────────────
if [ -f ".env" ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
else
  echo "Error: .env file not found.  Something went wrong during setup."
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
  echo "Error: .venv not found.  Something went wrong during setup."
  exit 1
fi

# ── Get port from environment or default to 8080 ─────────────────────
port="${HUB_PORT:-8080}"

# ── What's next (first run only) ─────────────────────────────────────
if [ "$needs_setup" -eq 1 ]; then
  echo "  Next: edit hub.yaml to configure your agents, then restart."
  echo ""
fi

# ── Parse optional flags ─────────────────────────────────────────────
host="0.0.0.0"
reload_flag=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      host="$2"; shift 2 ;;
    --no-reload)
      reload_flag="--no-reload"; shift ;;
    --production)
      host="0.0.0.0"; reload_flag="--no-reload"; shift ;;
    *)
      shift ;;
  esac
done

# ── Start the server ─────────────────────────────────────────────────
echo ""
if [ -n "$reload_flag" ]; then
  echo "Starting Agent Hub in production mode …"
else
  echo "Starting Agent Hub with auto-reload …"
fi
echo "Dashboard: http://localhost:$port"
echo "Press Ctrl+C to stop."
echo ""

# ── Auto-open browser ────────────────────────────────────────────────
if command -v xdg-open &>/dev/null; then
  xdg-open "http://localhost:$port" &>/dev/null &
elif command -v open &>/dev/null; then
  open "http://localhost:$port" &>/dev/null &
fi

if [ -n "$reload_flag" ]; then
  exec uvicorn hub.api:app --host "$host" --port "$port"
else
  exec uvicorn hub.api:app --host "$host" --port "$port" --reload
fi
