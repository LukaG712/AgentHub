---
sessionId: session-261020-142657-1t2p
---

# Desktop App, Portable EXE, Installer & Always-On VM Web Server

## Current Session — Fix & Verify (2026-10-20)

### Issues Fixed
1. **CI lint failures** — Added ruff config to `pyproject.toml`, fixed `Run` import in `hub/api.py`, auto-fixed 43 style issues
2. **Desktop authentication** — Replaced iframe approach with direct WebView navigation; cookie injected after navigation via Rust `eval()` so it's scoped to the server's origin
3. **Desktop lifecycle** — Removed minimize-to-tray behavior; app now closes properly without affecting the VM backend
4. **Bundle targets** — Removed macOS-only "app" target; kept NSIS installer only for Windows
5. **CI workflow** — Updated `desktop-build.yml` to fail on missing artifacts, added portable zip generation
6. **Tests workflow** — Added matrix build (Python 3.11-3.13, Windows + Linux)
7. **Tauri config** — Fixed `devPath`/`frontendDist` to point to `../index.html`
8. **Placeholder icon** — Created `icons/icon.png` for Tauri build

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         VM (Ubuntu/Debian)                      │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  systemd: agent-hub.service                              │  │
│  │  ┌────────────────────────────────────────────────────┐  │  │
│  │  │  FastAPI (uvicorn) on 0.0.0.0:8080                │  │  │
│  │  │  ┌─────────────┐  ┌─────────────┐  ┌───────────┐ │  │  │
│  │  │  │ REST API    │  │ SSE Stream  │  │ Static UI │ │  │  │
│  │  │  └─────────────┘  └─────────────┘  └───────────┘ │  │  │
│  │  │  ┌─────────────┐  ┌─────────────┐  ┌───────────┐ │  │  │
│  │  │  │ SQLite DB   │  │ Run Queue   │  │ Scheduler │ │  │  │
│  │  │  └─────────────┘  └─────────────┘  └───────────┘ │  │  │
│  │  └────────────────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  Data: data/hub.db, data/runs/, data/queue_state.json           │
│  Config: hub.yaml, .env (HUB_API_KEY)                           │
└─────────────────────────────────────────────────────────────────┘
         ▲                      ▲                      ▲
         │ HTTP/SSE             │ HTTP/SSE             │ HTTP
         │                      │                      │
┌────────┴────────┐    ┌───────┴───────┐    ┌────────┴────────┐
│ Browser (LAN)   │    │ Tauri Desktop │    │ Other LAN device │
│ http://vm-ip:8080│    │ App (Windows) │    │ Browser          │
└─────────────────┘    └───────────────┘    └─────────────────┘
```

## Key Design Decisions

1. **Tauri for desktop** — Lightweight (~5-10MB), uses system WebView2 on Windows, embeds the existing SPA frontend directly. Requires Rust toolchain for building.
2. **VM runs Ubuntu/Debian** — systemd service for auto-start and crash recovery.
3. **LAN + desktop access** — CORS configured for LAN browser access; Tauri desktop app connects via configurable server URL.
4. **Single backend** — All three access methods (browser, desktop, LAN) connect to the same VM-hosted FastAPI instance. No duplicate backend in the desktop app.
5. **Frontend remains unchanged** — The existing `hub/static/index.html` SPA is reused as-is. Tauri loads it from the remote VM URL (not bundled locally).

---

# Audit Findings (Previous Engineering Audit — All Fixed ✓)

All 20+ findings from the previous engineering audit have been fixed and committed. See git history for details.

---

# Delivery Steps

### ✓ Step 1: Write audit report and prioritize fixes
Produce the audit document with all findings ranked by severity. Confirm the prioritized fix list with the user before implementing.

### ✓ Step 2: Fix critical bugs: process check, server bind, query auth
- Fix `_is_process_alive()` in `hub/runner.py` to check without killing (C3)
- Change default host to `127.0.0.1` in `hub/cli.py` (C1)
- Remove query parameter auth fallback in `hub/api.py`; use cookie or header-only (C2)
- Add basic rate limiting decorator for auth failures (C4)
- Make `StrictHostKeyChecking` configurable in `hub/remote.py` (C5)
- Add regression tests for each fix
- Run `python -m pytest tests/ -v`

### ✓ Step 3: Fix high-priority reliability issues
- Persist queue state to SQLite in `hub/queue_manager.py` and replay on startup (H1)
- Add threading lock around load-modify-save in `hub/config.py` (H2)
- Fix SQLite connection leak in scheduler with try/finally (H3)
- Add run_id index to SQLite for fast lookup (H4)
- Add regression tests; run test suite

### ✓ Step 4: Fix medium-priority correctness issues
- Implement cross-platform file lock using `msvcrt.locking()` on Windows (M1)
- Document permissions limitations in README (M2)
- Document auto-review post-hoc limitation (M3)
- Remove or wire through queue_manager the `/api/agents/{name}/runs` endpoint (M5/dead code)
- Fix coordinator worktree cleanup on reject/failure (M6)
- Add regression tests; run test suite

### ✓ Step 5: Add CI, linting, and quality gates
- Add GitHub Actions workflow with test matrix (Python 3.11-3.13, Windows + Linux)
- Add linting (ruff or flake8) and basic type checking
- Update `pyproject.toml` dev dependencies
- Run full test suite; ensure all tests pass
- Update README with new configuration options and security notes

---

## ✓ Phase 1 — Backend: Health, CORS, and VM Service Improvements

**Completed:** Added health/ready endpoints, CORS middleware, improved systemd service, production mode flags, and documentation.

### Health and Readiness Endpoints ✓
- Added `GET /api/health` — returns `{"status": "ok", "version": "1.0.3"}` (unauthenticated)
- Added `GET /api/ready` — checks SQLite connectivity and config validity (returns 503 if not ready)

### CORS Middleware ✓
- Added `CORSMiddleware` to FastAPI with configurable allowed origins via `hub.yaml` `cors` section
- Default: allow `http://localhost:*` and `http://127.0.0.1:*`
- Documented in `hub.example.yaml` how to add custom origins for LAN access

### Improved systemd Service ✓
- Updated `install_service.sh` with:
  - `ExecStartPost` for health check delay
  - `StartLimitIntervalSec=60` and `StartLimitBurst=5` for crash restart limits
  - `LimitNOFILE=65536` for high file descriptor counts
  - `TimeoutStartSec=30` and `TimeoutStopSec=10`
  - Journal logging with `SyslogIdentifier=agent-hub`
  - `--host 0.0.0.0` explicitly in ExecStart for LAN access

### Improved start scripts ✓
- Added `--production` and `--host` flags to both `start.sh` and `start.ps1`
- Production mode disables auto-reload

### Files modified
- `hub/api.py` — Health/ready endpoints, CORS middleware
- `install_service.sh` — Enhanced systemd unit
- `start.sh` — Production mode flags
- `start.ps1` — Production mode flags
- `hub.example.yaml` — CORS and network config documentation
- `README.md` — VM deployment and desktop app sections

---

## ✓ Phase 2 — Tauri Desktop App Setup

**Completed:** Full Tauri project with settings page, connection handling, and health checks.

### Tauri Project Structure
Create a new `desktop/` directory with Tauri project:

```
desktop/
├── src/
│   └── main.rs              # Tauri Rust entry point
├── src-tauri/
│   ├── tauri.conf.json      # App config (name, version, window, etc.)
│   ├── Cargo.toml           # Rust dependencies
│   ├── build.rs             # Build script
│   ├── icons/               # App icons (generated)
│   └── permissions/         # Tauri permissions
├── index.html               # Splash/settings page (minimal)
├── package.json             # Node.js for build tooling only
└── README.md                # Build instructions
```

### App Architecture
- The Tauri app does NOT bundle the AgentHub frontend locally
- Instead, it loads the remote VM's URL (`http://vm-ip:8080`) in a WebView2 window
- A minimal settings page (local) allows configuring the server URL
- The main window navigates to the remote URL after settings are saved

### Settings Storage
- Server URL stored in Tauri's `store` API (encrypted JSON file in `%APPDATA%\agent-hub-desktop\`) 
- API key stored in the same store
- Connection status tracked in the window title bar

### First-Run Flow
1. App launches → shows settings page (local HTML)
2. User enters VM URL (e.g., `http://192.168.1.100:8080`) and API key
3. App validates connection via `/api/health`
4. On success, opens main window loading the remote AgentHub UI
5. On failure, shows error and allows retry

### Connection Handling
- Periodic health check (every 30s) to detect VM disconnect
- Auto-reconnect with exponential backoff on failure
- Status indicator in title bar (green/red dot)
- Manual reconnect button in settings

### Files to create
- `desktop/` — Full Tauri project
- `desktop/src/main.rs` — Window management, settings commands
- `desktop/src-tauri/tauri.conf.json` — App configuration
- `desktop/src-tauri/Cargo.toml` — Dependencies
- `desktop/settings.html` — Local settings page
- `desktop/README.md` — Build instructions

---

## ✓ Phase 3 — Portable and Installer Builds

**Completed:** Configured in `tauri.conf.json` with NSIS installer and portable app bundle targets.

### Portable Build
- Use Tauri's `tauri.conf.json` with `bundle.type = "app"` for a portable directory
- Package as `AgentHub-Portable-Windows-x64.zip` containing:
  - `agent-hub-desktop.exe`
  - Required WebView2 runtime check (uses system WebView2, no bundling)
  - `settings/` directory for user config
- No admin privileges required
- Settings stored in `%APPDATA%` (writable), not in the portable directory

### Installer Build
- Use Tauri's built-in NSIS installer support (`bundle.targets = ["nsis"]`)
- Produces `AgentHub-Setup-Windows-x64.exe`
- Installs to `%LOCALAPPDATA%\agent-hub-desktop` (per-user, no admin needed)
- Creates Start Menu shortcut
- Optional desktop shortcut
- Clean uninstaller that preserves `%APPDATA%` settings
- Version-aware upgrades that don't delete user data

### Build Configuration
- Update `tauri.conf.conf.json` with proper metadata:
  - Product name: "AgentHub Desktop"
  - Publisher: from `pyproject.toml` authors
  - Version: synced with `pyproject.toml` version
  - Icon: generated from Tauri icon generator

### Files to modify
- `desktop/src-tauri/tauri.conf.json` — Bundle configuration
- `desktop/src-tauri/tauri.conf.json` — NSIS installer settings

---

## ✓ Phase 4 — CI/CD for Desktop Builds

**Completed:** Added GitHub Actions workflow for desktop builds.

### GitHub Actions Workflow
- Add `desktop-build.yml` workflow:
  - Triggers on push to master and manual dispatch
  - Runs on `windows-latest`
  - Installs Rust toolchain
  - Installs Node.js (for Tauri CLI)
  - Runs `tauri build` producing both portable and installer artifacts
  - Uploads artifacts to the workflow run
  - Does NOT publish to GitHub Releases without authorization

### Build Artifacts
- `AgentHub-Portable-Windows-x64.zip`
- `AgentHub-Setup-Windows-x64.exe`

### Files to create
- `.github/workflows/desktop-build.yml`

---

## ✓ Phase 5 — Documentation and Testing

**Completed:** Updated README with VM deployment, desktop app, and troubleshooting sections.

### Documentation Updates
- **README.md**: Add sections for:
  - VM deployment (systemd service, start/stop/status commands)
  - LAN access configuration (CORS, firewall, network binding)
  - Desktop app (build, install, configure, connect)
  - Portable vs Installer comparison
  - Troubleshooting guide
  - Backup and restore procedures
  - Update procedure with rollback

- **desktop/README.md**: Build prerequisites, step-by-step build instructions

### Tests
- Backend tests for health/ready endpoints
- CORS configuration tests
- Settings storage tests (Tauri store)
- Connection validation tests
- Service script validation (syntax check)

### Files to modify
- `README.md` — Comprehensive deployment and desktop documentation
- `tests/test_api.py` — Health endpoint tests
- `tests/test_cors.py` — CORS configuration tests

---

## Summary of All Changes

| Phase | What | Files |
|-------|------|-------|
| 1 | Health, CORS, VM service | `hub/api.py`, `install_service.sh`, `start.sh`, `start.ps1`, `hub.example.yaml`, `README.md` |
| 2 | Tauri desktop app | `desktop/` (new directory) |
| 3 | Portable + installer builds | `desktop/src-tauri/tauri.conf.json` |
| 4 | CI/CD for desktop | `.github/workflows/desktop-build.yml` |
| 5 | Documentation + tests | `README.md`, `desktop/README.md`, `tests/` |