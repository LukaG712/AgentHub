---
sessionId: session-261018-190557-n48e
---

# Requirements

## Overview & Goals
Build a self-hosted "agent hub" in Python 3.11+ that manages CLI coding agents (initially JetBrains Junie CLI), a shared library of skills, and a web dashboard. Everything is free and local: no cloud, no paid APIs, no database server. The web UI works offline on a LAN.

## Key Design Changes (Pre-Phase 1 Adjustments)
- **Cross-process per-agent locking**: File lock via `fcntl.flock` on `data/locks/<agent>.lock`, held for the whole run. Web server, `hub run`, and any other process can never run the same agent simultaneously. A second caller waits its turn (queue behavior); with `--no-wait` it fails immediately with "agent busy".
- **Async-safe lock waiting**: In async code (API server), wait for the file lock in a worker thread via `asyncio.to_thread` or poll with `fcntl.LOCK_NB` and a short sleep. Never block the event loop. Open a fresh file handle for every run so `flock` really excludes other threads and processes.
- **Process group creation**: Use `subprocess.Popen(..., start_new_session=True)` instead of `preexec_fn=os.setsid`. The `preexec_fn` approach is not safe in multi-threaded programs, and the API server runs agents from background threads.
- **Three PIDs in run file**: Store `owner_pid` (the hub/CLI process that owns the run), plus the agent's `pid` and `pgid`. Queued runs have no agent `pid` yet. Stale-run recovery marks a run as "interrupted" **only** if its `owner_pid` process is dead, and must NOT touch runs that belong to another live process (e.g. a `hub run` in a terminal while the server starts).
- **Timeout counts running time only**: The timeout counts only the time the agent is actually running, not the time spent waiting in the queue.
- **HUB_TIMEOUT**: Read from environment (default 1800 seconds). Return a clear message when the agent binary is not found.
- **POSIX imports guarded**: Import `fcntl` and `os.setsid`-related code only on POSIX (guard the import), so test collection does not crash on Windows. Skip POSIX-only tests there.
- **Safe stop**: Before `hub stop` (or a timeout) kills a process group, check that the run state is "working" and that `os.getpgid(pid)` still equals the stored `pgid`. If not, do not kill anything and mark the run as stale. This prevents killing an unrelated process if the PID was reused.
- **Atomic run files**: Write every run file to a temporary file in the same folder and then `os.replace()` it into place, so the API and CLI never read a half-written file.
- **Live output**: Stream the agent's stdout and stderr into `data/runs/<agent>/<run-id>.log` while the process runs (reader thread, flush as lines arrive), and store only the path plus the final parsed answer in the run JSON. Cap the stored raw output at about 1 MB.

# Technical Design

## Current Implementation
Project is empty. Starting from scratch.

## Key Decisions
- **File-based cross-process locking** (`fcntl.flock`): Ensures only one process can run an agent at a time, regardless of whether the caller is the web server, CLI, or another process. Lock file at `data/locks/<agent>.lock`. A fresh file handle is opened for every run.
- **Async-safe lock waiting**: In async code, lock acquisition runs in a worker thread (`asyncio.to_thread`) or polls with `fcntl.LOCK_NB` to never block the event loop.
- **`start_new_session=True`**: Uses `subprocess.Popen(..., start_new_session=True)` for process group creation instead of `preexec_fn=os.setsid`, which is unsafe in multi-threaded programs.
- **Three PIDs in run file**: `owner_pid` (hub/CLI process), `pid` (agent subprocess), and `pgid` (agent process group). Enables precise stale-run recovery and cross-process `hub stop`.
- **Stale run recovery by `owner_pid`**: On startup, scan `data/runs/` for runs marked `queued` or `working` where the `owner_pid` process is dead; mark them `failed` with reason "interrupted". Runs belonging to another live process are left alone.
- **Timeout counts running time only**: The `HUB_TIMEOUT` clock starts when the agent begins executing, not when the task enters the queue.
- **`--no-wait` flag**: For CLI `hub run`, fails immediately with "agent busy" if the agent is already running, instead of queuing.
- **Guarded POSIX imports**: `fcntl` and `os.setsid` are imported only on POSIX platforms, so test collection never crashes on Windows. POSIX-only tests skip with `pytest.mark.skipif`.
- **Safe stop PID verification**: Before killing a process group (on `hub stop` or timeout), verify the run state is "working" and `os.getpgid(pid)` matches the stored `pgid`. If the PID was reused for an unrelated process, do not kill and mark the run as stale instead.
- **Atomic run file writes**: Each run JSON is written to a temporary file in the same directory, then atomically replaced with `os.replace()`. This prevents the API or CLI from reading a half-written file.
- **Live output streaming**: A reader thread streams stdout/stderr to `data/runs/<agent>/<run-id>.log` line by line, flushing as data arrives. The run JSON stores only the log file path and the final parsed answer. Raw output in the JSON is capped at ~1 MB.

## File Structure
```
hub/
  __init__.py
  config.py      # Load/save hub.yaml, name validation, backup, command resolution
  agents.py      # Agent CRUD operations
  runner.py      # Run dataclass, file locking, process group management, queue, retry, timeout, JSON parsing, run persistence
  skills.py      # Skill CRUD, symlink management, guidelines writing
  api.py         # FastAPI app with auth and endpoints
  cli.py         # Argparse-based CLI
  static/
    index.html   # Web dashboard

tests/
  __init__.py
  fake_agent.py  # Fake agent script for testing
  test_config.py
  test_agents.py
  test_runner.py
  test_skills.py
  test_api.py
  test_cli.py

hub.example.yaml
README.md
requirements.txt
data/             # Created at runtime
  runs/           # Run output files
  locks/          # File locks for per-agent locking
skills/           # Shared skill library
```

## Data Models

### Run (stored in `data/runs/<agent>/<timestamp>-<id>.json`)
```
{
  "id": "uuid",
  "agent": "agent-name",
  "task": "task description",
  "state": "queued|working|done|failed|stopped",
  "started": "ISO timestamp or null",
  "finished": "ISO timestamp or null",
  "exit_code": int or null,
  "answer": "parsed answer text",
  "log_file": "data/runs/<agent>/<run-id>.log",  # NEW: path to live log file
  "raw_output": "last ~1 MB of stdout+stderr (capped)",  # CHANGED: capped, full output in log file
  "owner_pid": int or null,   # hub/CLI process that owns this run
  "pid": int or null,         # agent subprocess ID when running
  "pgid": int or null,        # agent process group ID when running
  "fail_reason": "string or null"  # e.g. "interrupted", "timeout", "binary not found", "stale"
}
```

### Live Log File (`data/runs/<agent>/<run-id>.log`)
- Created when the agent subprocess starts
- Written line-by-line by a reader thread, flushed immediately
- Contains all stdout and stderr interleaved with `[stdout]`/`[stderr]` prefixes
- Available for reading by the API/CLI while the run is in progress
- Final file remains after the run completes for history

## Architecture Diagram

``` mermaid
graph LR
  A[CLI hub.py] --> C[runner.py]
  B[Web API api.py] --> C
  C --> D[config.py]
  C --> E[agents.py]
  C --> F[skills.py]
  C --> G[data/runs/ JSON files]
  C --> H[data/locks/ file locks]
  C --> I[subprocess Popen]
  I --> J[Agent binary]
```

# Testing

## Validation Approach
Each phase includes tests that run before proceeding. Tests use `pytest` and a fake agent script (`tests/fake_agent.py`) instead of the real `junie` command. POSIX-only tests are skipped on Windows.

## Key Scenarios

### Phase 1: Core and CLI
- Config loads and validates correctly
- Agent names rejected if invalid
- **File lock**: only one run at a time per agent across processes (`fcntl.flock`), fresh file handle per run
- **Async-safe lock**: lock wait in worker thread or `LOCK_NB` poll; event loop never blocked
- **Queue**: second task waits, then runs; `--no-wait` fails with "agent busy"
- **Three PIDs**: `owner_pid`, `pid`, and `pgid` stored in run file
- **Safe stop**: before kill, verify run state is "working" and `os.getpgid(pid)` equals stored `pgid`; if not, mark stale and don't kill
- **Stale run recovery**: orphaned runs marked `failed` with reason "interrupted" on startup; only if `owner_pid` is dead; live-process runs untouched
- **Timeout**: counts only running time (not queue time); process group killed after `HUB_TIMEOUT` (default 1800s)
- **Process group**: created with `start_new_session=True` (not `preexec_fn`)
- **Missing binary**: returns clear error message
- 429 retry: waits 30s, 60s, 90s (patched `time.sleep`)
- JSON parsing: finds answer/text/message field, falls back to raw
- **Atomic run files**: written to temp file then `os.replace()`; no half-written reads
- **Live output**: stdout/stderr streamed to `<run-id>.log` via reader thread; run JSON stores log path and capped raw output (~1 MB)
- Run files saved with correct metadata including `owner_pid`, `pid`, `pgid`, and `log_file`
- CLI commands work end-to-end
- `hub stop <run-id>` kills process group by `pgid` from run file, after verifying PGID still matches
- **Guarded imports**: `fcntl` imported only on POSIX; tests skip on Windows

### Phase 2: Skills
- Skill created, updated, deleted in `skills/` folder
- Symlinks created for enabled skills
- Stale hub symlinks removed on disable
- Foreign files untouched
- Guidelines block replaced correctly
- Path traversal rejected

### Phase 3: HTTP API
- Bearer auth required, rejects missing/invalid token
- Agent CRUD works
- Runner commands cannot be changed via API
- Skill CRUD works
- Enable/disable skill via API
- Dispatch run returns immediately, run executes in background
- Poll run status until done
- Stop run kills process
- Status endpoint returns correct states

### Phase 4: Web UI
- File served at `/`
- No external URLs in the HTML
- Manual checks documented in README

## Edge Cases
- Empty config file
- Agent with no skills
- Run with very long output
- Concurrent dispatches to same agent (cross-process)
- Skill name collision
- Guidelines file with no markers
- API key unset (refuse to start)
- Orphaned runs from crashed processes

## Test Changes
- Tests added per module as listed above
- `fake_agent.py` supports `--delay`, `--simulate-429`, `--fail`, `--hang` flags
- `JUNIE_BIN` env used by tests to point to fake agent
- POSIX-only tests marked with `@pytest.mark.skipif(sys.platform == "win32", ...)`

# Delivery Steps

### ✓ Step 1: Phase 1: Core and CLI
Build the foundation: config loading, agent runner with cross-process file locking, queue/retry/timeout, run persistence with PID/PGID tracking, and CLI commands.

- [x] Create project structure: `hub/` package, `tests/` package, `requirements.txt`, `hub.example.yaml`.
- Implement `hub/config.py`: load/save `hub.yaml`, name validation (`^[a-z0-9][a-z0-9-]{0,40}$`), backup creation, command resolution with `JUNIE_BIN` support, read `HUB_TIMEOUT` (default 1800s).
- Implement `hub/agents.py`: agent CRUD operations with validation.
- Implement `hub/runner.py`:
  - `Run` dataclass with `owner_pid`, `pid`, `pgid`, `fail_reason`, and `log_file` fields.
  - Per-agent file lock via `fcntl.flock` on `data/locks/<agent>.lock`; fresh file handle per run.
  - **Async-safe lock waiting**: in async code, acquire lock in worker thread via `asyncio.to_thread` or poll with `fcntl.LOCK_NB` + short sleep; never block event loop.
  - Queue behavior: second caller waits; `--no-wait` fails with "agent busy".
  - `subprocess.Popen` with `start_new_session=True` for process group (not `preexec_fn=os.setsid`), store `pid`/`pgid` in run file.
  - `owner_pid` set to current process PID when run is created.
  - **Safe stop**: before killing the process group (on `hub stop` or timeout), verify run state is "working" and `os.getpgid(pid)` equals the stored `pgid`. If the PID was reused, mark the run as `failed` with reason "stale" and do not send any signal.
  - Timeout kill of process group after `HUB_TIMEOUT` — **counts only running time**, not queue time.
  - 429 retry (30/60/90s waits).
  - JSON parsing with fallback.
  - Missing binary detection and clear error message.
  - **Atomic run file writes**: write to a temporary file in `data/runs/<agent>/` then `os.replace()` into the final path. Readers never see a partial file.
  - **Live output streaming**: start a reader thread that reads stdout/stderr line by line, prefixes each line with `[stdout]` or `[stderr]`, and appends to `data/runs/<agent>/<run-id>.log` with immediate flush. Store the log file path in the run JSON. Cap `raw_output` in the JSON at ~1 MB (the full output is in the log file).
  - Run file persistence to `data/runs/`.
  - Stale run recovery on startup: mark `queued`/`working` runs as `failed` with reason "interrupted" **only if `owner_pid` process is dead**; leave runs from live processes alone.
  - Guard `fcntl` import with `try/except ImportError` so test collection works on Windows.
- Implement `hub/cli.py`: argparse-based CLI with `hub agents`, `hub run [--no-wait]`, `hub runs`, `hub stop` (kills by `pgid` from run file).
- Create `tests/fake_agent.py`: fake agent script supporting `--delay`, `--simulate-429`, `--fail`, `--hang`.
- Write tests: `test_config.py`, `test_agents.py`, `test_runner.py`, `test_cli.py`.
  - Test file lock across processes.
  - Test async-safe lock doesn't block event loop.
  - Test `--no-wait` fails immediately.
  - Test three PIDs (`owner_pid`, `pid`, `pgid`) stored in run file.
  - **Test safe stop**: verify that `hub stop` checks state and `os.getpgid(pid)` before killing; test that a reused PID is not killed and is marked stale.
  - Test stale run recovery by `owner_pid` (dead owner → interrupted; live owner → untouched).
  - Test timeout counts only running time.
  - Test `start_new_session=True` creates process group.
  - Test missing binary error.
  - Test `HUB_TIMEOUT` env variable.
  - **Test atomic run files**: verify that a run file is never half-written by checking file content during a write.
  - **Test live output**: start a fake agent with `--delay` and verify that the `.log` file grows while the agent is still running; verify the run JSON stores the log file path.
  - Skip POSIX-only tests on Windows with `@pytest.mark.skipif(sys.platform == "win32", ...)`.
- Run tests, fix failures, verify all pass.

### ✓ Step 2: Phase 2: Skills

- Implement `hub/skills.py`: `list_skills`, `create_skill`, `update_skill`, `delete_skill`, `skill_usage`, `sync_agent` (symlink management, guidelines block writing).
- Add path safety: resolve and verify all paths stay within intended directories.
- Add auto-sync call before every run in `runner.py`.
- Extend CLI: `hub skills`, `hub skill-enable`, `hub skill-disable`, `hub sync`.
- Write tests: `test_skills.py` with temp dirs — symlinks created/removed, foreign files untouched, guideline block replaced, path traversal rejected.
- Run tests, fix failures, verify all pass.

### ✓ Step 3: Phase 3: HTTP API
Build the FastAPI application: authenticated CRUD endpoints, async run dispatch, status polling.

- Implement `hub/api.py`: FastAPI app with Bearer auth dependency (checks `HUB_API_KEY` env, refuses to start if unset).
- Add endpoints: agents CRUD (GET/POST/PUT/DELETE), skills CRUD, enable/disable skills, dispatch runs (POST, background execution), list/filter runs, get run details, stop run, status endpoint.
- Protect runner commands: never expose mutable command fields in API.
- Serve static files at `/`.
- Write tests: `test_api.py` with `TestClient` — auth, CRUD, dispatch and polling, stop, status, runner command protection.
- Run tests, fix failures, verify all pass.

### ✓ Step 4: Phase 4: Web UI
Build the single-file vanilla JS/CSS web dashboard: agent cards, detail panel, skills page, task bar.

- Create `hub/static/index.html`: Single HTML file with embedded CSS and JS.
- Implement dark/light mode via `prefers-color-scheme`.
- Dashboard: agent cards grouped by state (Working, Idle, Failed), polling `/api/status` every 2s.
- Bottom bar: agent dropdown, task input, send button.
- Agent panel: run output (live while working), run history, Stop button, edit form, skill toggles.
- Skills page: list, create/edit/delete, enable/disable matrix.
- Auth: first-visit API key prompt, stored in `localStorage`, 401 re-prompts.
- Security: all text escaped before DOM insertion.
- Responsive design for mobile.
- Verify: no external URLs, file served correctly.

### ✓ Step 5: Phase 5: Docs
Write the README with install, run, config reference, safety model, and manual steps.

- Create `README.md` with:
  - Install instructions (`pip install -r requirements.txt`)
  - Run command (`uvicorn hub.api:app --host 0.0.0.0 --port 8080`)
  - systemd unit file example
  - Config reference (hub.yaml structure)
  - Safety model (LAN only, runner commands in hub.yaml only)
  - Manual steps (mount vault, log in to Junie, use scratch copy)
  - How to add another runner
  - Manual UI checks
- Final verification: run all tests, ensure the app starts and serves the UI.