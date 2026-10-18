#!/usr/bin/env bash
# setup.sh — One-time setup for Agent Hub
# Safe to run more than once.  Run it as your normal (non-root) user.
set -euo pipefail

# ── Colours (degrade gracefully when not on a terminal) ─────────────
if [ -t 1 ]; then
  GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
else
  GREEN=''; YELLOW=''; RED=''; NC=''
fi

info()  { printf "${GREEN}✓${NC} %s\n" "$*"; }
warn()  { printf "${YELLOW}⚠${NC} %s\n" "$*"; }
fail()  { printf "${RED}✗${NC} %s\n" "$*" >&2; exit 1; }

echo "========================================="
echo "  Agent Hub — Setup"
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
  echo "      On Debian/Ubuntu:  sudo apt install python3.11 python3.11-venv"
  echo "      Then make sure 'python3' points to 3.11+."
fi
info "Python $PYVER — good."

# ── 2. Check junie CLI ──────────────────────────────────────────────
if ! command -v junie &>/dev/null; then
  warn "The 'junie' command was not found on your PATH."
  echo "     Agent Hub needs Junie CLI to run agents."
  echo "     Install it from https://junie.jetbrains.com and make sure 'junie' is on your PATH."
  echo ""
  echo "     You can still start the hub without junie, but agents won't run."
  echo "     Press Enter to continue anyway, or Ctrl+C to abort."
  read -r
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
  echo "     Edit hub.yaml to set project_dir and other settings."
else
  info "hub.yaml already exists (not overwritten)."
fi

echo ""

# ── 6. Generate API key & .env file ─────────────────────────────────
if [ ! -f ".env" ]; then
  API_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
  echo "HUB_API_KEY=$API_KEY" > .env
  chmod 600 .env
  info "Generated API key and saved it in .env (chmod 600)."
  echo ""
  echo "  ┌──────────────────────────────────────────────────────────┐"
  echo "  │  Your API key (save it somewhere safe!):                 │"
  echo "  │  $API_KEY"
  echo "  └──────────────────────────────────────────────────────────┘"
else
  info ".env file already exists (not overwritten)."
  echo "     Your API key is stored in .env."
fi

echo ""
echo "========================================="
echo "  Setup complete!"
echo "========================================="
echo ""
echo "What's next:"
echo ""
echo "  1. Edit hub.yaml — set project_dir for each agent."
echo "  2. Start the server:"
echo "     ./start.sh"
echo "  3. Open http://localhost:8080 in your browser."
echo "     Enter the API key from .env when prompted."
echo ""
echo "  To run in the background (systemd):"
echo "     sudo ./install_service.sh"
echo ""
