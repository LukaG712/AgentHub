# Agent Hub features spec (backend + wiring)

Goal: add the Grok Bot-style features to Polter's backend and wire them into the existing messenger UI. Bots are named AI teammates that take on a job, work in parallel, remember how the user works, come back for approval, and can pass work to each other. Everything stays self-hosted, local, free and offline-capable.

Our existing "agents" are the Bots. The UI redesign (see `docs/UI_SPEC.md`) is already done and has quiet "Coming soon" placeholders for Memory, Routines, Plugins and Marketplace, plus disabled composer buttons. Replace placeholders with working features using the EXISTING design tokens and components. Do not restyle or restructure the UI beyond what a feature needs.

Out of scope: Grok's cloud computer / computer-use. Our Bots run the configured runner (Junie) inside their `project_dir`.

## Non-negotiable constraints

- Runner commands and plugin commands stay immutable via API/UI; they only live in `hub.yaml` on disk.
- Bearer token auth (`HUB_API_KEY`) on all `/api/*` endpoints.
- Keep name validation (`^[a-z0-9][a-z0-9-]{0,40}$`) and path-safety checks for skills, templates and memory files.
- Do not break the existing CLI (`python -m hub.cli ...`) or the config format. Extend backwards-compatibly; update `README.md` and `hub.example.yaml`.
- Free, local, offline-capable. LAN-only binding as documented. No external URLs or services.
- No real `junie` binary needed for tests: extend `tests/fake_agent.py` and add tests for every feature below. All existing tests must keep passing.
- Ask before adding any new dependency; prefer the standard library.

## Data model (suggested: SQLite)

Persist per Bot: messages, runs (status, timing, output), routines, memory notes, approvals, and "events" (system lines). Threads must survive page reloads and restarts. Event types that render as centered grey system lines in the thread: `renamed`, `routine_created`, `routine_ran`, `handoff` ("Messages from Bot A and Bot B"), `memory_updated`, `approval_requested`, `approval_resolved`.

## Features

### 1. Streaming and persistence
- Stream run output live (SSE or WebSocket) instead of polling; the UI run card updates as output arrives.
- Last-message preview and last-activity time per Bot come from the stored data, so the sidebar rows show real previews and times.
- Unread tracking per Bot (a reply arrived since the user last opened the thread) drives the blue unread dot.

### 2. Queueing, parallel Bots, pause/resume
- Different Bots run at the same time; one Bot runs one task at a time. Extra messages are queued and shown as "queued".
- Respect `HUB_TIMEOUT`.
- Pause/Resume per Bot. Status shown in the UI: Working / Idle / Paused / Failed.

### 3. Routines
- Per Bot: a routine = name + task text + schedule (cron-like or simple interval, e.g. daily, every week, every 2 weeks). Run in the background; each run appears in the thread as a normal run card, preceded by a "Routine ran" system line.
- Enable / disable / run-now, listed in the right panel (Routines section).
- Sidebar grouping: Bots are grouped by their routine schedule ("Daily", "Every week", "Every 2 weeks") and Bots without a routine go under "Unassigned" (with a count). Keep the existing "Working / Recent" grouping as the fallback when there are no routines.
- "Teach a task": a "Save this run as a routine" button on any successful run card, plus a mode where the user describes the steps once and the Bot stores them as a reusable routine it can run by name. Creating a routine adds a "Created routine ⏱ <name>" system line.

### 4. Bot memory
- Per-Bot memory file (role context, stable preferences, summaries of prior work). It is included in the task context for that Bot, and shown/editable in the right panel (Memory section). Never shared between Bots.
- After a run the Bot may propose a memory update, shown in the thread as "Updated memory for <Bot>: ..." with an Undo button.

### 5. Connected Bots, group threads, handoffs
- A thread can contain several Bots. A Bot can hand off to another (@mention in a message, or a "Send to another Bot" action on a run card).
- The thread shows system lines like "Messages from ● Bot A and ● Bot B" (colored dots and names) and the receiving Bot's reply appears in the same thread. The group thread uses the overlapping mini-avatar cluster.
- Prevent infinite handoff loops (configurable max hops in `hub.yaml`).

### 6. Approvals and Auto Review
- A step can be flagged as needing approval: show an inline Approve / Deny card in the thread, an amber badge dot on the Bot's avatar, and the run pauses until the user decides. Resolution adds an `approval_resolved` event.
- Auto Review: a configurable list of sensitive-action patterns in `hub.yaml` (deleting files, `git push`, network calls, writing outside `project_dir`, ...). When the runner's output or planned action matches, pause for approval. This is best effort based on what the runner exposes; document the limits in the README.

### 7. Plugins
- A `plugins` section in `hub.yaml` (MCP servers or local scripts), toggled per Bot in the right panel and listed on the Plugins page ("N installed", search, "Add"/toggle). Plugin definitions and commands live only in `hub.yaml`.

### 8. Marketplace (local templates)
- A `templates/` directory with YAML or Markdown-with-frontmatter Bot templates: Research, Vault Librarian, Bug Reproduction, Chief of Staff, Expense Manager, Inbox Triage, Night Shift, Daily Briefing. Each has name, one-line description, job text/guidelines, suggested skills, suggested routine (optional).
- The Marketplace page lists them (search + category chips) with an "Add" button that creates an agent from the template. The "Suggestions" cards on the New Bot page read from the same templates. No external fetching.

### 9. New Bot from a sentence
- Generate name, one-line description and draft guidelines from the "What should this Bot do?" text via a configurable local runner/LLM call; fall back to simple templates when none is configured. The user can edit the draft before saving.

### 10. Primary Bot
- One Bot can be marked the "Primary Bot": the user's go-to for everyday tasks that works proactively, unblocks work, and checks in when it needs help. It is pinned at the top of the sidebar with a small star badge on its avatar.
- First-run prompt (small modal): "Introducing Primary Bot" with "Use an existing Bot" and "Create Primary Bot". Proactive check-ins are implemented as a built-in routine (e.g. a daily "what needs attention?" pass over the other Bots' recent activity and approvals) that posts a short summary message in the Primary Bot's thread.

### 11. Notifications
- Browser notification plus the sidebar badge when a Bot finishes, fails or needs approval.

## Optional references (do not depend on them; the app must work offline)

Official Grok Bot docs describe the intended behavior of these features:
- docs.x.ai/grok-bot/skills-routines-and-automations
- docs.x.ai/grok-bot/approvals-security-and-privacy
- docs.x.ai/grok-bot/chat-and-collaboration

## Working method

1. Read the code, `README.md`, `hub.example.yaml`, `tests/` and `docs/UI_SPEC.md`, then write a phased plan in `.junie/plans`.
2. Phases, one at a time. After each phase run `python -m pytest tests/ -v`, fix failures, update the README and its "Web UI Manual Checks" list, commit, and STOP with a short summary so the user can test before continuing:
   - Phase 1: persistence + streaming + unread/previews
   - Phase 2: queueing, parallel runs, pause/resume
   - Phase 3: routines + "Teach a task" + sidebar grouping
   - Phase 4: memory
   - Phase 5: group threads and handoffs
   - Phase 6: approvals + Auto Review
   - Phase 7: plugins, marketplace templates, New Bot from a sentence
   - Phase 8: Primary Bot + notifications
