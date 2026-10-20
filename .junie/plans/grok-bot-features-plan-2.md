---
sessionId: session-261020-105257-ymnb
---

# Current State Analysis

### What's Already Implemented

After thorough investigation of the codebase, here's what **already works**:

| Feature | Status | Location |
|---------|--------|----------|
| **SSE Streaming** | ✅ Fully implemented | `hub/api.py` lines 36-825: `SSERunStore`, `_sse_send_event`, `api_stream_session` |
| **Persistence (SQLite)** | ✅ Fully implemented | `hub/memory.py`: sessions, messages, memories, approvals, routines tables with full CRUD |
| **Queue Manager** | ✅ Fully implemented | `hub/queue_manager.py`: per-bot queue, parallel execution, pause/resume |
| **Parallel Bots** | ✅ Working | Different bots run concurrently; one bot runs one task at a time |
| **Pause/Resume** | ✅ Working | `/api/bots/{bot_id}/pause`, `/api/bots/{bot_id}/resume`, `/api/bots/{bot_id}/queue` |
| **Routines Backend** | ✅ CRUD + scheduler | `hub/memory.py` (CRUD), `hub/routines.py` (scheduler, `run_routine_now`) |
| **Approvals Backend** | ✅ CRUD | `hub/memory.py`: `create_approval`, `update_approval_status`, `list_approvals` |
| **Memory Backend** | ✅ CRUD | `hub/memory.py`: `create_memory`, `list_memories`, `update_memory`, `delete_memory` |
| **Context Assembly** | ✅ Working | `hub/memory.py` `assemble_context()`: session history + memories + project files |
| **Session Messages** | ✅ Persisted | `hub/runner.py` `_persist_run_to_session()`: saves run results as assistant messages |
| **Coordinator** | ✅ Working | `hub/coordinator.py`: multi-agent tasks with dependencies, worktree isolation, approval workflow |
| **Bearer Token Auth** | ✅ Working | All `/api/*` endpoints protected by `HUB_API_KEY` |
| **Name Validation** | ✅ Working | `^[a-z0-9][a-z0-9-]{0,40}$` in `hub/config.py` |
| **Tests** | ✅ Partial | `tests/test_grok_features.py`: persistence, queue/parallel, approvals CRUD, routines CRUD |

### What's Missing (Gaps to Fill)

| Feature | Gap | Priority |
|---------|-----|----------|
| **Routines API endpoints** | No REST endpoints expose the routines CRUD or scheduler | High |
| **Approvals API endpoints** | No REST endpoints expose approvals to the UI | High |
| **UI: Memory panel** | Placeholder card in right panel (line 625-628) | High |
| **UI: Routines panel** | Placeholder card in right panel (line 629-632) | High |
| **UI: Plugins panel** | Placeholder card in right panel (line 633-636) | High |
| **UI: Marketplace** | Disabled sidebar link (line 533-535) | Medium |
| **"Teach a Task"** | No way to save a run as a routine | Medium |
| **Bot Memory files** | No per-Bot `memory.md` file included in context | Medium |
| **Group Threads** | `bot_ids` column exists but no handoff logic | Medium |
| **Bot Handoffs** | No `@mention` or handoff API | Medium |
| **Auto Review** | No pattern-based action detection | Medium |
| **Approval UI** | No inline Approve/Deny cards in chat | Medium |
| **Plugins config** | No `plugins` section in `hub.yaml` | Low |
| **Marketplace templates** | No `templates/` directory or template API | Low |
| **"New Bot from a sentence"** | No generation endpoint | Low |
| **Browser Notifications** | No notification support | Low |
| **Scheduler startup** | Routine scheduler not started on app boot | High |

# Technical Design

### Architecture Overview

The codebase follows a layered architecture:
- **API layer** (`hub/api.py`): FastAPI endpoints, SSE streaming
- **Business logic** (`hub/runner.py`, `hub/queue_manager.py`, `hub/routines.py`, `hub/coordinator.py`)
- **Persistence** (`hub/memory.py`): SQLite with WAL mode, thread-local connections
- **Config** (`hub/config.py`, `hub.yaml`): YAML-based, immutable runner commands
- **UI** (`hub/static/index.html`): Single-page app, vanilla JS, CSS variables for theming

### Key Design Decisions

1. **Routines & Approvals API**: Add REST endpoints in `hub/api.py` following the existing pattern (e.g., `/api/memories`). No new modules needed — the CRUD functions already exist in `hub/memory.py`.

2. **Bot Memory Files**: Store as `data/bots/{bot_id}/memory.md` — simple text files, not database records. Included in `assemble_context()` in `hub/runner.py`. Path-safety validated against `NAME_RE`.

3. **Group Threads**: Reuse the existing `bot_ids` column in sessions table. Handoffs create messages with `msg_type="handoff"` and metadata tracking hop count. Max hops configurable in `hub.yaml` (default 5).

4. **Auto Review**: New `hub/auto_review.py` module with `check_action(text, patterns)` function. Patterns defined in `hub.yaml` under `auto_review.patterns`. Integrated into the SSE output callback chain.

5. **Plugins**: Defined in `hub.yaml` under `plugins:` section. Each plugin has `name`, `type` (mcp/script), `command`, and `enabled` (per-Bot toggle stored in agent config).

6. **Marketplace Templates**: YAML files in `templates/` directory. Each has `name`, `title`, `description`, `guidelines`, `suggested_skills`. `hub/templates.py` provides `list_templates()`, `get_template()`, `create_agent_from_template()`.

7. **"New Bot from a sentence"**: `POST /api/agents/generate` uses Ollama if configured (via existing `hub/ollama.py`), falls back to template-based name/title generation.

8. **Notifications**: Browser `Notification` API, triggered by SSE events. No server-side push needed — the SSE connection already delivers real-time events.

### File Changes Summary

| File | Changes |
|------|---------|
| `hub/api.py` | Add routines, approvals, handoff, templates, generate-bot endpoints |
| `hub/static/index.html` | Replace 3 placeholder cards + Marketplace link, add notification support |
| `hub/bot_memory.py` | **New**: per-Bot memory file management |
| `hub/auto_review.py` | **New**: pattern-based action detection |
| `hub/templates.py` | **New**: template loading and agent creation |
| `templates/` | **New**: 8 Bot template YAML files |
| `hub.example.yaml` | Add `plugins`, `auto_review`, `max_handoff_hops` sections |
| `README.md` | Document all new features |
| `tests/test_grok_features.py` | Add tests for new API endpoints and features |

# Testing Strategy

### Testing Approach

All tests use the existing pattern in `tests/test_grok_features.py`:
- `client_env` fixture: temporary config, database, runs dir, fake agent binary
- `JUNIE_BIN` points to `tests/fake_agent.py` (no real Junie needed)
- `TestClient` from FastAPI for HTTP endpoint testing
- Direct calls to `hub.memory.*` functions for persistence testing

### Test Coverage per Phase

**Phase 1 (API endpoints):**
- `test_routines_api_crud`: Create, list, update, delete routines via API
- `test_routines_run_now`: Trigger routine execution via API
- `test_approvals_api`: Create, list pending, approve/deny via API
- `test_bot_memory_api`: Get/set per-Bot memory via API
- `test_scheduler_started`: Verify scheduler runs on app startup

**Phase 2 (UI panels):**
- Verify HTML elements exist (no placeholder cards)
- Verify JS functions call correct API endpoints (mocked)

**Phase 3 (Bot Memory + Teach):**
- `test_bot_memory_file_crud`: Create, read, update memory.md files
- `test_bot_memory_in_context`: Verify memory.md content appears in assembled context
- `test_teach_as_routine`: Save a run as a routine via API

**Phase 4 (Handoffs):**
- `test_handoff_api`: Send handoff between bots in group thread
- `test_handoff_loop_prevention`: Verify max hops enforcement
- `test_mention_detection`: Verify @mention triggers handoff

**Phase 5 (Auto Review):**
- `test_auto_review_patterns`: Pattern matching for sensitive actions
- `test_approval_pause_resume`: Run pauses on match, resumes on approve/deny

**Phase 6 (Templates + Generate):**
- `test_templates_list`: List available templates
- `test_create_from_template`: Create agent from template
- `test_generate_from_sentence`: Generate bot config from description

**Phase 7 (Notifications):**
- Browser notification tests (manual verification in UI checklist)

### Regression Testing
After each phase: `python -m pytest tests/ -v` — all existing tests must pass.

# Delivery Steps

### ✓ Step 1: Phase 1: Missing API endpoints for existing backend features
**Wire up routines, approvals, and memory to the API so the UI can use them.**

The backend persistence layers already exist (`memory.py` has CRUD for routines, approvals, memories; `routines.py` has the scheduler; `queue_manager.py` has pause/resume). What's missing are the REST API endpoints to expose them.

- Add `/api/routines` endpoints (GET list, POST create, PUT update, DELETE, POST run-now) in `hub/api.py`
- Add `/api/approvals` endpoints (GET list pending, POST approve/deny) in `hub/api.py`
- Add `/api/bots/{bot_id}/memory` endpoint (GET/PUT) for per-Bot memory file in `hub/api.py`
- Start the routine scheduler on app startup in `hub/api.py` lifespan
- Update `hub.example.yaml` with `plugins` and `auto_review` sections as documentation
- Add tests in `tests/test_grok_features.py` for the new API endpoints
- Run `python -m pytest tests/ -v`, fix failures

### ✓ Step 2: Phase 2: Replace UI placeholders — Memory, Routines, Plugins panels
**Replace the three 'Coming soon' placeholder cards in the right panel with working UI.**

In `hub/static/index.html`:
- Replace the Memory placeholder card (lines 625-628) with a working memory editor: show per-Bot memories, allow adding/editing/deleting, connected to `/api/memories?agent=...`
- Replace the Routines placeholder card (lines 629-632) with a working routines panel: list routines for the current Bot, enable/disable toggle, run-now button, create/edit routine form, connected to `/api/routines`
- Replace the Plugins placeholder card (lines 633-636) with a plugins toggle panel: show plugins from `hub.yaml`, toggle per-Bot (stored in agent config), connected to `/api/agents/{name}` updates
- Add the "Save this run as a routine" button on successful run results in the chat thread
- Add tests by verifying the HTML elements exist and the JS functions call the correct API endpoints
- Run `python -m pytest tests/ -v`, fix failures

### ✓ Step 3: Phase 3: Bot Memory files and 'Teach a Task' feature
**Add per-Bot memory files and the ability to save a run as a reusable routine.**

- Create `hub/bot_memory.py` with functions to read/write per-Bot memory files (`data/bots/{bot_id}/memory.md`) with path-safety validation
- Modify `hub/runner.py` `assemble_context()` to include Bot memory content in the task context
- Add "Teach a Task" API: `POST /api/routines/teach` that takes a run_id, extracts the task text, and creates a routine
- Add memory update proposal flow: after a run, the Bot can propose a memory update; shown in thread as "Updated memory for <Bot>: ..." with an Undo button (stored as a message with `msg_type="memory_update"` and metadata)
- Update `hub.example.yaml` to document the memory file location
- Add tests in `tests/test_grok_features.py` for bot memory CRUD and teach-a-task flow
- Run `python -m pytest tests/ -v`, fix failures

### ✓ Step 4: Phase 4: Group Threads and Bot Handoffs
**Enable multi-Bot threads where Bots can hand off work to each other.**

- Extend `memory.py` `create_session()` to accept `bot_ids` list (already supported in schema via `bot_ids` column)
- Add `POST /api/sessions/{session_id}/handoff` endpoint: send a message from one Bot to another within the same session
- Add handoff loop prevention: track hop count in metadata, configurable max hops (default 5) in `hub.yaml`
- Add `@mention` detection: when a Bot's output contains `@bot-name`, auto-trigger a handoff
- Add UI support in `hub/static/index.html`: show "Asking Research..." and receiving Bot's reply in the same thread
- Update session creation API to accept `bot_ids` array for group threads
- Add tests in `tests/test_grok_features.py` for handoff flow and loop prevention
- Run `python -m pytest tests/ -v`, fix failures

### ✓ Step 5: Phase 5: Auto Review and Approval UI
**Add pattern-based auto-review for sensitive actions and inline approval cards in the UI.**

- Add `auto_review` section to `hub.yaml` config (list of patterns: `git push`, `rm -rf`, network calls, writing outside `project_dir`)
- Create `hub/auto_review.py` with `check_action(text)` function that matches output against configured patterns
- Integrate into `hub/runner.py` `_output_callback`: when output matches a pattern, create a pending approval and pause the run
- Add `/api/approvals/{id}/approve` and `/api/approvals/{id}/deny` endpoints
- Add inline Approve/Deny card in the chat thread (message type `approval_request`) with badge in sidebar
- Add notification badge count for pending approvals in the UI header
- Update `hub.example.yaml` with `auto_review` patterns documentation
- Add tests in `tests/test_grok_features.py` for auto-review pattern matching and approval flow
- Run `python -m pytest tests/ -v`, fix failures

### ✓ Step 6: Phase 6: Marketplace Templates and 'New Bot from a Sentence'
**Add a local library of Bot templates and the ability to create a Bot from a one-sentence description.**

- Create `templates/` directory with YAML template files (Research, Vault Librarian, Bug Reproduction, Chief of Staff, Expense Manager, Email Triage, Daily Briefing)
- Each template: `name`, `title`, `description`, `guidelines`, `suggested_skills`, `runner`
- Create `hub/templates.py` with `list_templates()`, `get_template(name)`, `create_agent_from_template(name)`
- Add `/api/templates` (GET list), `/api/templates/{name}` (GET), `/api/templates/{name}/apply` (POST: creates agent from template)
- Add "New Bot from a sentence" endpoint: `POST /api/agents/generate` — uses Ollama if configured, falls back to simple template-based generation
- Replace the Marketplace "Coming soon" sidebar link in `hub/static/index.html` with a working marketplace page showing templates with "Add to my Bots" button
- Update the New Bot dialog to auto-generate name/title/description from the sentence input
- Update `hub.example.yaml` and `README.md`
- Add tests in `tests/test_grok_features.py` for template loading, agent creation from template, and generate-from-sentence
- Run `python -m pytest tests/ -v`, fix failures

### ✓ Step 7: Phase 7: Browser Notifications and Final Polish
**Add browser notifications, badges, and final README/docs updates.**

- Add browser notification support in `hub/static/index.html`: request notification permission, show notification when a Bot finishes/fails/needs approval
- Add badge updates in the sidebar for pending approvals and queued tasks
- Add SSE event listeners for `complete`, `error`, and `approval_request` events to trigger notifications
- Add the "Plugins" section to `hub.yaml` config: MCP servers or local scripts, toggled per-Bot
- Update `hub.example.yaml` with complete examples of all new features
- Update `README.md` with documentation for all new Grok Bot features
- Update the "Web UI Manual Checks" list in README
- Final test run: `python -m pytest tests/ -v`, fix all failures
- Verify all existing tests still pass

### ✓ Step 8: Fix flaky tests
**Eliminate intermittent test failures caused by SQLite concurrency.**

- Added retry logic with exponential backoff to `_get_connection()` in `hub/memory.py` — retries up to 5 times when `sqlite3.OperationalError` occurs during connection setup (PRAGMA journal_mode=WAL)
- Added `timeout=10.0` to `sqlite3.connect()` call for better lock handling
- Added `memory.close_connection()` in the scheduler loop's `finally` block in `hub/routines.py` so the scheduler thread releases its DB connection after each iteration
- Improved `test_scheduler_started` in `tests/test_grok_features.py` to poll for thread startup with a 2-second deadline instead of a fixed 0.5s sleep
- Verified: 15 consecutive runs of `test_grok_features.py` (32 tests each) with zero failures