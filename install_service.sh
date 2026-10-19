#!/usr/bin/env bash
# install_service.sh — Install Agent Hub as a systemd service
# Run with sudo:  sudo ./install_service.sh
set -euo pipefail

# ── Must be run as root (via sudo) ───────────────────────────────────
if [ "$EUID" -ne 0 ]; then
  echo "Error: This script must be run with sudo."
  echo "      sudo ./install_service.sh"
  exit 1
fi

# ── Resolve the real user ────────────────────────────────────────────
if [ -z "${SUDO_USER:-}" ]; then
  echo "Error: SUDO_USER is not set.  Run this script with sudo, not as root directly."
  exit 1
fi

REAL_USER="$SUDO_USER"
REAL_HOME=$(eval echo "~$REAL_USER")

if [ ! -d "$REAL_HOME" ]; then
  echo "Error: Home directory for $REAL_USER ($REAL_HOME) does not exist."
  exit 1
fi

# ── Locate the project directory ─────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -f "$SCRIPT_DIR/requirements.txt" ]; then
  echo "Error: Script must be run from the Agent Hub directory."
  exit 1
fi

ENV_FILE="$SCRIPT_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
  echo "Error: .env file not found.  Run ./start.sh first."
  exit 1
fi

VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"
if [ ! -f "$VENV_PYTHON" ]; then
  echo "Error: Virtual environment not found.  Run ./start.sh first."
  exit 1
fi

# ── Write the systemd unit file ──────────────────────────────────────
UNIT_NAME="agent-hub"
UNIT_FILE="/etc/systemd/system/${UNIT_NAME}.service"

echo "Installing systemd service: $UNIT_NAME"
echo "  User:       $REAL_USER"
echo "  Home:       $REAL_HOME"
echo "  WorkingDir: $SCRIPT_DIR"
echo "  Env file:   $ENV_FILE"
echo ""

cat > "$UNIT_FILE" <<EOF
[Unit]
Description=Agent Hub — self-hosted agent dashboard
After=network.target

[Service]
Type=simple
User=${REAL_USER}
Environment=HOME=${REAL_HOME}
EnvironmentFile=${ENV_FILE}
WorkingDirectory=${SCRIPT_DIR}
ExecStart=${SCRIPT_DIR}/.venv/bin/uvicorn hub.api:app --host 0.0.0.0 --port 8080
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# ── Enable and start the service ─────────────────────────────────────
systemctl daemon-reload
systemctl enable "$UNIT_NAME"
systemctl start "$UNIT_NAME"

echo ""
echo "Service installed and started!"
echo ""
echo "  Check status:   systemctl status $UNIT_NAME"
echo "  View logs:      journalctl -u $UNIT_NAME -f"
echo "  Stop:           sudo systemctl stop $UNIT_NAME"
echo "  Disable:        sudo systemctl disable $UNIT_NAME && sudo rm $UNIT_FILE"
echo ""
echo "  Dashboard: http://localhost:8080"
echo ""
