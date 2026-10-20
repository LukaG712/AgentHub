# AgentHub Grok Bot Features — Phased Plan

## Context

The codebase already has substantial infrastructure:
- **SQLite persistence** (hub/memory.py): sessions, messages, memories, approvals, routines tables
- **SSE streaming** (hub/api.py): bounded event store, reconnect support
- **Queue manager** (hub/queue_manager.py): per-bot sequential queue, parallel bots, pause/resume
- **Routines engine** (hub/routines.py): scheduler, run-now, CRUD
- **Bot memory** (hub/bot_memory.py): per-bot memory.md files
- **Auto review** (hub/auto_review.py): pattern matching for sensitive actions
- **Templates** (hub/templates.py): local YAML templates for marketplace
- **Web UI** (hub/static/index.html): messenger-style UI with design tokens from UI_SPEC.md
- **Tests** (tests/test_grok_features.py): 32 tests covering all 8 phases, all passing

All 32 Grok feature tests pass. The backend API endpoints exist for all features. The task is to ensure Phase 1 and Phase 2 are fully wired end-to-end with proper UI integration, then verify everything works.

---

## Phase 1: Persistence + Streaming + Unread/Previews

**Goal:** Ensure threads survive page reloads and restarts, run output streams live via SSE, sidebar shows real last-message previews and activity times, and unread dots work.

### What already exists
- SQLite sessions/messages tables with bot_id, msg_type, metadata
- SSE event store with bounded retention and reconnect
- `/api/sessions/{id}/stream` endpoint for SSE
- `/api/sessions/{id}` returns session with messages
- Runner persists runs to JSON files and to SQLite messages
- Web UI has SSE EventSource connection

### What needs to be done
1. **Fix handoff callback bug**: `res.output` → `res.raw_output` in api.py line 1432
2. **Unread tracking**: Add `unread_count` to session model; increment when assistant messages arrive while user isn't viewing; clear on session open. Expose in `/api/sessions` and `/api/sessions/{id}`.
3. **Sidebar previews**: Ensure `/api/sessions` returns `last_message_preview` and `updated_at` for each session so the sidebar can show real previews and times.
4. **SSE streaming verification**: Ensure the UI properly connects to `/api/sessions/{id}/stream` and updates run cards as output arrives.
5. **Thread survival**: Verify that reloading the page restores all messages from SQLite.
6. **Add unread dot to UI**: Wire the unread count to the blue dot on sidebar rows.
7. **Update README**: Document Phase 1 features.

---

## Phase 2: Queueing + Parallel Runs + Pause/Resume

**Goal:** Different bots run simultaneously; one bot runs one task at a time with extra messages queued. Pause/Resume per bot. Status shown in UI.

### What already exists
- `hub/queue_manager.py`: full queue with per-bot workers, pause/resume
- API endpoints: `/api/bots/{bot_id}/pause`, `/api/bots/{bot_id}/resume`, `/api/bots/{bot_id}/queue`
- `/api/status` includes `paused` field per agent
- `agent_status()` in runner.py checks queue_manager for paused state
- Tests verify parallel execution and sequential queueing

### What needs to be done
1. **Wire message sending through queue**: Ensure `/api/sessions/{id}/messages` uses `queue_manager.enqueue_task()` instead of direct `run_agent()` call, so tasks are properly queued.
2. **UI pause/resume buttons**: Add pause/resume controls to the right panel or thread header.
3. **UI queue display**: Show "N queued" in the sidebar or right panel when tasks are waiting.
4. **UI status pills**: Show Working/Idle/Paused/Failed status in the thread header and sidebar.
5. **HUB_TIMEOUT respect**: Verify the queue manager passes timeout to run_agent.
6. **Update README**: Document Phase 2 features.

---

## Phase 3: Routines + "Teach a task" + Sidebar Grouping
(Not in scope for this session)

## Phase 4: Memory
(Not in scope for this session)

## Phase 5: Group Threads and Handoffs
(Not in scope for this session)

## Phase 6: Approvals + Auto Review
(Not in scope for this session)

## Phase 7: Plugins, Marketplace, New Bot from Sentence
(Not in scope for this session)

## Phase 8: Primary Bot + Notifications
(Not in scope for this session)

---

## Implementation Order for Phase 1 + 2

1. Fix the `res.output` bug in api.py
2. Add unread tracking to memory.py and api.py
3. Wire message sending through queue_manager in api.py
4. Update UI for unread dots, status pills, pause/resume, queue display
5. Run `python -m pytest tests/ -v`
6. Update README.md
7. Commit
