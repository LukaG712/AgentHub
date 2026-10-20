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
(COMPLETED)

**Goal:** Routines with scheduled execution, "Teach a task" to save runs as routines, and sidebar grouping by routine schedule.

### What was done
1. **"Save as routine" button**: Added to completed run cards in the chat thread (`renderBotRun`)
2. **teachRunAsRoutine function**: Prompts for routine name, calls `/api/routines/teach`, appends system message
3. **Sidebar grouping**: Bots grouped by routine schedule (Daily, Weekly, etc.) with "Unassigned" for bots without routines; falls back to Working/Recent when no routines exist
4. **Routines cache**: Loaded in `loadAllAgents` and refreshed in `pollStatus` and after teach
5. **parseScheduleLabel function**: Converts schedule values to human-readable labels
6. **README updated**: Added Routines, Teach a task, Sidebar grouping to features table and UI checklist

## Phase 4: Memory
(COMPLETED)

**Goal:** Per-Bot memory with editable notes, memory update proposals shown in chat, and Undo capability.

### What was done
1. **Backend memory functions**: Added `propose_memory_update()` and `undo_memory_update()` in `hub/memory.py` — these save previous content, write new content, and add system messages with metadata for undo
2. **Backend API endpoints**: Added `POST /api/bots/{bot_id}/memory/propose` and `POST /api/bots/{bot_id}/memory/undo` in `hub/api.py`
3. **UI Memory section**: Added "Propose update" button next to Save in the right panel Memory section
4. **UI memory update cards**: System messages with `msg_type=memory_updated` render as styled cards with "Updated memory for <Bot>" text and an Undo button
5. **UI undo function**: `undoMemoryUpdate()` restores previous content and reloads the chat to show the undo system message
6. **CSS styling**: Added `.memory-update-card` styles for the proposal cards
7. **README updated**: Added Bot Memory and Memory Undo to features table and UI checklist

## Phase 5: Group Threads and Handoffs
(COMPLETED)

**Goal:** Multi-Bot group threads, bot-to-bot handoffs with "Send to another Bot" button, handoff system messages with colored dots, and loop prevention.

### What was done
1. **UI handoff message rendering**: Messages with `msg_type=handoff` render as styled system cards with colored dots for both Bots; `msg_type=handoff_reply` renders as a reply card showing the responding Bot's name and content
2. **UI "Send to another Bot" button**: Added to completed run cards in `renderBotRun()`; opens a dialog listing other available Bots
3. **UI handoff dialog**: Modal overlay with Bot list, color dots, and cancel button; `showHandoffDialog()`, `closeHandoffDialog()`, and `executeHandoff()` functions
4. **UI group thread header**: When session has multiple `bot_ids`, the chat header shows participant avatars with overlapping circles and lists participant names
5. **UI session data storage**: `window._currentSessionData` stores session data including `bot_ids`; `updateGroupThreadHeader()` updates the header on session load
6. **CSS styling**: Added `.handoff-card`, `.handoff-reply-card`, `.group-participants`, `.btn-send-to-bot`, and `.handoff-dialog-*` styles
7. **getBotColor function**: Added alias for `getAvatarColor` used by handoff cards and group header
8. **README updated**: Added Group Threads and Handoffs to features table and UI checklist

## Phase 6: Approvals + Auto Review
(COMPLETED)

**Goal:** Human-in-the-loop approvals with auto-review pattern detection, inline Approve/Deny cards in chat, amber badge for pending approvals, and auto-review toggle in the right panel.

### What was done
1. **Backend auto-review wiring**: Added auto-review check in runner.py after each run — when enabled, checks run output against sensitive action patterns and creates approval records
2. **Backend approval_resolved messages**: Updated memory.py update_approval_status() to add approval_resolved system messages when approvals are approved or denied
3. **Backend pending approvals in /api/status**: Added pending_approvals count per bot so the sidebar can show amber badges
4. **Backend auto-review settings API**: Added GET/PUT /api/auto-review/settings endpoints for reading and toggling auto-review configuration
5. **UI approval cards**: Messages with msg_type=approval_requested render as styled cards with warning icon, description, and Approve/Deny buttons
6. **UI approval resolved cards**: Messages with msg_type=approval_resolved render as styled system messages with green (approved) or red (denied) styling
7. **UI amber badge**: Sidebar bot items show an amber dot badge when the bot has pending approvals
8. **UI auto-review panel**: Added "Auto Review" section in the right panel with toggle switch and pending approvals list
9. **UI JavaScript**: Added approveAction(), denyAction(), loadAutoReviewSettings(), toggleAutoReview(), and loadPendingApprovals() functions
10. **CSS styling**: Added .approval-card, .approval-resolved-card, .approval-badge, .btn-approve, .btn-deny, and auto-review panel styles
11. **README updated**: Added Approvals and Auto Review to features table and UI checklist

## Phase 7: Plugins, Marketplace, New Bot from Sentence
(COMPLETED)

**Goal:** Plugins toggled per Bot in the right panel, Marketplace page with local Bot templates (search + category chips), and New Bot page with sentence-based creation, avatar customization, and suggestion cards.

### What was done
1. **Verified backend complete**: templates.py provides list_templates(), get_template(), create_agent_from_template(), and generate_bot_config() for sentence-based creation
2. **Verified API complete**: GET /api/templates, GET /api/templates/{name}, POST /api/templates/{name}/apply, POST /api/agents/generate endpoints all working
3. **Verified UI Marketplace page**: Full page with search field, category chips (All, Development, Operations, Data), template cards with "Add" button, and empty state
4. **Verified UI New Bot page**: Full page with name input, description textarea, avatar color/shape customization, live preview, suggestions grid, advanced section (runner, project dir, guidelines), and "Get started" submit button
5. **Verified UI Plugins section**: Right panel Plugins section lists available plugins with enable/disable toggle per Bot
6. **Verified routing**: Hash-based routing (#marketplace, #new-bot) properly shows/hides pages
7. **Verified templates**: 7 templates in templates/ directory (research, bug-repro, chief-of-staff, daily-briefing, email-triage, expense-manager, vault-librarian)
8. **Verified sidebar navigation**: "+ New Bot" button in header, "Marketplace" link in footer
9. **README updated**: Added Plugins, Marketplace, and New Bot from Sentence to features table; updated checklist items; added Marketplace Page and New Bot Page sections

## Phase 8: Primary Bot + Notifications
(COMPLETED)

**Goal:** Primary Bot pinned at sidebar top with star badge, proactive daily check-in routine, and browser notifications when bots finish or fail.

### What was done
1. **Backend config**: Added `get_primary_bot()` and `set_primary_bot()` in `hub/config.py` to store the primary bot name in hub.yaml
2. **Backend API**: Added `POST /api/primary-bot` endpoint to set/clear the primary bot; added `is_primary` flag to each agent in `/api/status`; added `primary_bot` field to status response
3. **Proactive check-in**: When a bot is set as primary, automatically creates a "Daily Check-in" routine that reviews other bots' activity
4. **UI star badge**: Added `★` star badge on the primary bot's avatar in the sidebar
5. **UI sidebar pinning**: Primary bot pinned at the top of the sidebar under a "Primary" group label in both routine-based and fallback grouping modes
6. **UI right panel**: Added "Set as Primary Bot" / "Clear as Primary" button in the right panel for the selected bot
7. **UI toggle function**: `togglePrimaryBot()` calls the API and refreshes the sidebar and panel
8. **CSS**: Added `.primary-star-badge` styles for the amber star
9. **Notifications**: Added `requestNotificationPermission()` on app load; `showNotification()` function for browser notifications; triggered on run complete and run error via SSE events
10. **README updated**: Added Primary Bot and Notifications to features table and UI checklist

---

## Implementation Order for Phase 1 + 2

1. Fix the `res.output` bug in api.py
2. Add unread tracking to memory.py and api.py
3. Wire message sending through queue_manager in api.py
4. Update UI for unread dots, status pills, pause/resume, queue display
5. Run `python -m pytest tests/ -v`
6. Update README.md
7. Commit
