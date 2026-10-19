---
sessionId: session-261019-101517-o991
---

# Requirements

### Overview & Goals
Bring AgentHub closer to a reliable, production-quality, self-hosted coding-agent control center by fixing genuine live streaming, finishing the chat UI, verifying context assembly, hardening execution, adding Git safety, and building a multi-agent coordinator — all while preserving existing working features.

### Current State (Verified)
- **341 tests**: 303 passed, 2 failed, 2 skipped
- **2 test failures**: `test_missing_binary` (FileNotFoundError not caught), `test_failed_run` (exit code 1 marked as "done")
- **Core modules**: `hub/runner.py` (716 lines), `hub/api.py` (942 lines), `hub/memory.py` (544 lines), `hub/providers.py` (379 lines), `hub/static/index.html` (978 lines)
- **SQLite persistence**: Sessions, messages, memories — working
- **SSE streaming**: Exists but only emits start/complete/end events — no incremental output
- **Context assembly**: Exists in `memory.assemble_context()` but includes current user message and has no deduplication
- **Provider abstraction**: JunieProvider, SSHProvider — working
- **Permission system**: Defined but not enforced at execution boundary
- **Frontend**: Single-page app with dashboard, chat, skills, memory pages — functional but incomplete

### Scope
**In Scope**: Fix streaming, finish chat UI, verify context assembly, harden permissions, add Git safety, build multi-agent coordinator, fix test failures, add regression tests.

**Out of Scope**: Rewriting working features, adding new dependencies, changing configuration format, breaking API contracts.

### User Stories
1. As a user, I want to see agent output in real time as it's produced, not just after completion.
2. As a user, I want to create, rename, delete, and resume chat sessions reliably.
3. As a user, I want context from my session and project to be relevant and not leak between sessions.
4. As a user, I want to see which permissions are enabled and trust they are enforced.
5. As a user, I want to see Git status and have my changes preserved.
6. As a user, I want to run multiple agents concurrently on isolated worktrees.

# Technical Design

### Current Implementation
- **hub/runner.py**: `run_agent()` spawns subprocess, `_stream_output()` thread writes to log file and accumulator, but no SSE events during execution. After completion, `_persist_run_to_session()` saves the result.
- **hub/api.py**: SSE buffer (`_sse_buffers`) maps run_id → queue.Queue. `_run()` in `api_dispatch_message()` sends `start`, `complete`/`error`, and `end` events — all after the run finishes. `api_stream_session()` finds the latest run and streams from its buffer.
- **hub/memory.py**: `assemble_context()` gathers session messages, memories, guidelines, and project files. Includes the current user message (bug). No deduplication of memories. Truncation is character-based.
- **hub/providers.py**: `JunieProvider.build_command()` returns a list (safe). `AgentPermissions.permission_flags()` generates CLI flags. Permissions are passed to the command but not validated at execution.
- **hub/static/index.html**: Single-page app. SSE handler listens for `start`, `output`, `complete`, `error`, `end` events. But `output` events are never emitted by the backend.

### Key Decisions
1. **Streaming via callback**: Instead of the SSE buffer polling the runner, the runner will accept a callback that pushes events directly to the SSE buffer. This eliminates the race condition between run completion and event emission.
2. **Bounded event retention**: Max 1000 events per run buffer, cleaned up 30 seconds after the run ends. Prevents unbounded memory growth.
3. **Context excludes current message**: The most recent user message in `assemble_context()` is excluded since it's already the current task being dispatched.
4. **Git service layer**: New `hub/git_service.py` provides Git operations behind a clear interface. No automatic merges or resets.
5. **Coordinator independent of Junie**: The multi-agent coordinator uses an adapter interface, keeping it independent of Junie's internal details.

### Proposed Changes

#### Stage 1: Fix live streaming
- **hub/runner.py**: Add `output_callback` parameter to `run_agent()`. Call it from `_stream_output()` for each line of output. Emit `output` events incrementally.
- **hub/api.py**: Pass the SSE buffer callback to `run_agent()`. Wire incremental output to the SSE stream. Support reconnecting clients by replaying buffered events. Add bounded retention.
- **hub/static/index.html**: Update SSE handler to render `output` events as incremental assistant messages.
- **tests/test_runner.py**: Add `TestStreamingOutput` with mocked agent that produces delayed output. Verify output arrives before completion.
- **tests/test_api.py**: Add `TestSSEStreaming` proving incremental events during a run.
- Fix `test_missing_binary`: Catch `FileNotFoundError` in `run_agent()` before subprocess.Popen.
- Fix `test_failed_run`: Ensure non-zero exit code marks the run as "failed".

#### Stage 2: Finish chat UI
- **hub/static/index.html**: Add session renaming, loading/empty/error states, auto-scroll that respects manual scrolling, keyboard shortcuts, responsive layout, memory editing, SSE reconnect.

#### Stage 3: Context assembly
- **hub/memory.py**: Fix `assemble_context()` to exclude current user message. Add deterministic ordering. Add memory deduplication. Add context source tracking. Add configurable budget.
- **tests/test_memory.py**: Add `TestContextAssembly` covering ordering, isolation, deduplication, truncation, and missing files.

#### Stage 4: Permissions hardening
- **hub/providers.py**: Verify command safety (already list-based).
- **hub/runner.py**: Validate project paths. Filter secrets from logs.
- **hub/api.py**: Filter sensitive fields from responses.
- **hub/static/index.html**: Display permissions for selected agent.

#### Stage 5: Git safety
- **hub/git_service.py** (new): Git status, worktree management.
- **hub/api.py**: Add `/api/git/status` and `/api/git/worktrees` endpoints.
- **hub/static/index.html**: Add Git status panel.
- **tests/test_git_service.py** (new): Test Git operations.

#### Stage 6: Multi-agent coordinator
- **hub/coordinator.py** (new): Task coordinator with dependencies, concurrency, worktree isolation.
- **hub/api.py**: Add `/api/coordinator/tasks` endpoints.
- **hub/static/index.html**: Add coordinator view.
- **tests/test_coordinator.py** (new): Test coordinator.

#### Stage 7: Tests and verification
- Run full test suite. Add regression tests. Update documentation.

# Delivery Steps

### ✓ Step 1: Fix genuine live streaming
Connect subprocess output to real-time SSE events so the UI receives incremental output as the agent runs, not just at the end.

- **hub/runner.py**: Add `output_callback` parameter to `run_agent()`. Call it from `_stream_output()` for each line of output. Emit `output` events incrementally.
- **hub/api.py**: Pass the SSE buffer callback to `run_agent()`. Wire incremental output to the SSE stream. Support reconnecting clients by replaying buffered events. Add bounded retention (max 1000 events, cleanup after 30s).
- **hub/static/index.html**: Update SSE handler to render `output` events as incremental assistant messages.
- **tests/test_runner.py**: Add `TestStreamingOutput` proving a client receives output before the mocked agent finishes.
- **tests/test_api.py**: Add `TestSSEStreaming` proving the SSE endpoint emits incremental events during a run.
- Fix `test_missing_binary`: Catch `FileNotFoundError` in `run_agent()` before subprocess.Popen.
- Fix `test_failed_run`: Ensure non-zero exit code marks the run as "failed".

### ✓ Step 2: Finish chat and session UI
Improve the existing frontend chat interface with proper session management, streaming rendering, and UX polish.

- **hub/static/index.html**: Add session renaming (inline edit on double-click), proper loading/empty/error states, automatic scroll that respects manual scrolling, keyboard shortcuts (Enter to send, Shift+Enter for newline), and responsive layout fixes.
- Improve the streaming indicator to show a proper typing animation and replace it with the final assistant message.
- Add session resumption after page refresh (restore from localStorage).
- Add memory editing (inline edit button) in the memory page.
- Ensure the SSE reconnect works properly when the connection drops.
- Add project selection in the chat input bar.

### ✓ Step 3: Verify and complete context assembly
Ensure context assembly in hub/memory.py is correct, deterministic, and respects isolation and budget.

- **hub/memory.py**: Fix `assemble_context()` to exclude the current user message (the most recent one) from conversation history. Add deterministic ordering (messages by created_at ASC, memories by relevance). Add configurable context budget with predictable truncation. Add context source tracking (which files/memories were included).
- **hub/runner.py**: Pass context source metadata to the run record so it can be inspected.
- **tests/test_memory.py**: Add `TestContextAssembly` covering ordering, project isolation, memory deduplication, missing files, truncation, and no-session scenarios.
- Ensure no conversation history leaks between sessions or projects.

### ✓ Step 4: Harden execution and permissions
Audit and harden the execution boundary to ensure permissions are enforced and commands are safe.

- **hub/providers.py**: Ensure `build_command()` uses list-based arguments (not shell string interpolation) — already done, verify.
- **hub/runner.py**: Validate project paths exist and are within allowed directories. Ensure secrets (API keys, tokens) are never logged or returned to the frontend. Improve process cleanup on timeout and failure.
- **hub/api.py**: Filter sensitive fields from API responses (e.g., runner commands, remote configs).
- **hub/static/index.html**: Display which permissions are enabled for the selected agent.
- **tests/test_providers.py**: Add tests for permission flag generation and command safety.

### ✓ Step 5: Git safety and worker isolation foundations
Add Git status inspection and safe worktree management without risky automatic behavior.

- **hub/git_service.py** (new): Create a Git service layer that detects Git repos, shows branch/status/diffs, and provides safe worktree creation/cleanup.
- **hub/api.py**: Add `/api/git/status` endpoint for the selected project. Add `/api/git/worktrees` for listing and managing worktrees.
- **hub/static/index.html**: Add a Git status panel in the chat view showing branch, changed files, and status.
- **tests/test_git_service.py** (new): Test dirty tree detection, untracked files, worktree creation, and cleanup.
- Never discard changes, reset branches, or merge automatically without explicit approval.

### ✓ Step 6: Multi-agent coordinator
Add a coordinator that can run independent tasks concurrently with isolated worktrees.

- **hub/coordinator.py** (new): Implement a task coordinator with task IDs, dependencies, statuses, and assigned workers. Support configurable concurrency limits. Give each worker its own Git worktree.
- **hub/api.py**: Add `/api/coordinator/tasks` endpoints for creating, listing, and managing coordinated tasks.
- **hub/runner.py**: Support running multiple agents concurrently (each with its own lock and worktree).
- **hub/static/index.html**: Add a coordinator view showing task plans, dependencies, and worker status.
- **tests/test_coordinator.py** (new): Test dependency handling, concurrent execution, worktree isolation, and cancellation.
- Require explicit approval before merging worker changes to the main working tree.

### ✓ Step 7: Tests, documentation, and verification
Run the full test suite, add regression tests, and update documentation.

- Run `pytest tests/` and verify all tests pass (target: 341+ tests, 0 failures).
- Add regression tests for all fixes.
- Update README.md to reflect actual implemented behavior.
- Verify the full end-to-end flow: session creation → message dispatch → streaming output → completion → persistence.
- Report remaining gaps and risks.