# Grok Bot Features Implementation Plan

## Overview & Goals
Transform AgentHub into a local, self-hosted, offline-capable AI teammate hub inspired by xAI's Grok Bot (https://x.ai/bot).
Existing "agents" become "Bots": named AI teammates that take on jobs, run in parallel, persist conversation history across reloads and restarts, maintain per-bot memory, come back when sensitive actions need human approval, run scheduled or user-taught routines, and seamlessly hand off work to each other in connected group threads.

Everything stays completely local, self-hosted, free, and offline-capable using standard library and existing dependencies. The runner commands and plugin commands remain immutable via API/UI (configured only in `hub.yaml`).

---

## Architecture & Data Design

### 1. Database Schema Extensions (`hub/memory.py` / SQLite)
- **Sessions & Messages**:
  - `sessions`: add support for group threads (connected bots) via `bot_ids` column (JSON array or comma-separated list of bots in the thread), keeping `agent_id` backwards-compatible.
  - `messages`: add columns `bot_id` (TEXT, indicates which Bot authored the message), `msg_type` (TEXT default `'message'`, can be `'message'`, `'routine_ran'`, `'handoff'`, `'approval'`, `'memory_proposal'`), and `metadata` (TEXT JSON containing structured context e.g. undo payload, approval status, handoff hops, run details).
- **Approvals**:
  - `approvals` table:
    - `id` (TEXT PRIMARY KEY)
    - `run_id` (TEXT)
    - `session_id` (TEXT)
    - `bot_id` (TEXT)
    - `action_type` (TEXT)
    - `description` (TEXT)
    - `pattern_matched` (TEXT)
    - `status` (TEXT: `'pending'`, `'approved'`, `'denied'`)
    - `created_at` (TEXT)
    - `decided_at` (TEXT)
- **Routines**:
  - `routines` table:
    - `id` (TEXT PRIMARY KEY)
    - `bot_id` (TEXT NOT NULL)
    - `name` (TEXT NOT NULL)
    - `task_text` (TEXT NOT NULL)
    - `schedule_type` (TEXT: `'interval'`, `'cron'`)
    - `schedule_value` (TEXT, e.g. interval in seconds or cron pattern)
    - `enabled` (INTEGER: 0 or 1)
    - `last_run_at` (TEXT)
    - `next_run_at` (TEXT)
    - `created_at` (TEXT)
    - `updated_at` (TEXT)

### 2. File Storage & Path Safety
- **Per-Bot Memory**:
  - Stored in `data/memory/<bot_name>.md`.
  - Name validation strictly enforced (`^[a-z0-9][a-z0-9-]{0,40}$`) preventing directory traversal.
  - Included in context assembly when assembling prompts.
- **Templates Library**:
  - Stored in `templates/<template_name>.yaml` or `.md`.
  - Local templates: Research, Vault Librarian, Bug Reproduction, Chief of Staff, Expense Manager, Email Triage, Daily Briefing, etc.
  - Path safety check prevents loading outside `templates/`.
- **Plugins**:
  - Defined in `hub.yaml` under `plugins:` section (MCP or script definitions).
  - Toggled per Bot in agent config (`plugins: [plugin_id, ...]`).
  - Read-only via UI/API; command templates never exposed or editable.

### 3. Execution, Queueing & Concurrency Engine
- **Parallel Bots**:
  - In-process coordinator & queue manager (`hub/queue_manager.py` or integrated into `hub/runner.py`).
  - Each Bot has an independent FIFO queue and dedicated execution state (`idle`, `working`, `paused`).
  - Bot A and Bot B can run simultaneously in parallel.
  - If a Bot is already running a task, incoming tasks for that Bot enter the queue with state `'queued'`.
  - Pause/Resume: when a Bot is paused, queued tasks remain in the queue and do not dispatch until resumed.
  - Respect `HUB_TIMEOUT`.

### 4. Approvals & Auto Review Engine
- Configurable sensitive action patterns in `hub.yaml` (`auto_review.sensitive_patterns`).
- As the runner process streams output or planned tool calls, the auto-review evaluator tests against patterns (e.g. `rm -rf`, `git push`, file deletions, writes outside `project_dir`, unauthorized network calls).
- When a sensitive pattern is detected:
  - An approval record is created in SQLite.
  - The run execution is paused waiting on a threading event / condition variable.
  - An SSE event `approval_required` is broadcast with details.
  - The thread renders an inline Approve / Deny card; the sidebar displays an alert badge.
  - If Approved, execution resumes; if Denied, run is aborted or cancelled.

### 5. Connected Bots & Handoffs
- A single thread can host multiple Bots.
- A Bot or user can hand off to another Bot using `@bot-name` syntax or a UI "Send to another Bot" action.
- When Bot A finishes and its output requests handoff (or contains `@<bot-name>`):
  - A thread message `"Asking <Bot B>..."` is added with `msg_type='handoff'`.
  - Bot B is queued with the current conversation context.
  - Maximum hops limit (e.g., configurable `max_handoff_hops: 5`) prevents infinite ping-pong loops.

### 6. User Interface Extensions (`hub/static/index.html`)
- Remove disabled placeholders for Memory, Routines, Plugins, Marketplace.
- Wire working UI for:
  - Live SSE streaming with reconnect and status transitions.
  - Queued status indications and Pause/Resume button per Bot.
  - Routine management in right panel (list, enable/disable, run-now) + "Save this run as a routine" and "Teach a task" modal.
  - Memory panel (view, edit, save) and thread "Updated memory for <Bot>" cards with working Undo button.
  - Inline Approve / Deny action cards and sidebar badge notifications.
  - Group thread header displaying connected Bots, with `@bot` selector or "Send to another Bot" button.
  - Plugins toggle list in the right panel.
  - Marketplace page (`#marketplace`) with template cards and "Add to my Bots" one-click action.
  - "New Bot" modal with "Describe job in a sentence" AI generator and draft editor.
  - Browser notifications (`Notification` API) and tab/badge indicators for finished runs, failures, and approvals.

---

## Phased Implementation Roadmap

### Phase 1: Persistence & Streaming
1. Extend database schema in `hub/memory.py` with migration/check logic for new columns (`bot_id`, `msg_type`, `metadata`).
2. Add helper functions in `hub/memory.py` for message metadata and bot author attribution.
3. Verify and refine SSE streaming in `hub/api.py` and `hub/static/index.html` to ensure all runs, reconnects, and thread updates persist and load accurately after browser reload or server restart.
4. Add unit and integration tests for thread and message persistence across restarts.
5. Verification: `python -m pytest tests/ -v`. Update README and Web UI Manual Checks.

### Phase 2: Queueing, Parallel Runs, Pause/Resume
1. Implement per-bot queue management in `hub/runner.py`:
   - Multiple bots can execute concurrently.
   - Each bot processes tasks strictly sequentially (one active task at a time; extra messages are queued as `'queued'`).
   - Add per-bot pause/resume state (`pause_agent(bot_id)`, `resume_agent(bot_id)`).
2. Add API endpoints:
   - `POST /api/bots/{bot_id}/pause`
   - `POST /api/bots/{bot_id}/resume`
   - `GET /api/bots/{bot_id}/queue`
3. Update UI:
   - Show queued tasks in thread and sidebar with "queued" badge/state.
   - Add Pause/Resume button in the right panel and chat header.
4. Add unit tests for concurrent parallel bots, per-bot FIFO queueing, and pause/resume.
5. Verification: `python -m pytest tests/ -v`. Update README and Web UI Manual Checks.

### Phase 3: Routines & "Teach a task"
1. Add `routines` table and CRUD operations in `hub/memory.py` (or `hub/routines.py`).
2. Implement a background routine scheduler thread that checks active schedules (interval or cron) and dispatches bot tasks.
3. Add API endpoints:
   - `GET /api/bots/{bot_id}/routines`
   - `POST /api/bots/{bot_id}/routines`
   - `PUT /api/bots/{bot_id}/routines/{routine_id}`
   - `DELETE /api/bots/{bot_id}/routines/{routine_id}`
   - `POST /api/bots/{bot_id}/routines/{routine_id}/toggle`
   - `POST /api/bots/{bot_id}/routines/{routine_id}/run`
4. Wire into UI:
   - Replace "Routines: Coming soon" with routine list, toggle switch, and "Run now" button.
   - Add "Save this run as a routine" button on successful run cards.
   - Add "Teach a task" modal where users define step-by-step instructions.
   - Display "Routine ran" cards in the chat thread.
5. Add unit and API tests for routines and the scheduler.
6. Verification: `python -m pytest tests/ -v`. Update README and Web UI Manual Checks.

### Phase 4: Bot Memory
1. Implement per-bot markdown memory file storage in `data/memory/<bot_id>.md` with strict path validation and filename sanitation.
2. Integrate bot memory into `assemble_context()` in `hub/memory.py`.
3. Add API endpoints:
   - `GET /api/bots/{bot_id}/memory`
   - `PUT /api/bots/{bot_id}/memory`
   - `POST /api/bots/{bot_id}/memory/undo`
4. Propose memory updates:
   - Post-run hook in `hub/runner.py` / `hub/api.py` checks for proposed memory updates (structured output or extraction).
   - Records proposed update with previous version snapshot for instant Undo.
   - Thread renders "Updated memory for <Bot>: <summary>" with an interactive Undo button.
5. Wire into UI:
   - Replace "Memory: Coming soon" in the right panel with a markdown memory viewer/editor.
   - Connect Undo button in thread to the undo endpoint.
6. Add unit tests for memory file safety, context assembly inclusion, update proposal, and undo.
7. Verification: `python -m pytest tests/ -v`. Update README and Web UI Manual Checks.

### Phase 5: Connected Bots & Group Threads (Handoffs)
1. Support multi-bot sessions in `hub/memory.py` and `hub/api.py`.
2. Implement handoff detector in `hub/runner.py` / `hub/api.py`:
   - Detect `@bot-name` or handoff intent in bot response.
   - Enforce configurable `max_handoff_hops` (default: 5) to prevent infinite loops.
   - Insert "Asking <Bot B>..." status message in thread.
   - Queue Bot B to execute with the accumulated thread context.
3. Add API endpoint:
   - `POST /api/sessions/{session_id}/handoff`
4. UI updates:
   - Thread displays multiple bots with their respective avatars and names.
   - "Send to another Bot" action button on messages.
   - "Asking <Bot>..." handoff indicator line.
5. Add unit tests for multi-bot sessions, @mentions, handoff queues, and hop-limit termination.
6. Verification: `python -m pytest tests/ -v`. Update README and Web UI Manual Checks.

### Phase 6: Approvals & Auto Review
1. Define `auto_review` configuration in `hub.yaml` / `hub.example.yaml`:
   ```yaml
   auto_review:
     sensitive_patterns:
       - "rm -rf"
       - "git push"
       - "curl"
       - "wget"
       - "drop table"
   ```
2. Build approval interception in `hub/runner.py` / `hub/approvals.py`:
   - Pattern scanner checks output lines in real-time.
   - When matched, execution pauses and an approval record is stored.
   - Event `approval_required` is sent via SSE.
3. Add API endpoints:
   - `GET /api/approvals/pending`
   - `POST /api/approvals/{approval_id}/approve`
   - `POST /api/approvals/{approval_id}/deny`
4. UI updates:
   - Inline Approve / Deny card rendered in chat thread.
   - Approval badge indicator on sidebar bot items.
5. Update `README.md` documenting Auto Review pattern capabilities and runner boundary limits.
6. Add unit and integration tests for sensitive pattern matching, pause/resume approval flow, and denial termination.
7. Verification: `python -m pytest tests/ -v`. Update README and Web UI Manual Checks.

### Phase 7: Plugins, Marketplace, "New Bot" from a sentence, Notifications
1. **Plugins**:
   - Add `plugins` specification in `hub.yaml` and `hub.example.yaml`.
   - Add `plugins` field to agent config.
   - API: `GET /api/plugins` (lists available plugins in `hub.yaml`), `PUT /api/bots/{bot_id}/plugins` (toggle plugins for bot).
   - UI: Replace "Plugins: Coming soon" with active plugin checkboxes.
2. **Marketplace Templates**:
   - Create local library directory `templates/` with YAML/Markdown templates (Research, Vault Librarian, Bug Reproduction, Chief of Staff, Expense Manager, Email Triage, Daily Briefing).
   - Add path-safe template reader in `hub/templates.py`.
   - API: `GET /api/marketplace/templates`, `POST /api/marketplace/templates/{template_id}/install`.
   - UI: Replace disabled Marketplace link with `#marketplace` page showcasing templates with "Add to my Bots" button.
3. **"New Bot" from a sentence**:
   - API: `POST /api/bots/generate-draft` (uses Ollama / local LLM if configured; fallback template heuristics otherwise).
   - UI: New Bot modal auto-populates name, title, description, and draft guidelines from the job sentence.
4. **Browser Notifications**:
   - Add browser `Notification` integration in UI with permission prompt.
   - Trigger desktop notification and document title/badge when a run finishes, fails, or requires approval.
5. Add comprehensive test suite in `tests/test_grok_features.py` covering all new functionality.
6. Verification: `python -m pytest tests/ -v`. Update README and Web UI Manual Checks.

