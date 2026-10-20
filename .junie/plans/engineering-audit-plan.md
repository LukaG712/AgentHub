---
sessionId: session-261020-142657-1t2p
---

# Audit Findings

## Phase 1 — Audit: Severity-Ranked Findings

I've inspected the full repository: `hub/api.py` (1854 lines), `hub/runner.py` (917 lines), `hub/memory.py` (970 lines), `hub/queue_manager.py` (213 lines), `hub/coordinator.py` (494 lines), `hub/providers.py` (418 lines), `hub/config.py` (146 lines), `hub/static/index.html` (~125KB single file), `hub/auto_review.py`, `hub/templates.py`, `hub/routines.py`, `hub/remote.py`, `hub/git_service.py`, `hub/agents.py`, `hub/cli.py`, and all 16 test files.

---

### CRITICAL — Security & Reliability

**C1. Server binds to 0.0.0.0 by default (hub/cli.py:213)**
- The `serve` command defaults `--host` to `"0.0.0.0"`, exposing the API to the entire local network. Any network neighbor can attempt brute-force on the bearer token.
- **Fix:** Default to `127.0.0.1`; document `--host 0.0.0.0` for intentional LAN exposure.

**C2. API key exposed via query parameter (hub/api.py:155-171)**
- `_verify_token_or_query` accepts the API key as a `?token=` query string for SSE endpoints. Query strings are logged in server access logs, browser history, and proxy logs.
- **Fix:** Use a cookie-based or header-only auth for SSE; or at minimum document the risk and add a warning.

**C3. `_is_process_alive()` kills the process instead of checking (hub/runner.py:150-167)**
- The fallback when `psutil` is not installed runs `taskkill /F /T /PID <pid>` — it **force-kills** the process instead of checking if it's alive. This is a data-destructive bug during stale run recovery.
- **Fix:** Use `os.kill(pid, 0)` on POSIX / `OpenProcess` on Windows to check existence without killing.

**C4. No rate limiting on authentication failures**
- Unlimited brute-force attempts against the bearer token. No lockout, delay, or logging.
- **Fix:** Add simple rate limiting (e.g., 10 failures/min → 429) with logging.

**C5. StrictHostKeyChecking=no for SSH (hub/remote.py:111)**
- SSH connections disable host key verification, enabling MITM attacks on remote execution.
- **Fix:** Make this configurable; default to checking known hosts.

---

### HIGH — Reliability & Data Integrity

**H1. Queue state lost on restart (hub/queue_manager.py)**
- `_bot_queues`, `_paused_bots`, and `_resume_events` are in-memory only. A server restart loses all queued tasks and pause state. Running tasks are recovered via `recover_stale_runs()`, but queued tasks silently disappear.
- **Fix:** Persist queue state to SQLite or JSON; replay on startup.

**H2. Config race condition (hub/config.py:43-52)**
- `save_config()` reads → backs up → writes temp → replaces. But multiple concurrent API endpoints call `load_config()` + `save_config()` without coordination, leading to lost updates (e.g., two agents created simultaneously → one overwrites the other).
- **Fix:** Add a file-level or threading lock around load-modify-save cycles.

**H3. SQLite connection leak on scheduler thread (hub/memory.py)**
- The scheduler thread calls `memory.close_connection()` at the end of each loop iteration (routines.py:139), but if an exception occurs before that, the connection stays open. Thread-local connections are never cleaned up on shutdown.
- **Fix:** Use `try/finally` in the scheduler loop; add explicit cleanup on `stop_scheduler()`.

**H4. Run file search is O(N) across all files (hub/runner.py:114-126)**
- `_load_run()` walks all JSON files under `data/runs/` and loads each one. With hundreds of runs, `get_run()`, `stop_run()`, and status checks become slow.
- **Fix:** Maintain an index (run_id → filepath) in SQLite or a cache.

**H5. SSE event store never cleaned on restart (hub/api.py:40-47)**
- `_sse_event_store` is in-memory. After restart, old run buffers are gone, but the `_sse_next_id` counter resets to 0, potentially causing ID collisions if events are replayed.
- **Fix:** Accept that SSE state is ephemeral; document this. The counter reset is harmless since stores are per-run-ID.

---

### MEDIUM — Correctness & UX

**M1. `_FileLock` on Windows is thread-only (hub/runner.py:197-251)**
- On Windows, `fcntl` is not available, so `_HAS_FLOCK = False`. The file lock becomes a no-op for cross-process locking — only the in-process `threading.Lock` works. Two separate hub processes could run the same agent concurrently.
- **Fix:** Use `msvcrt.locking()` on Windows or a cross-platform lock library.

**M2. Permissions not enforced by execution layer (hub/providers.py)**
- `AgentPermissions` generates CLI flags (e.g., `--no-file-write`), but the runner doesn't verify the provider actually respects them. If the provider ignores flags, permissions are ineffective.
- **Fix:** Document that permissions are provider-dependent; add a provider capability check.

**M3. Auto-review is post-hoc only (hub/auto_review.py + runner.py:760-789)**
- Auto-review checks output **after** the run completes. It cannot prevent a destructive command from executing — it only creates an approval record after the fact.
- **Fix:** Document this limitation clearly. The spec says "pause for approval" but the implementation checks after completion.

**M4. Static UI is a single 125KB file (hub/static/index.html)**
- All CSS, HTML, and JavaScript are in one file. This makes maintenance difficult and increases risk of regressions.
- **Fix:** Defer to Phase 4 (refactoring). Not a bug, but a maintainability risk.

**M5. No input sanitization for agent names in file paths**
- Agent names are used directly in file paths (e.g., `data/runs/{agent}/`). While `validate_name()` restricts to `[a-z0-9-]`, template names and routine names have no such validation.
- **Fix:** Add path traversal checks for all user-controlled names used in paths.

**M6. Coordinator worktrees not cleaned on failure (hub/coordinator.py)**
- When a coordinated task fails or is rejected, its worktree may not be cleaned up, leaving orphaned directories.
- **Fix:** Ensure `reject_task()` and failure paths call worktree cleanup.

---

### LOW — Code Quality & Tests

**L1. No CI configuration**
- No GitHub Actions, linting, type checking, or test matrices. `pyproject.toml` has minimal dev deps.
- **Fix:** Add CI workflow.

**L2. No type hints on most functions**
- Only `runner.py` and `coordinator.py` have partial type hints. No mypy configuration.
- **Fix:** Add to Phase 5 quality gates.

**L3. Test coverage gaps**
- No tests for: queue recovery on restart, config race conditions, process management on Windows, API auth rate limiting, coordinator worktree cleanup, or SSE reconnection.
- **Fix:** Add in Phase 5.

**L4. `__init__.py` imports create circular dependency risk**
- `hub/api.py` imports from `hub.runner`, `hub.coordinator`, `hub.queue_manager`, etc. at module level. Any circular import breaks the entire API.
- **Fix:** Use lazy imports where possible (already partially done).

**L5. Dead code: `_dispatch_run` endpoint (hub/api.py:489-510)**
- `POST /api/agents/{name}/runs` spawns a background thread that calls `run_agent()` directly, bypassing the queue manager. This creates a parallel execution path that doesn't respect per-bot sequential queueing.
- **Fix:** Either remove or wire through queue_manager.

---

## Summary Table

| ID | Severity | Category | File | Description |
|----|----------|----------|------|-------------|
| C1 | CRITICAL | Security | cli.py | Server binds to 0.0.0.0 by default |
| C2 | CRITICAL | Security | api.py | API key via query parameter |
| C3 | CRITICAL | Bug | runner.py | `_is_process_alive` kills processes |
| C4 | CRITICAL | Security | api.py | No rate limiting on auth |
| C5 | CRITICAL | Security | remote.py | StrictHostKeyChecking=no |
| H1 | HIGH | Reliability | queue_manager.py | Queue state lost on restart |
| H2 | HIGH | Data integrity | config.py | Config race condition |
| H3 | HIGH | Reliability | memory.py | SQLite connection leak |
| H4 | HIGH | Performance | runner.py | O(N) run file search |
| H5 | HIGH | Reliability | api.py | SSE state on restart |
| M1 | MEDIUM | Correctness | runner.py | File lock no-op on Windows |
| M2 | MEDIUM | Security | providers.py | Permissions not enforced |
| M3 | MEDIUM | Correctness | auto_review.py | Post-hoc review only |
| M4 | MEDIUM | Maintainability | static/index.html | Single 125KB file |
| M5 | MEDIUM | Security | Multiple | Path traversal in names |
| M6 | MEDIUM | Correctness | coordinator.py | Worktree cleanup on failure |
| L1-L5 | LOW | Quality | Multiple | CI, types, tests, imports, dead code |

# Delivery Steps

### ✓ Step 1: Write audit report and prioritize fixes
Produce the audit document in `.junie/plans/audit.md` with all findings ranked by severity. Confirm the prioritized fix list with the user before implementing.

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