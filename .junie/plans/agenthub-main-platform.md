---
sessionId: session-261018-220404-99he
---

# Audit & Architecture

## Current Architecture — What Works

AgentHub is a Python/FastAPI application with a single-page HTML dashboard. It already provides:

- **Agent management** (`hub/agents.py`, `hub/config.py`): CRUD for agents stored in `hub.yaml` (YAML). Agents reference runners (command templates) and skills.
- **Runner** (`hub/runner.py`): Subprocess-based agent execution with cross-process file locking, process group management, timeout, retry on 429, live output streaming to log files, atomic run-file writes, and stale-run recovery. Runs are persisted as JSON in `data/runs/<agent>/`.
- **Skills** (`hub/skills.py`): Shared skill library in `skills/` directory. Skills are synced to agent project directories via symlinks (or copy on Windows). Guidelines are written to `.junie/AGENTS.md` with hub-managed markers.
- **API** (`hub/api.py`): FastAPI with Bearer token auth. Endpoints for agents CRUD, skills CRUD, agent-skill enable/disable, run dispatch/status/stop, and overall status.
- **CLI** (`hub/cli.py`): argparse-based CLI for agents, runs, skills management.
- **Frontend** (`hub/static/index.html`): Single-page vanilla JS dashboard with agent cards, agent detail panel (edit, skills, run history), skills page with matrix, and a bottom task bar.
- **Tests** (`tests/`): Comprehensive test suite with a `fake_agent.py` for runner testing.
- **Setup** (`setup.sh`, `start.sh`): Linux-focused setup with venv, API key generation, systemd service.

## Key Gaps (vs. Desired State)

1. **No conversation model** — tasks are dispatched as one-off runs with no chat interface, no conversation history, no session concept.
2. **No persistent memory** — runs are stored as JSON files but there's no structured conversation history, project knowledge, or task state that persists meaningfully across sessions.
3. **No streaming to frontend** — the API dispatches runs in a background thread and returns immediately; the frontend polls `/status` but never sees live progress.
4. **No project browsing** — projects are hardcoded in `hub.yaml`; no UI to browse or select local projects.
5. **Linux-only setup** — `setup.sh`, `start.sh`, and `install_service.sh` are bash scripts; no Windows support.
6. **No provider abstraction** — Junie CLI is hardcoded as the only runner; no clean interface for adding other agents.
7. **No Ollama integration** — no support for local LLM for planning, summarization, etc.
8. **No Obsidian integration** — not implemented at all.
9. **No SSE/WebSocket for live output** — the frontend cannot see agent progress in real time.
10. **Run detail is weak** — clicking a run shows an `alert()` dialog; no proper detail view.

## Architecture Approach

Keep the existing structure and extend it incrementally:

```
graph LR
  U[Frontend index.html] -->|HTTP| A[FastAPI api.py]
  A -->|dispatch| R[runner.py]
  R -->|subprocess| J[Junie CLI]
  A -->|CRUD| AG[agents.py]
  A -->|CRUD| SK[skills.py]
  A -->|read/write| C[config.py hub.yaml]
  A -->|new| M[memory.py SQLite]
  R -->|persist| D[data/runs/ JSON]
  A -->|SSE| U
```

- Add `hub/memory.py` — SQLite-based persistence for conversations, sessions, project knowledge, and memories.
- Extend `hub/api.py` — add conversation/session endpoints, SSE endpoint for live run output, project browsing.
- Extend `hub/static/index.html` — add chat interface, conversation list, session management, run detail view.
- Add `start.ps1` — Windows startup script.
- Add provider interface in `hub/runner.py` — abstract the Junie-specific command resolution.

# Phase 1 — Core Workflow & Chat Interface

### Goal
Make AgentHub usable as a local coding-agent platform: select a project/agent, chat with the agent, see live progress, and review results.

### Changes

**1. SQLite memory layer** (`hub/memory.py`)
- SQLite database at `data/hub.db` with tables:
  - `sessions`: id, agent_name, project_dir, title, created_at, updated_at
  - `messages`: id, session_id, role (user/assistant/system), content, created_at
  - `memories`: id, agent_name, category (project_knowledge/decision/issue), title, content, created_at
- Functions: create_session, add_message, get_session_messages, search_memories, upsert_memory, delete_memory
- Migrations handled via simple version check on first load

**2. Extended API** (`hub/api.py`)
- `GET /api/sessions` — list sessions, filtered by agent
- `POST /api/sessions` — create session (agent_name, optional title)
- `GET /api/sessions/{id}` — get session with messages
- `POST /api/sessions/{id}/messages` — add user message and dispatch agent run
- `GET /api/sessions/{id}/stream` — SSE endpoint for live run output
- `GET /api/memories` — list/search memories
- `POST /api/memories` — create memory
- `DELETE /api/memories/{id}` — delete memory
- `GET /api/projects` — list local directories (scan common locations)

**3. Extended runner** (`hub/runner.py`)
- Add `session_id` field to `Run` dataclass
- On run completion, save the agent's answer as an assistant message in the session
- Thread-safe message writing

**4. Chat frontend** (`hub/static/index.html`)
- Add **Chat** page (new nav tab) with:
  - Left sidebar: session list (create, select, delete)
  - Main area: message list with user/assistant bubbles
  - Input bar: text input + send button, agent selector
  - Live output: when agent is working, show streaming output via SSE
- Improve run detail: replace `alert()` with a proper panel showing output, answer, and log
- Add **Memory** page (new nav tab) for viewing and managing memories

**5. Windows startup** (`start.ps1`)
- PowerShell equivalent of `start.sh`: load `.env`, activate venv, start uvicorn

# Phase 2 — Persistence & Context

### Goal
Make conversations and project context meaningful across sessions.

### Changes

**1. Context assembly** (`hub/memory.py` + `hub/runner.py`)
- When dispatching a task, assemble context from:
  - Recent messages from the same session (last N messages)
  - Relevant memories for the agent's project
  - Project guidelines from the agent config
  - AGENTS.md files found in the project directory
- Append context to the task prompt sent to the agent
- Configurable context window (number of messages, memory limit)

**2. Session resumption** (`hub/api.py` + frontend)
- Sessions show last message preview in the sidebar
- Clicking a session loads the conversation and allows continuing
- "New session" button creates a fresh session

**3. Memory management UI** (frontend)
- Memory page with categories (project knowledge, decisions, issues)
- Search/filter memories
- Create, edit, delete memories
- "Save to memory" button on completed runs to capture useful context

**4. Project discovery** (`hub/api.py`)
- `GET /api/projects` scans common directories (Desktop, Documents, workspace) for git repos
- Returns list of project paths with repo name and last commit date
- Agent creation can select a discovered project

# Phase 3 — Provider Abstraction & Safety

### Goal
Make Junie one of several possible agent providers; improve safety and reliability.

### Changes

**1. Provider interface** (`hub/providers.py`)
- Abstract base: `AgentProvider` with methods: `run(task, project_dir, skills, guidelines, timeout)`, `check_available()`, `name`
- `JunieProvider` implements the current subprocess-based approach
- Runner uses the provider interface instead of direct command resolution
- Config supports `providers` section mapping provider names to type and settings

**2. Tool permissions** (`hub/config.py` + `hub.yaml`)
- Add `permissions` field to agent config: `file_read`, `file_write`, `command_exec`, `git_ops`, `network`
- Default: all enabled for local agents (safe default for self-hosted)
- Runner passes permission flags to the agent command

**3. Error handling improvements**
- Validate config on startup and report actionable errors via `/api/status`
- Graceful handling of missing Junie, unavailable projects, timeouts
- Better error messages in the frontend

**4. Tests**
- Tests for memory layer (CRUD, search, persistence)
- Tests for session/message API
- Tests for provider interface
- Tests for context assembly

# Delivery Steps

### ✓ Step 1: Phase 1A: SQLite memory layer and extended API
Add persistent storage for conversations, sessions, and memories, plus the new API endpoints.
- Create `hub/memory.py` with SQLite database at `data/hub.db`: tables for sessions, messages, and memories with CRUD functions and search.
- Extend `Run` dataclass in `hub/runner.py` with `session_id` field; on run completion, save the agent's answer as an assistant message.
- Add API endpoints to `hub/api.py`: sessions CRUD (`GET/POST /api/sessions`, `GET /api/sessions/{id}`), message dispatch (`POST /api/sessions/{id}/messages`), SSE streaming (`GET /api/sessions/{id}/stream`), memories CRUD (`GET/POST/DELETE /api/memories`), project discovery (`GET /api/projects`).
- Add tests for memory layer in `tests/test_memory.py` and for new API endpoints in `tests/test_api.py`.
- Add `aiosqlite` or use SQLite synchronously in background threads (no async needed since runs execute in threads already).

### ✓ Step 2: Phase 1B: Chat frontend and Windows startup
Build the chat interface and make the app runnable on Windows.
- Extend `hub/static/index.html` with a Chat page: left sidebar for session list (create/select/delete), main message area with user/assistant bubbles, input bar with agent selector, live output via SSE when agent is working.
- Replace the `alert()`-based run detail with a proper panel showing output, answer, state, and log file path.
- Add a Memory page (nav tab) for viewing, searching, creating, and deleting memories.
- Add `start.ps1` — PowerShell startup script that loads `.env`, activates `.venv`, and starts uvicorn on port 8080.
- Update `README.md` with Windows instructions.
- Verify the full workflow: create session → send task → see live progress → review result → resume session.

### ✓ Step 3: Phase 2: Context assembly, session resumption, and project discovery
Make conversations meaningful across sessions with proper context and project browsing.
- Implement context assembly in `hub/runner.py`: when dispatching a task, gather recent session messages, relevant memories, project guidelines, and AGENTS.md content; append as context to the agent's task prompt.
- Add session resumption to the frontend: sessions show last message preview, clicking loads the full conversation, "New session" creates a fresh one.
- Add "Save to memory" button on completed runs in the frontend, wired to `POST /api/memories`.
- Implement `GET /api/projects` to scan common directories for git repos and return project paths with metadata.
- Allow agent creation via the UI to select a discovered project directory.
- Add tests for context assembly logic and project discovery.

### ✓ Step 4: Phase 3: Provider abstraction, permissions, and safety
Abstract Junie as one provider among many, add tool permissions, and improve error handling.
- Create `hub/providers.py` with `AgentProvider` abstract base class and `JunieProvider` implementation; refactor `hub/runner.py` to use the provider interface.
- Add `permissions` field to agent config in `hub.yaml` (file_read, file_write, command_exec, git_ops, network) with safe defaults.
- Improve startup validation in `hub/api.py`: check for missing Junie, unavailable projects, invalid config, and report via `/api/status`.
- Add graceful error handling for timeouts, failed commands, and interrupted sessions in the frontend.
- Add tests for provider interface, permissions, and error scenarios.
- Update `docs/API.md` with new endpoints and `README.md` with the updated architecture and setup instructions.